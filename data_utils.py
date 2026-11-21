from __future__ import annotations
import io, re, unicodedata
from pathlib import Path
import pandas as pd
import yaml
from csv_utils import read_csv_bytes

ROOT = Path(__file__).parent
CONFIG = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8'))
ALIASES = CONFIG['columns']


def _key(x):
    x = unicodedata.normalize('NFKD', str(x)).encode('ascii','ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '', x)


def find_col(df, logical):
    aliases = {_key(x) for x in ALIASES.get(logical, [])}
    for c in df.columns:
        if _key(c) in aliases:
            return c
    # Fallback: qualquer coluna cujo nome contenha 'cnpj' (ex.: CPF_CNPJ, CNPJ_Titular).
    if logical == 'cnpj':
        for c in df.columns:
            if 'cnpj' in _key(c):
                return c
    return None


def clean_doc(value, length=None):
    s = re.sub(r'\D', '', str(value)) if pd.notna(value) else ''
    if length and len(s) != length: return ''
    return s


def read_uploaded(uploaded):
    name = uploaded.name.lower()
    raw = uploaded.getvalue()
    if name.endswith('.csv'):
        return read_csv_bytes(raw)
    if name.endswith(('.xlsx','.xls')):
        return pd.read_excel(io.BytesIO(raw))
    if name.endswith('.parquet'):
        return pd.read_parquet(io.BytesIO(raw))
    raise ValueError('Formato não suportado. Use CSV, XLSX ou Parquet.')


def _coluna_ano(df):
    """Quando 'ano' não casou pelos aliases: coluna 'AnoXxx' (exceto do processo) ou data de recolhimento/crédito."""
    for c in df.columns:
        k = _key(c)
        if k.startswith('ano') and 'process' not in k:
            return c
    for c in df.columns:
        k = _key(c)
        if 'data' in k and any(t in k for t in ('recolh', 'credit', 'arrecad', 'pagament', 'compet')):
            return c
    return None


def _num(v):
    """'1.234,56' -> 1234.56 ; '1234.56' -> 1234.56."""
    s = str(v).strip() if pd.notna(v) else ''
    if not s:
        return float('nan')
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return float('nan')


def normalize(df):
    if df is None or df.empty: return pd.DataFrame()
    out = df.copy()
    out.columns = [str(c).replace('\ufeff', '').replace('ï»¿', '').strip() for c in out.columns]
    mapping = {}
    for logical in ALIASES:
        c = find_col(out, logical)
        if c: mapping[c] = logical
    out = out.rename(columns=mapping)
    origem_ano = next((c for c, l in mapping.items() if l == 'ano'), None)
    if origem_ano is None:
        origem_ano = _coluna_ano(out)
        if origem_ano is not None:
            out['ano'] = pd.to_numeric(out[origem_ano].astype(str).str.extract(r'((?:19|20)\d{2})')[0], errors='coerce')
    if origem_ano is not None:
        out['_ano_coluna'] = origem_ano
    for c in ['uf','municipio','titular','substancia','fase','processo']:
        if c not in out: out[c] = ''
        out[c] = out[c].fillna('').astype(str).str.strip()
    if 'cnpj' not in out: out['cnpj'] = ''
    out['cnpj'] = out['cnpj'].map(lambda x: clean_doc(x, 14))
    if 'cpf' in out:
        out['cpf'] = out['cpf'].map(lambda x: clean_doc(x, 11))
    # Regra explícita do projeto: pessoas físicas/linhas sem CNPJ não entram na base empresarial.
    out = out[out['cnpj'].str.len().eq(14)].copy()
    if 'ano' in out:
        out['ano'] = pd.to_numeric(out['ano'], errors='coerce').astype('Int64')
    if 'valor' in out:
        out['valor'] = out['valor'].map(_num)
    out['uf'] = out['uf'].str.upper().str[:2]
    out['municipio'] = out['municipio'].str.title()
    out['empresa_key'] = out['cnpj']
    return out


def enrich(df, crea_df=None):
    if df.empty: return df
    out = df.copy()
    out['tem_indicio_operacao'] = out['fase'].str.lower().str.contains('lavra|concess|licen|registro|requerimento de lavra|disponibilidade', regex=True, na=False)
    if 'quantidade' in out:
        out['tem_indicio_operacao'] = out['tem_indicio_operacao'] | out['quantidade'].notna()
    if crea_df is not None and not crea_df.empty:
        c = normalize(crea_df)
        reg = c[['cnpj']].drop_duplicates().assign(registro_crea=True)
        out = out.merge(reg, on='cnpj', how='left')
        out['registro_crea'] = out['registro_crea'].fillna(False)
    else:
        out['registro_crea'] = pd.NA
    return out


ORDEM_PRIORIDADE = {'Alta': 0, 'Média': 1, 'Baixa': 2, 'Sem base Crea': 3}


def company_summary(df):
    """Uma linha por CNPJ, com CFEM por ano e prioridade.

    Prioridade (exige a base do Crea carregada):
      Alta  = sem registro no Crea e CFEM recolhida em ano recente (indício forte de que ainda opera)
      Média = sem registro no Crea, CFEM apenas em anos anteriores
      Baixa = com registro no Crea
    """
    if df.empty: return df
    agg = {
        'titular': lambda x: next((v for v in x if v), ''),
        'uf': 'first',
        'municipio': lambda x: ', '.join(sorted(set(v for v in x if v))),
        'processo': lambda x: x[x.ne('')].nunique(),
        'substancia': lambda x: ', '.join(sorted(set(v for v in x if v))),
        'registro_crea': 'first',
    }
    resumo = df.groupby('cnpj', as_index=False).agg(agg).rename(columns={'processo': 'qtd_processos'})

    # CFEM por ano (somente linhas da CFEM quando a origem está marcada)
    cf = df[df['ano'].notna()] if 'ano' in df else df.iloc[0:0]
    if 'fonte' in cf: cf = cf[cf['fonte'].eq('cfem')]
    anos_cols = []
    if len(cf):
        if 'valor' in cf and cf['valor'].notna().any():
            pv = cf.groupby(['cnpj', 'ano'])['valor'].sum().unstack(fill_value=0)
        else:
            pv = cf.groupby(['cnpj', 'ano']).size().unstack(fill_value=0)
        pv.columns = [f'CFEM {int(a)}' for a in pv.columns]
        anos_cols = list(pv.columns)
        resumo = resumo.merge(pv, left_on='cnpj', right_index=True, how='left')
        resumo[anos_cols] = resumo[anos_cols].fillna(0)
        anos_txt = pv.gt(0).apply(lambda r: ', '.join(c.split()[-1] for c, ok in r.items() if ok), axis=1)
        resumo['anos_cfem'] = resumo['cnpj'].map(anos_txt).fillna('')
        resumo['ultimo_ano_cfem'] = resumo['cnpj'].map(cf.groupby('cnpj')['ano'].max()).astype('Int64')
        ano_ref = int(cf['ano'].max())
    else:
        resumo['ultimo_ano_cfem'] = pd.array([pd.NA] * len(resumo), dtype='Int64')
        resumo['anos_cfem'] = ''
        ano_ref = None

    janela = int(CONFIG['app'].get('anos_recentes', 2))
    recente = resumo['ultimo_ano_cfem'].notna() & (resumo['ultimo_ano_cfem'].fillna(0) >= (ano_ref or 0) - janela + 1)
    if df['registro_crea'].notna().any():
        sem_reg = resumo['registro_crea'].eq(False)
        resumo['prioridade'] = 'Baixa'
        resumo.loc[sem_reg, 'prioridade'] = 'Média'
        resumo.loc[sem_reg & recente, 'prioridade'] = 'Alta'
    else:
        resumo['prioridade'] = 'Sem base Crea'

    resumo = resumo.sort_values(by=['prioridade', 'qtd_processos'], key=lambda c: c.map(ORDEM_PRIORIDADE) if c.name == 'prioridade' else -c)
    # texto legível (a prioridade acima já foi calculada com o valor booleano)
    resumo['registro_crea'] = resumo['registro_crea'].map(lambda v: 'SEM BASE CREA' if pd.isna(v) else ('SIM' if v else 'NÃO'))
    ordem = ['cnpj', 'titular', 'uf', 'municipio', 'prioridade', 'registro_crea', 'anos_cfem', 'ultimo_ano_cfem'] + anos_cols + ['qtd_processos', 'substancia']
    return resumo[ordem].reset_index(drop=True)


def fmt_cnpj(value):
    """00000000000000 -> 00.000.000/0000-00 (como texto, o Excel preserva os zeros à esquerda)."""
    d = clean_doc(value)
    if len(d) < 14:
        d = d.zfill(14) if d else ''
    return f'{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}' if len(d) == 14 else d


def export_frames(df):
    """Retorna (csv_bytes, xlsx_bytes) com CNPJ mascarado e como texto."""
    out = df.copy()
    if 'cnpj' in out:
        out['cnpj'] = out['cnpj'].map(fmt_cnpj)
    csv = out.to_csv(index=False, sep=';').encode('utf-8-sig')
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        out.to_excel(w, index=False, sheet_name='fila')
    return csv, buf.getvalue()
