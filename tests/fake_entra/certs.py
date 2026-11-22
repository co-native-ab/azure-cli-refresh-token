"""A throwaway certificate authority and server certificate for the fake identity provider.

Test tooling only. The files are written to a temporary directory the caller owns and deletes.
"""

import datetime
import ipaddress
import pathlib

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def _name(common_name):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _write_key(path, key):
    path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))


def create(directory):
    """Write ``ca.pem``, ``server.pem`` and ``server-key.pem`` into ``directory``.

    The server certificate is valid for ``127.0.0.1`` for one day and signed by a new CA.
    """
    directory = pathlib.Path(directory)
    now = datetime.datetime.now(datetime.timezone.utc)
    not_before = now - datetime.timedelta(minutes=5)
    not_after = now + datetime.timedelta(days=1)

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = _name('Fake identity provider test CA')
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, key_cert_sign=True, crl_sign=True,
            content_commitment=False, key_encipherment=False, data_encipherment=False,
            key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
                       critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    server_key = ec.generate_private_key(ec.SECP256R1())
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(_name('127.0.0.1'))
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.SubjectAlternativeName(
            [x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()),
                       critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                       critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    ca_path = directory / 'ca.pem'
    server_path = directory / 'server.pem'
    key_path = directory / 'server-key.pem'
    ca_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    server_path.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    _write_key(key_path, server_key)
    return ca_path, server_path, key_path
