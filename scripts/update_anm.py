#!/usr/bin/env python3
"""Baixa snapshots publicados pela ANM.

Uso:
  python scripts/update_anm.py
  python scripts/update_anm.py --datasets cadastro_mineiro amb
  python scripts/update_anm.py --dry-run

O portal oficial da ANM aponta para páginas de conjuntos no dados.gov.br.
Como os nomes/URLs dos arquivos podem mudar, o script descobre links de
arquivos na página e permite sobrescrever URLs por variável de ambiente:
ANM_URL_CADASTRO_MINEIRO, ANM_URL_AMB, ANM_URL_CFEM, ANM_URL_SIGMINE,
ANM_URL_SIGBM.
"""
from __future__ import annotations
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import argparse, hashlib, json, os, re, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from urllib3.exceptions import InsecureRequestWarning

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'anm'
CATALOG = 'https://www.gov.br/anm/pt-br/acesso-a-informacao/dados-abertos/bases-de-dados'
DATASETS = {
    'cadastro_mineiro': 'https://dados.gov.br/dados/conjuntos-dados/sistema-de-cadastro-mineiro',
    'amb': 'https://dados.gov.br/dados/conjuntos-dados/anuario-mineral-brasileiro-amb',
    'cfem': 'https://dados.gov.br/dados/conjuntos-dados/sistema-arrecadacao',
    'sigmine': 'https://dados.gov.br/dados/conjuntos-dados/sistema-de-informacoes-geograficas-da-mineracao-sigmine',
    'sigbm': 'https://dados.gov.br/dados/conjuntos-dados/barragens-de-mineracao',
}
RESOURCE_URLS = {
    'cadastro_mineiro': 'https://dadosabertos.anm.gov.br/SCM/Licenciamento.csv',
    'cfem': 'https://dadosabertos.anm.gov.br/CFEM/CFEM_Arrecadacao_2022_2026.csv',
}
EXTENSIONS = ('.csv', '.zip', '.xlsx', '.xls', '.parquet', '.kmz', '.kml', '.json')
HEADERS = {'User-Agent': 'FiscalizacaoMineraria/0.1 (+public-data-downloader)'}
ANM_HOST = 'dadosabertos.anm.gov.br'


def discover(url: str) -> list[str]:
    override = next((os.getenv('ANM_URL_' + k.upper()) for k, v in DATASETS.items() if v == url and os.getenv('ANM_URL_' + k.upper())), None)
    if override:
        return [override]
    for name, page in DATASETS.items():
        if page == url and name in RESOURCE_URLS:
            return [RESOURCE_URLS[name]]
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    found = []
    for a in soup.select('a[href]'):
        href = urljoin(url, a['href'])
        low = href.lower().split('?')[0]
        if any(low.endswith(ext) for ext in EXTENSIONS): found.append(href)
    # Dados.gov.br pode renderizar links via HTML/JSON. Deduplica mantendo ordem.
    return list(dict.fromkeys(found))


def filename(url: str, dataset: str, index: int) -> str:
    raw = url.split('?')[0].rstrip('/').rsplit('/', 1)[-1]
    raw = re.sub(r'[^A-Za-z0-9_.-]+', '_', raw) or f'{dataset}_{index}'
    return f'{dataset}__{raw}'


def download(url: str, target: Path, dry_run: bool) -> dict:
    print(('DRY-RUN ' if dry_run else '') + f'{url} -> {target}')
    if dry_run: return {'url': url, 'file': str(target.relative_to(ROOT)), 'status': 'planned'}
    tmp = target.with_suffix(target.suffix + '.part')
    h = hashlib.sha256(); size = 0
    try:
        response = requests.get(url, headers=HEADERS, stream=True, timeout=(30, 300))
        insecure = False
    except requests.exceptions.SSLError:
        if ANM_HOST not in url.lower(): raise
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
        response = requests.get(url, headers=HEADERS, stream=True, timeout=(30, 300), verify=False)
        insecure = True
    with response as r:
        r.raise_for_status()
        with tmp.open('wb') as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk); h.update(chunk); size += len(chunk)
    tmp.replace(target)
    return {'url': url, 'file': str(target.relative_to(ROOT)), 'status': 'downloaded', 'bytes': size, 'sha256': h.hexdigest(), 'insecure_tls_fallback': insecure}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--datasets', nargs='+', choices=sorted(DATASETS), default=list(DATASETS))
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {'generated_at': datetime.now(timezone.utc).isoformat(), 'catalog': CATALOG, 'items': []}
    failures = 0
    for name in args.datasets:
        try:
            links = discover(DATASETS[name])
            if not links: print(f'[WARN] nenhum arquivo encontrado para {name}', file=sys.stderr)
            for i, link in enumerate(links, 1):
                target = OUT / filename(link, name, i)
                try: manifest['items'].append(download(link, target, args.dry_run))
                except Exception as exc:
                    failures += 1; print(f'[ERROR] {name}: {link}: {exc}', file=sys.stderr)
                    manifest['items'].append({'url': link, 'status': 'error', 'error': str(exc)})
        except Exception as exc:
            failures += 1; print(f'[ERROR] descoberta {name}: {exc}', file=sys.stderr)
            manifest['items'].append({'dataset': name, 'status': 'error', 'error': str(exc)})
    (OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    if failures: sys.exit(1)

if __name__ == '__main__': main()
