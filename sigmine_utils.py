"""Leitura do SIGMINE (ANM) e cruzamento com a CFEM para plotar em mapa.

Aceita shapefile em .zip (lido com pyshp, sem GDAL) ou GeoJSON. Cada área vira um ponto (centro do
retângulo envolvente), suficiente para visualizar onde ocorre a exploração em escala de estado.
"""
from __future__ import annotations
import io, json, re, unicodedata, zipfile
import pandas as pd


def _key(x):
    x = unicodedata.normalize('NFKD', str(x)).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '', x)


def chave_processo(num, ano=None) -> str:
    """'860.001/2010' ou ('860001', 2010) -> '860001/2010'. Vazio se não for possível montar."""
    s = '' if num is None or (isinstance(num, float) and pd.isna(num)) else str(num).strip()
    if '/' in s:
        n, a = s.split('/', 1)
    else:
        n, a = s, ano
    n = re.sub(r'\D', '', n).lstrip('0')
    a = re.sub(r'\D', '', str(a).split('.')[0]) if a is not None and not (isinstance(a, float) and pd.isna(a)) else ''
    return f'{n}/{a}' if n and len(a) == 4 else ''


def _flatten(coords, out):
    if coords and isinstance(coords[0], (int, float)):
        out.append(coords)
    else:
        for c in coords:
            _flatten(c, out)


def _centro(xmin, ymin, xmax, ymax):
    if not (-180 <= xmin <= 180 and -180 <= xmax <= 180 and -90 <= ymin <= 90 and -90 <= ymax <= 90):
        raise ValueError('As coordenadas do arquivo não estão em graus (CRS projetado?). Use a versão em SIRGAS 2000/WGS84.')
    return (ymin + ymax) / 2, (xmin + xmax) / 2


def _linha(props: dict, lat, lon) -> dict:
    p = {_key(k): v for k, v in props.items()}
    get = lambda *ks: next((p[k] for k in ks if k in p and p[k] not in (None, '')), '')
    processo = get('processo', 'nup')
    chave = chave_processo(processo, get('ano')) if '/' in str(processo) else chave_processo(get('numero', 'processo'), get('ano'))
    return {'chave': chave, 'processo_sigmine': processo, 'titular_sigmine': str(get('nome', 'titular')).strip(),
            'fase': str(get('fase')).strip(), 'substancia_sigmine': str(get('subs', 'substancia')).strip(),
            'uso': str(get('uso')).strip(), 'area_ha': get('areaha', 'area'), 'uf_sigmine': str(get('uf')).strip().upper()[:2],
            'lat': lat, 'lon': lon}


def _ler_shapefile_zip(raw: bytes) -> pd.DataFrame:
    import shapefile  # pyshp
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        nomes = z.namelist()
        shp = next((n for n in nomes if n.lower().endswith('.shp')), None)
        if not shp:
            geo = next((n for n in nomes if n.lower().endswith(('.geojson', '.json'))), None)
            if geo:
                return _ler_geojson(z.read(geo))
            raise ValueError('ZIP sem .shp ou .geojson')
        base = shp[:-4].lower()
        achar = lambda ext: next((n for n in nomes if n.lower() == base + ext), None)
        dbf, shx, cpg = achar('.dbf'), achar('.shx'), achar('.cpg')
        if not dbf:
            raise ValueError('ZIP sem o arquivo .dbf')
        enc = z.read(cpg).decode('ascii', 'ignore').strip() if cpg else 'latin1'
        r = shapefile.Reader(shp=io.BytesIO(z.read(shp)), dbf=io.BytesIO(z.read(dbf)),
                             shx=io.BytesIO(z.read(shx)) if shx else None, encoding=enc or 'latin1')
        linhas = []
        for sr in r.iterShapeRecords():
            sh = sr.shape
            if getattr(sh, 'bbox', None):
                xmin, ymin, xmax, ymax = sh.bbox
            elif sh.points:
                xmin = xmax = sh.points[0][0]; ymin = ymax = sh.points[0][1]
            else:
                continue
            lat, lon = _centro(xmin, ymin, xmax, ymax)
            linhas.append(_linha(sr.record.as_dict(), lat, lon))
    return pd.DataFrame(linhas)


def _ler_geojson(raw: bytes) -> pd.DataFrame:
    gj = json.loads(raw.decode('utf-8-sig'))
    feats = gj.get('features', [gj] if gj.get('type') == 'Feature' else [])
    linhas = []
    for f in feats:
        g = f.get('geometry') or {}
        pts = []
        _flatten(g.get('coordinates', []), pts)
        if not pts:
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        lat, lon = _centro(min(xs), min(ys), max(xs), max(ys))
        linhas.append(_linha(f.get('properties') or {}, lat, lon))
    return pd.DataFrame(linhas)


def read_sigmine(raw: bytes, name: str) -> pd.DataFrame:
    low = name.lower().split('?')[0]
    if low.endswith('.zip'):
        df = _ler_shapefile_zip(raw)
    elif low.endswith(('.geojson', '.json')):
        df = _ler_geojson(raw)
    else:
        raise ValueError('Formato não suportado: use .zip (shapefile) ou .geojson')
    if df.empty:
        raise ValueError('Nenhuma geometria encontrada no arquivo.')
    return df


def pontos_empresas(base: pd.DataFrame, empresas: pd.DataFrame, sig: pd.DataFrame):
    """Cruza os processos da CFEM (por empresa) com o SIGMINE. Retorna (pontos, estatísticas)."""
    cols = [c for c in ('cnpj', 'processo', 'ano_processo') if c in base]
    rows = base
    if 'fonte' in rows:
        rows = rows[rows['fonte'].eq('cfem')]
    rows = rows[cols].drop_duplicates()
    rows = rows[rows['processo'].ne('')] if 'processo' in rows else rows.iloc[0:0]
    ap = rows['ano_processo'] if 'ano_processo' in rows else [None] * len(rows)
    rows = rows.assign(chave=[chave_processo(p, a) for p, a in zip(rows['processo'], ap)])
    validos = rows[rows['chave'].ne('')]
    sig_u = sig[sig['chave'].ne('')]
    casados = validos.merge(sig_u, on='chave', how='inner').drop_duplicates(['cnpj', 'chave', 'lat', 'lon'])
    extra = [c for c in ('prioridade', 'anos_cfem', 'ultimo_ano_cfem', 'municipio', 'registro_crea') if c in empresas]
    pontos = casados.merge(empresas[['cnpj'] + extra], on='cnpj', how='left')
    stats = {
        'processos_cfem': int(len(validos)), 'sem_chave': int(len(rows) - len(validos)),
        'localizados': int(validos['chave'].isin(sig_u['chave']).sum()),
        'exemplo_cfem': validos['chave'].head(5).tolist(), 'exemplo_sigmine': sig_u['chave'].head(5).tolist(),
        'chaves_casadas': set(casados['chave']),
    }
    return pontos, stats
