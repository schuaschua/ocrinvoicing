"""A throwaway OpenPGP RSA key pair for the Story 1.6 tests, built in memory with
`cryptography` (no gpg on the build agent needed, and no key material in git).

pgcrypto skips the primary key and encrypts to the first encryption subkey, and it
checks no signatures, so a primary key packet plus one subkey packet (the same RSA
key) is enough for `pgp_pub_encrypt` and `pgp_pub_decrypt`.
"""

import base64
import time
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric import rsa

_RSA = 1  # OpenPGP public-key algorithm: RSA (encrypt or sign)
_PUBLIC_KEY, _SECRET_KEY, _SECRET_SUBKEY, _PUBLIC_SUBKEY = 6, 5, 7, 14


@dataclass(frozen=True)
class PgpKeyPair:
    public_key: str  # ASCII-armoured, as the `pgp-public-key` secret holds it
    private_key: str  # ASCII-armoured; only the test ever decrypts


def _mpi(value: int) -> bytes:
    return value.bit_length().to_bytes(2, "big") + value.to_bytes(
        (value.bit_length() + 7) // 8, "big"
    )


def _packet(tag: int, body: bytes) -> bytes:
    # New-format header with a 5-octet length.
    return bytes([0xC0 | tag, 0xFF]) + len(body).to_bytes(4, "big") + body


def _crc24(data: bytes) -> int:
    crc = 0xB704CE
    for byte in data:
        crc ^= byte << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    return crc & 0xFFFFFF


def _armour(kind: str, data: bytes) -> str:
    text = base64.b64encode(data).decode()
    lines = [text[i : i + 64] for i in range(0, len(text), 64)]
    checksum = base64.b64encode(_crc24(data).to_bytes(3, "big")).decode()
    return "\n".join(
        [f"-----BEGIN PGP {kind} KEY BLOCK-----", "", *lines, f"={checksum}"]
        + [f"-----END PGP {kind} KEY BLOCK-----", ""]
    )


def make_test_key_pair() -> PgpKeyPair:
    """A new RSA 2048 key pair, armoured as `gpg --armor --export(-secret-keys)`."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.private_numbers()
    public = numbers.public_numbers
    created = int(time.time()).to_bytes(4, "big")
    public_body = bytes([4]) + created + bytes([_RSA]) + _mpi(public.n) + _mpi(public.e)
    # OpenPGP's u is p^-1 mod q (RFC 4880 5.5.3).
    secret_mpis = (
        _mpi(numbers.d)
        + _mpi(numbers.p)
        + _mpi(numbers.q)
        + _mpi(pow(numbers.p, -1, numbers.q))
    )
    # S2K usage 0 (not encrypted), then the MPIs and their 2-octet checksum.
    secret_body = (
        public_body
        + bytes([0])
        + secret_mpis
        + (sum(secret_mpis) % 65536).to_bytes(2, "big")
    )
    public_blob = _packet(_PUBLIC_KEY, public_body) + _packet(
        _PUBLIC_SUBKEY, public_body
    )
    secret_blob = _packet(_SECRET_KEY, secret_body) + _packet(
        _SECRET_SUBKEY, secret_body
    )
    return PgpKeyPair(
        public_key=_armour("PUBLIC", public_blob),
        private_key=_armour("PRIVATE", secret_blob),
    )
