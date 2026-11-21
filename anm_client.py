from __future__ import annotations
import io, re
from urllib.parse import urljoin
import pandas as pd
import requests
from bs4 import BeautifulSoup

HEADERS = {'User-Agent': 'FiscalizacaoMineraria/0.2 (+public-data-use)'}
DATASETS = {
    'cfem': 'https://dados.gov.br/dados/conjuntos-dados/sistema-arrecadacao',
    'cadastro_mineiro': 'https://dados.gov.br/dados/conjuntos-dados/sistema-de-cadastro-mineiro',
}
RESOURCE_URLS = {
    # Equivalentes aos botões “Acessar o recurso” dos cards do catálogo.
    'cfem': 'https://dadosabertos.anm.gov.br/CFEM/CFEM_Arrecadacao_2022_2026.csv',
    'cadastro_mineiro': 'https://dadosabertos.anm.gov.br/SCM/Licenciamento.csv',
}
EXTENSIONS = ('.csv', '.zip', '.xlsx', '.xls', '.parquet', '.json')


def _resource_links(page_url: str) -> list[str]:
    r = requests.get(page_url, headers=HEADERS, timeout=45)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    links = []
    for a in soup.select('a[href]'):
        u = urljoin(page_url, a.get('href', ''))
        if any(u.lower().split('?')[0].endswith(ext) for ext in EXTENSIONS):
            links.append(u)
    return list(dict.fromkeys(links))


def _read_bytes(name: str, raw: bytes) -> pd.DataFrame:
    low = name.lower().split('?')[0]
    if low.endswith('.csv'):
        last = None
        for enc in ('utf-8-sig', 'utf-8', 'latin1'):
            for sep in (None, ';', ','):
                try:
                    return pd.read_csv(io.BytesIO(raw), sep=sep, engine='python', encoding=enc, low_memory=False)
                except Exception as exc: last = exc
        raise ValueError(f'CSV não pôde ser lido: {last}')
    if low.endswith(('.xlsx', '.xls')): return pd.read_excel(io.BytesIO(raw))
    if low.endswith('.parquet'): return pd.read_parquet(io.BytesIO(raw))
    if low.endswith('.json'): return pd.read_json(io.BytesIO(raw))
    if low.endswith('.zip'):
        import zipfile
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = [n for n in z.namelist() if n.lower().endswith(('.csv','.xlsx','.xls','.parquet'))]
            if not names: raise ValueError('ZIP sem CSV/XLSX/Parquet legível')
            return _read_bytes(names[0], z.read(names[0]))
    raise ValueError(f'Formato não suportado: {name}')


def download_dataset(dataset: str, resource_urls: list[str] | None = None) -> tuple[pd.DataFrame, dict]:
    page = DATASETS[dataset]
    links = resource_urls or [RESOURCE_URLS[dataset]]
    if not links:
        raise RuntimeError(
            'O catálogo carregou os recursos por JavaScript e não expôs links de arquivo no HTML. '
            'Informe os links diretos dos CSVs na configuração ANM_RESOURCE_URLS.'
        )
    frames = []
    errors = []
    for url in links:
        try:
            r = requests.get(url, headers=HEADERS, timeout=(30, 300))
            r.raise_for_status()
            frames.append(_read_bytes(url, r.content))
        except Exception as exc: errors.append(f'{url}: {exc}')
    if not frames:
        raise RuntimeError('Nenhum recurso pôde ser baixado. ' + ' | '.join(errors))
    return pd.concat(frames, ignore_index=True, sort=False), {'dataset': dataset, 'page': page, 'resources': links, 'errors': errors}
