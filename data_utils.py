from __future__ import annotations
import io, re, unicodedata
from pathlib import Path
import pandas as pd
import yaml

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
    return None


def clean_doc(value, length=None):
    s = re.sub(r'\D', '', str(value)) if pd.notna(value) else ''
    if length and len(s) != length: return ''
    return s


def read_uploaded(uploaded):
    name = uploaded.name.lower()
    raw = uploaded.getvalue()
    if name.endswith('.csv'):
        for enc in ('utf-8-sig', 'latin1'):
            try: return pd.read_csv(io.BytesIO(raw), sep=None, engine='python', encoding=enc)
            except Exception: pass
    if name.endswith(('.xlsx','.xls')):
        return pd.read_excel(io.BytesIO(raw))
    if name.endswith('.parquet'):
        return pd.read_parquet(io.BytesIO(raw))
    raise ValueError('Formato não suportado. Use CSV, XLSX ou Parquet.')


def normalize(df):
    if df is None or df.empty: return pd.DataFrame()
    out = df.copy()
    mapping = {}
    for logical in ALIASES:
        c = find_col(out, logical)
        if c: mapping[c] = logical
    out = out.rename(columns=mapping)
    for c in ['uf','municipio','titular','substancia','fase','processo']:
        if c not in out: out[c] = ''
        out[c] = out[c].fillna('').astype(str).str.strip()
    if 'cnpj' not in out: out['cnpj'] = ''
    out['cnpj'] = out['cnpj'].map(lambda x: clean_doc(x, 14))
    if 'cpf' in out:
        out['cpf'] = out['cpf'].map(lambda x: clean_doc(x, 11))
    # Regra explícita do projeto: pessoas físicas/linhas sem CNPJ não entram na base empresarial.
    out = out[out['cnpj'].str.len().eq(14)].copy()
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
    out['prioridade'] = 'Baixa'
    out.loc[out['tem_indicio_operacao'].eq(True), 'prioridade'] = 'Média'
    out.loc[out['tem_indicio_operacao'].eq(True) & out['registro_crea'].eq(False), 'prioridade'] = 'Alta'
    return out


def company_summary(df):
    if df.empty: return df
    agg = {'titular':'first','uf':'first','municipio':lambda x: ', '.join(sorted(set(v for v in x if v))), 'processo':'count','substancia':lambda x: ', '.join(sorted(set(v for v in x if v))), 'prioridade':'max','registro_crea':'first'}
    return df.groupby('cnpj', as_index=False).agg(agg).rename(columns={'processo':'qtd_processos'})
