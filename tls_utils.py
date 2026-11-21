"""Verificação TLS do host da ANM usando a cadeia intermediária salva em certs/anm_chain.pem."""
from __future__ import annotations
import tempfile
from pathlib import Path
import certifi

CHAIN = Path(__file__).parent / 'certs' / 'anm_chain.pem'


def anm_verify():
    """Retorna o caminho de um bundle (certifi + cadeia da ANM) ou None se a cadeia não existir."""
    if not CHAIN.exists():
        return None
    out = Path(tempfile.gettempdir()) / 'anm_bundle.pem'
    out.write_text(Path(certifi.where()).read_text() + '\n' + CHAIN.read_text())
    return str(out)
