"""Limites municipais (IBGE ou KML/KMZ) e mapa Leaflet (folium) sobre OpenStreetMap."""
from __future__ import annotations
import io, json, re, unicodedata, zipfile
import xml.etree.ElementTree as ET
import pandas as pd
import requests

IBGE_MALHA = ('https://servicodados.ibge.gov.br/api/v3/malhas/estados/{uf}'
              '?formato=application/vnd.geo+json&intrarregiao=municipio&qualidade=minima')
IBGE_NOMES = 'https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios'


def chave_nome(x) -> str:
    x = unicodedata.normalize('NFKD', str(x)).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '', x)


def municipios_ibge(uf: str) -> dict:
    """GeoJSON dos municípios da UF, com a propriedade 'nome' (a malha do IBGE só traz o código)."""
    uf = uf.strip().upper()
    h = {'User-Agent': 'FiscalizacaoMineraria/0.3'}
    gj = requests.get(IBGE_MALHA.format(uf=uf), headers=h, timeout=60); gj.raise_for_status()
    nm = requests.get(IBGE_NOMES.format(uf=uf), headers=h, timeout=60); nm.raise_for_status()
    return juntar_nomes(gj.json(), {str(m['id']): m['nome'] for m in nm.json()})


def juntar_nomes(geojson: dict, nomes: dict) -> dict:
    for f in geojson.get('features', []):
        p = f.setdefault('properties', {})
        cod = str(p.get('codarea', p.get('CD_MUN', '')))
        p['nome'] = nomes.get(cod, nomes.get(cod[:7], cod))
    return geojson


# ---------------- KML / KMZ ----------------
def _tag(el):
    return el.tag.rsplit('}', 1)[-1]


def _coords(txt):
    pts = []
    for tok in txt.split():
        v = tok.split(',')
        if len(v) >= 2:
            pts.append([float(v[0]), float(v[1])])
    return pts


def ler_kml(raw: bytes, name: str = 'x.kml') -> dict:
    """KML/KMZ de municípios (Placemark + Polygon) -> GeoJSON com 'nome'."""
    if name.lower().endswith('.kmz') or raw[:2] == b'PK':
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            k = next((n for n in z.namelist() if n.lower().endswith('.kml')), None)
            if not k:
                raise ValueError('KMZ sem arquivo .kml')
            raw = z.read(k)
    root = ET.fromstring(raw)
    feats = []
    for pm in (e for e in root.iter() if _tag(e) == 'Placemark'):
        nome = next((c.text.strip() for c in pm if _tag(c) == 'name' and c.text), '')
        # ExtendedData/SimpleData também costuma trazer o nome do município
        for e in pm.iter():
            if _tag(e) in ('SimpleData', 'Data') and (e.get('name') or '').lower() in ('nm_mun', 'nome', 'municipio', 'name') and (e.text or '').strip():
                nome = e.text.strip()
        polys = []
        for pg in (e for e in pm.iter() if _tag(e) == 'Polygon'):
            aneis = []
            for ring in (e for e in pg.iter() if _tag(e) == 'LinearRing'):
                c = next((x.text for x in ring if _tag(x) == 'coordinates' and x.text), '')
                pts = _coords(c)
                if len(pts) >= 3:
                    aneis.append(pts)
            if aneis:
                polys.append(aneis)
        if not polys:
            continue
        geom = {'type': 'Polygon', 'coordinates': polys[0]} if len(polys) == 1 else {'type': 'MultiPolygon', 'coordinates': polys}
        feats.append({'type': 'Feature', 'properties': {'nome': nome}, 'geometry': geom})
    if not feats:
        raise ValueError('Nenhum polígono encontrado no KML/KMZ.')
    return {'type': 'FeatureCollection', 'features': feats}


# ---------------- estatística por município ----------------
def stats_municipio(base: pd.DataFrame, empresas: pd.DataFrame) -> pd.DataFrame:
    """Empresas (CNPJ distintos) por município, e quantas são prioridade Alta. Usa a lista da CFEM."""
    if base.empty or 'municipio' not in base:
        return pd.DataFrame(columns=['chave', 'empresas', 'alta'])
    b = base[['cnpj', 'municipio']].copy()
    if 'fonte' in base:
        b = b[base['fonte'].eq('cfem')]
    b = b[b['municipio'].ne('')].drop_duplicates()
    b = b.merge(empresas[['cnpj', 'prioridade']], on='cnpj', how='left')
    b['chave'] = b['municipio'].map(chave_nome)
    g = b.groupby('chave').agg(empresas=('cnpj', 'nunique'), alta=('prioridade', lambda s: int((s == 'Alta').sum())))
    return g.reset_index()


# ---------------- mapa Leaflet ----------------
# Mapas de fundo. O servidor do OpenStreetMap bloqueia páginas abertas direto do computador (file://, sem Referer),
# então o padrão é o CARTO (também baseado em dados do OSM); o OpenStreetMap continua disponível no seletor de camadas.
BASES = [
    ('CARTO Positron (claro)', 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
     '&copy; contribuidores do <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>', 'abcd'),
    ('OpenStreetMap', 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
     '&copy; contribuidores do <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>', 'abc'),
    ('Satélite (Esri)', 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
     'Tiles &copy; Esri, Maxar, Earthstar Geographics', 'abc'),
]

CORES = {'Alta': '#d62728', 'Média': '#ff9f1c', 'Baixa': '#2a9d8f', 'Sem base Crea': '#6c757d', 'Sem CFEM': '#9aa0a6'}


def montar_mapa(pontos: pd.DataFrame, municipios: dict | None = None, stats: pd.DataFrame | None = None,
                colorir: bool = True, extras: pd.DataFrame | None = None, altura: int = 650):
    import folium
    from folium.plugins import Fullscreen, MiniMap
    pts_all = pd.concat([x[['lat', 'lon']] for x in (pontos, extras) if x is not None and len(x)], ignore_index=True)
    if pts_all.empty and not municipios:
        raise ValueError('Nada para plotar.')
    m = folium.Map(location=[-20.5, -54.6], zoom_start=6, tiles=None, control_scale=True, prefer_canvas=True, zoom_snap=0.25)
    for i, (nome_b, url_b, attr_b, sub_b) in enumerate(BASES):
        folium.TileLayer(tiles=url_b, attr=attr_b, name=nome_b, subdomains=sub_b, max_zoom=19, show=(i == 0)).add_to(m)

    if municipios:
        smap = {}
        if stats is not None and len(stats):
            smap = stats.set_index('chave')[['empresas', 'alta']].to_dict('index')
        for f in municipios['features']:
            s = smap.get(chave_nome(f['properties'].get('nome', '')), {'empresas': 0, 'alta': 0})
            f['properties']['_empresas'] = int(s['empresas']); f['properties']['_alta'] = int(s['alta'])
        maxalta = max([f['properties']['_alta'] for f in municipios['features']] + [1])

        def estilo(f):
            a = f['properties']['_alta']
            if colorir and a > 0:
                return {'color': '#7a1f1f', 'weight': 1, 'fillColor': '#d62728', 'fillOpacity': 0.12 + 0.45 * a / maxalta}
            return {'color': '#4a5568', 'weight': 1, 'fillColor': '#000000', 'fillOpacity': 0.0}
        folium.GeoJson(municipios, name='Limites municipais', style_function=estilo,
                       highlight_function=lambda f: {'weight': 3, 'color': '#1d3557'},
                       tooltip=folium.GeoJsonTooltip(fields=['nome', '_empresas', '_alta'],
                                                     aliases=['Município', 'Empresas c/ CFEM', 'Prioridade Alta'], sticky=True)).add_to(m)

    if extras is not None and len(extras):
        fg = folium.FeatureGroup(name=f'Demais áreas SIGMINE ({len(extras):,})', show=False)
        for r in extras.itertuples():
            folium.CircleMarker([r.lat, r.lon], radius=3, color=CORES['Sem CFEM'], weight=1, fill=True, fill_opacity=0.5,
                                tooltip=f"{getattr(r, 'titular_sigmine', '') or '—'} • {getattr(r, 'fase', '')}").add_to(fg)
        fg.add_to(m)

    if len(pontos):
        for grupo in ['Sem base Crea', 'Baixa', 'Média', 'Alta']:  # Alta por último = por cima
            sub = pontos[pontos['prioridade'].eq(grupo)]
            if sub.empty:
                continue
            fg = folium.FeatureGroup(name=f'{grupo} ({sub["cnpj"].nunique():,} empresas)')
            for r in sub.itertuples():
                tip = (f"<b>{getattr(r, 'titular_sigmine', '') or '—'}</b><br>CNPJ: {r.cnpj}<br>"
                       f"CFEM: {getattr(r, 'anos_cfem', '') or '—'}<br>Fase: {getattr(r, 'fase', '')}<br>"
                       f"Substância: {getattr(r, 'substancia_sigmine', '')}<br>Processo: {getattr(r, 'processo_sigmine', '')}")
                folium.CircleMarker([r.lat, r.lon], radius=7 if grupo == 'Alta' else 5, color='#222', weight=1,
                                    fill=True, fill_color=CORES[grupo], fill_opacity=0.9, tooltip=folium.Tooltip(tip, sticky=True)).add_to(fg)
            fg.add_to(m)

    if municipios:  # enquadra no estado inteiro quando há limites
        allc = []
        for f in municipios['features']:
            g = f['geometry']; st = [g['coordinates']] if g['type'] == 'Polygon' else g['coordinates']
            for poly in st:
                allc += poly[0]
        xs = pd.Series([c[0] for c in allc]); ys = pd.Series([c[1] for c in allc])
    else:
        ys, xs = pts_all['lat'], pts_all['lon']
    m.fit_bounds([[float(ys.min()), float(xs.min())], [float(ys.max()), float(xs.max())]])
    folium.LayerControl(collapsed=False).add_to(m)
    mini = folium.TileLayer(tiles=BASES[0][1], attr=BASES[0][2], subdomains=BASES[0][3])
    Fullscreen().add_to(m); MiniMap(tile_layer=mini, toggle_display=True, zoom_level_fixed=None).add_to(m)
    return m
