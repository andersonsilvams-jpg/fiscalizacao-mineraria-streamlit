"""Carga automática por estado: CFEM, Cadastro Mineiro, SIGMINE e limites municipais.

Cada passo é cacheado por UF (24 h) e falha de forma independente: se um passo cair, os outros seguem.
Os arquivos nacionais (CFEM e Cadastro) são filtrados pela UF logo após o download, para poupar memória.
"""
from __future__ import annotations
import pandas as pd
import streamlit as st
from anm_client import download_dataset, download_bytes
from data_utils import CONFIG, normalize
from geo_utils import municipios_ibge
from sigmine_utils import read_sigmine

TTL = 24 * 3600
# UF -> (região, estado), como aparecem no relatório "Maiores Arrecadadores" da ANM
UF_INFO = {
    'AC': ('Norte', 'Acre'), 'AL': ('Nordeste', 'Alagoas'), 'AM': ('Norte', 'Amazonas'), 'AP': ('Norte', 'Amapá'),
    'BA': ('Nordeste', 'Bahia'), 'CE': ('Nordeste', 'Ceará'), 'DF': ('Centro-Oeste', 'Distrito Federal'),
    'ES': ('Sudeste', 'Espírito Santo'), 'GO': ('Centro-Oeste', 'Goiás'), 'MA': ('Nordeste', 'Maranhão'),
    'MG': ('Sudeste', 'Minas Gerais'), 'MS': ('Centro-Oeste', 'Mato Grosso do Sul'), 'MT': ('Centro-Oeste', 'Mato Grosso'),
    'PA': ('Norte', 'Pará'), 'PB': ('Nordeste', 'Paraíba'), 'PE': ('Nordeste', 'Pernambuco'), 'PI': ('Nordeste', 'Piauí'),
    'PR': ('Sul', 'Paraná'), 'RJ': ('Sudeste', 'Rio de Janeiro'), 'RN': ('Nordeste', 'Rio Grande do Norte'),
    'RO': ('Norte', 'Rondônia'), 'RR': ('Norte', 'Roraima'), 'RS': ('Sul', 'Rio Grande do Sul'), 'SC': ('Sul', 'Santa Catarina'),
    'SE': ('Nordeste', 'Sergipe'), 'SP': ('Sudeste', 'São Paulo'), 'TO': ('Norte', 'Tocantins'),
}
UFS = sorted(UF_INFO)
PASSOS = {
    'cfem': 'CFEM (ANM)',
    'cadastro_mineiro': 'Razão social (Cadastro Mineiro)',
    'sigmine': 'SIGMINE (ANM)',
    'municipios': 'Limites municipais (IBGE)',
}


@st.cache_data(ttl=TTL, show_spinner=False, max_entries=8)
def dados_anm(dataset: str, uf: str, urls: tuple = ()):
    """CFEM já normalizada e filtrada pela UF. Retorna (df, tls_fallback, nota)."""
    df, meta = download_dataset(dataset, list(urls) or None)
    df['fonte'] = dataset
    colunas = [str(c) for c in df.columns if c != 'fonte']
    out = normalize(df)
    del df
    nota = ''
    if len(out) and out['uf'].eq('').all():
        out = out.iloc[0:0]
        nota = 'sem coluna de UF identificada: ignorado. Colunas do arquivo: ' + ', '.join(colunas[:30])
    else:
        out = out[out['uf'].eq(uf)]
    return out.reset_index(drop=True), bool(meta.get('insecure_tls_fallback')), nota


@st.cache_data(ttl=TTL, show_spinner=False, max_entries=8)
def titulares_anm(uf: str, urls: tuple = (), cnpjs: tuple = ()):
    """Razão social por CNPJ a partir do Cadastro Mineiro (que não traz UF): só os CNPJs da CFEM do estado.
    Retorna (df[cnpj, titular], tls_fallback, nota)."""
    df, meta = download_dataset('cadastro_mineiro', list(urls) or None)
    out = normalize(df)
    del df
    alvo = set(cnpjs)
    out = out[out['cnpj'].isin(alvo) & out['titular'].ne('')]
    tls = bool(meta.get('insecure_tls_fallback'))
    if out.empty:
        return pd.DataFrame(columns=['cnpj', 'titular']), tls, 'nenhum CNPJ da CFEM encontrado no Cadastro Mineiro'
    t = out.groupby('cnpj')['titular'].agg(lambda x: x.mode().iat[0]).reset_index()
    return t, tls, ''


@st.cache_data(ttl=TTL, show_spinner=False, max_entries=8)
def sigmine_uf(uf: str, modelo_url: str):
    url = modelo_url.replace('{uf}', uf).replace('{UF}', uf)
    try:
        raw, tls = download_bytes(url)
        return read_sigmine(raw, url), tls
    except Exception as exc:
        raise RuntimeError(f'{url} -> {exc}') from exc


@st.cache_data(ttl=TTL, show_spinner=False, max_entries=8)
def malha_uf(uf: str):
    return municipios_ibge(uf)


def limpar_cache():
    for f in (dados_anm, titulares_anm, sigmine_uf, malha_uf):
        f.clear()


def executar_passo(passo: str, uf: str):
    """Roda um passo. Retorna (dados, aviso_tls, mensagem). Levanta exceção se falhar."""
    if passo == 'cfem':
        urls = tuple(st.session_state.get('anm_direct_urls', {}).get(passo, []))
        df, tls, nota = dados_anm(passo, uf, urls)
        msg = f'{len(df):,} linhas em {uf}' + (f' ({nota})' if nota else '')
        if df.empty and not nota:
            msg += ' — nenhuma linha com CNPJ válido para a UF'
        return df, tls, msg
    if passo == 'cadastro_mineiro':
        cf = st.session_state.frames.get('cfem')
        cnpjs = tuple(sorted(cf['cnpj'].unique())) if cf is not None and len(cf) else ()
        if not cnpjs:
            raise RuntimeError('depende da CFEM do estado, que não foi carregada')
        urls = tuple(st.session_state.get('anm_direct_urls', {}).get(passo, []))
        df, tls, nota = titulares_anm(uf, urls, cnpjs)
        return df, tls, f'{len(df):,} razões sociais para {len(cnpjs):,} empresas' + (f' ({nota})' if nota else '')
    if passo == 'sigmine':
        df, tls = sigmine_uf(uf, CONFIG['app'].get('sigmine_url', ''))
        return df, tls, f'{len(df):,} áreas'
    if passo == 'municipios':
        gj = malha_uf(uf)
        return gj, False, f"{len(gj.get('features', []))} municípios"
    raise ValueError(f'passo desconhecido: {passo}')
