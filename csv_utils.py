"""Leitura robusta de CSV (ANM e uploads) sem depender de detecção automática."""
from __future__ import annotations
import io
import pandas as pd

ENCODINGS = ('utf-8-sig', 'latin1')  # latin1 nunca falha na decodificação: fica por último
SEPARATORS = (';', ',', '\t', '|')


def _detect_sep(raw: bytes, encoding: str) -> str:
    head = raw[:65536].decode(encoding, errors='replace')
    first = next((ln for ln in head.splitlines() if ln.strip()), '')
    counts = {s: first.count(s) for s in SEPARATORS}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ';'


def read_csv_bytes(raw: bytes) -> pd.DataFrame:
    """Lê CSV tentando: encoding -> separador detectado pelo cabeçalho -> engine C -> engine python.

    Tudo é lido como texto (dtype=str); a normalização converte o que for necessário.
    Todas as falhas são acumuladas para aparecer na mensagem de erro final.
    """
    errors = []
    for enc in ENCODINGS:
        sep = _detect_sep(raw, enc)
        attempts = (
            ('c', dict(low_memory=False)),   # rápido; low_memory só existe no engine C
            ('python', dict()),              # tolerante; NÃO aceita low_memory
        )
        for engine, extra in attempts:
            try:
                df = pd.read_csv(
                    io.BytesIO(raw), sep=sep, encoding=enc, engine=engine,
                    dtype=str, on_bad_lines='skip', **extra,
                )
                if df.shape[1] > 1 and len(df):
                    return df
                errors.append(f'{enc}/{engine}/sep={sep!r}: apenas {df.shape[1]} coluna(s)')
            except Exception as exc:
                errors.append(f'{enc}/{engine}/sep={sep!r}: {exc}')
    raise ValueError('CSV não pôde ser lido. Tentativas: ' + ' || '.join(errors))
