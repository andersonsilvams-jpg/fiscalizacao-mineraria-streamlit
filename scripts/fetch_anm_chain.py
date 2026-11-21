#!/usr/bin/env python3
"""Gera certs/anm_chain.pem com os certificados intermediários da ANM (rodar uma vez, na sua máquina).

O servidor da ANM não envia o certificado intermediário. Este script lê o certificado do servidor,
segue o endereço "CA Issuers" (AIA) embutido nele e salva a cadeia. Requer: pip install cryptography
"""
from __future__ import annotations
import ssl, sys, urllib.request
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID

HOST = 'dadosabertos.anm.gov.br'
HOSTS = ('dadosabertos.anm.gov.br', 'app.anm.gov.br')  # CSVs da CFEM/Cadastro e shapefiles do SIGMINE
OUT = Path(__file__).resolve().parents[1] / 'certs' / 'anm_chain.pem'


def ca_issuer_url(cert):
    try:
        aia = cert.extensions.get_extension_for_oid(ExtensionOID.AUTHORITY_INFORMATION_ACCESS).value
    except x509.ExtensionNotFound:
        return None
    for d in aia:
        if d.access_method == AuthorityInformationAccessOID.CA_ISSUERS:
            return d.access_location.value
    return None


def load_any(data: bytes):
    for loader in (lambda d: [x509.load_der_x509_certificate(d)], lambda d: [x509.load_pem_x509_certificate(d)],
                   pkcs7.load_der_pkcs7_certificates, pkcs7.load_pem_pkcs7_certificates):
        try:
            return loader(data)
        except ValueError:
            continue
    raise ValueError('formato de certificado não reconhecido')


def build_chain(host=HOST, port=443):
    cur = x509.load_pem_x509_certificate(ssl.get_server_certificate((host, port)).encode())
    chain = []
    for _ in range(4):
        url = ca_issuer_url(cur)
        if not url:
            break
        print('baixando', url)
        certs = load_any(urllib.request.urlopen(url, timeout=30).read())
        nxt = next((c for c in certs if c.subject == cur.issuer), None)
        if nxt is None:
            break
        chain.append(nxt)
        if nxt.subject == nxt.issuer:
            break
        cur = nxt
    return chain


def main(host=HOST, port=443, out=OUT):
    chain = build_chain(host, port)
    if not chain:
        sys.exit('Não foi possível obter o certificado intermediário (o certificado do servidor não informa o AIA).')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b''.join(c.public_bytes(serialization.Encoding.PEM) for c in chain))
    print(f'{len(chain)} certificado(s) salvo(s) em {out}')
    for c in chain:
        print(' -', c.subject.rfc4514_string())


def main_todos(hosts=HOSTS, out=OUT):
    vistos, chain = set(), []
    for h in hosts:
        try:
            print('host', h)
            for c in build_chain(h):
                if c.fingerprint(hashes.SHA256()) not in vistos:
                    vistos.add(c.fingerprint(hashes.SHA256())); chain.append(c)
        except Exception as exc:
            print(f'  aviso: {h}: {exc}')
    if not chain:
        sys.exit('Não foi possível obter nenhum certificado intermediário.')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b''.join(c.public_bytes(serialization.Encoding.PEM) for c in chain))
    print(f'{len(chain)} certificado(s) salvo(s) em {out}')


if __name__ == '__main__':
    main_todos(tuple(sys.argv[1:]) or HOSTS)
