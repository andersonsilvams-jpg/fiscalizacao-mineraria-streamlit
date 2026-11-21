"""Carga automática por estado: CFEM, Cadastro Mineiro, SIGMINE e limites municipais.

Cada passo é cacheado por UF (24 h) e falha de forma independente: se um passo cair, os outros seguem.
Os arquivos nacionais (CFEM e Cadastro) são filtrados pela UF logo após o download, para poupar memória.
"""
from __future__ import annotations
import streamlit as st
from anm_client import download_dataset, download_bytes
from data_utils import CONFIG, normalize
from geo_utils import municipios_ibge
from sigmine_utils import read_sigmine

TTL = 24 * 3600
UFS = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MG', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI',
       'PR', 'RJ', 'RN', 'RO', 'RR', 'RS', 'SC', 'SE', 'SP', 'TO']
PASSOS = {
    'cfem': 'CFEM (ANM)',
    'cadastro_mineiro': 'Cadastro Mineiro (ANM)',
    'sigmine': 'SIGMINE (ANM)',
    'municipios': 'Limites municipais (IBGE)',
}


@st.cache_data(ttl=TTL, show_spinner=False, max_entries=8)
def dados_anm(dataset: str, uf: str, urls: tuple = ()):
    """CFEM ou Cadastro Mineiro já normalizado e filtrado pela UF. Retorna (df, tls_fallback, nota)."""
    df, meta = download_dataset(dataset, list(urls) or None)
    df['fonte'] = dataset
    out = normalize(df)
    del df
    nota = ''
    if len(out) and out['uf'].eq('').all():
        out = out.iloc[0:0]
        nota = 'arquivo sem coluna de UF identificada: ignorado (ajuste os nomes em config.yaml > columns > uf)'
    else:
        out = out[out['uf'].eq(uf)]
    return out.reset_index(drop=True), bool(meta.get('insecure_tls_fallback')), nota


@st.cache_data(ttl=TTL, show_spinner=False, max_entries=8)
def sigmine_uf(uf: str, modelo_url: str):
    url = modelo_url.replace('{uf}', uf).replace('{UF}', uf)
    raw, tls = download_bytes(url)
    return read_sigmine(raw, url), tls


@st.cache_data(ttl=TTL, show_spinner=False, max_entries=8)
def malha_uf(uf: str):
    return municipios_ibge(uf)


def limpar_cache():
    for f in (dados_anm, sigmine_uf, malha_uf):
        f.clear()


def executar_passo(passo: str, uf: str):
    """Roda um passo. Retorna (dados, aviso_tls, mensagem). Levanta exceção se falhar."""
    if passo in ('cfem', 'cadastro_mineiro'):
        urls = tuple(st.session_state.get('anm_direct_urls', {}).get(passo, []))
        df, tls, nota = dados_anm(passo, uf, urls)
        msg = f'{len(df):,} linhas em {uf}' + (f' ({nota})' if nota else '')
        if df.empty and not nota:
            msg += ' — nenhuma linha com CNPJ válido para a UF'
        return df, tls, msg
    if passo == 'sigmine':
        df, tls = sigmine_uf(uf, CONFIG['app'].get('sigmine_url', ''))
        return df, tls, f'{len(df):,} áreas'
    if passo == 'municipios':
        gj = malha_uf(uf)
        return gj, False, f"{len(gj.get('features', []))} municípios"
    raise ValueError(f'passo desconhecido: {passo}')
