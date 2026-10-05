"""Validate vaulted EMQX PEM material before changing the production stack."""

import json
import sys
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import serialization


def main() -> None:
    material = json.load(sys.stdin)
    ca = x509.load_pem_x509_certificate(material["ca_cert"].encode())
    cert = x509.load_pem_x509_certificate(material["server_cert"].encode())
    key = serialization.load_pem_private_key(
        material["server_key"].encode(), password=None
    )

    now = datetime.now(timezone.utc)
    if ca.not_valid_before_utc > now or ca.not_valid_after_utc <= now + timedelta(
        days=30
    ):
        raise ValueError("The MQTT CA is not currently valid for at least 30 days")
    if cert.not_valid_before_utc > now or cert.not_valid_after_utc <= now + timedelta(
        days=30
    ):
        raise ValueError(
            "The MQTT server certificate is not valid for at least 30 days"
        )
    if not ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
        raise ValueError("The MQTT issuer must be a CA")
    if cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
        raise ValueError("The MQTT server certificate must not be a CA")
    if "emqx-main" not in cert.extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    ).value.get_values_for_type(x509.DNSName):
        raise ValueError("The MQTT server certificate needs DNS:emqx-main")
    if (
        x509.ExtendedKeyUsageOID.SERVER_AUTH
        not in cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    ):
        raise ValueError("The MQTT server certificate needs serverAuth")
    ca.verify_directly_issued_by(ca)
    cert.verify_directly_issued_by(ca)

    encoding = serialization.Encoding.DER
    public_format = serialization.PublicFormat.SubjectPublicKeyInfo
    if cert.public_key().public_bytes(
        encoding, public_format
    ) != key.public_key().public_bytes(encoding, public_format):
        raise ValueError("The MQTT certificate and private key do not match")


if __name__ == "__main__":
    main()
