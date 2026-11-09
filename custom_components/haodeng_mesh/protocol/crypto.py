"""Telink BLE mesh cryptography (as used by Zengge / Hao Deng lights).

Telink uses AES-128-ECB with byte-reversed key, input and output. On top of
that, it builds a CCM-like scheme: a 2-byte MAC ("checksum") computed in
CBC-MAC style and a CTR-style keystream for the payload.

This module has no Home Assistant dependency so it can be unit tested on its own.
"""

from __future__ import annotations

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

BLOCK_SIZE = 16


def _pad16(value: bytes) -> bytes:
    if len(value) > BLOCK_SIZE:
        raise ValueError(f"value must be at most {BLOCK_SIZE} bytes, got {len(value)}")
    return value.ljust(BLOCK_SIZE, b"\x00")


def telink_encrypt(key: bytes, value: bytes) -> bytes:
    """Encrypt one block the Telink way (reversed AES-128-ECB)."""
    if len(key) != BLOCK_SIZE:
        raise ValueError("key must be exactly 16 bytes")
    encryptor = Cipher(algorithms.AES(bytes(reversed(key))), modes.ECB()).encryptor()
    block = bytes(reversed(_pad16(bytes(value))))
    result = encryptor.update(block) + encryptor.finalize()
    return bytes(reversed(result))


def _xor(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right, strict=False))


def make_checksum(key: bytes, nonce: bytes, payload: bytes) -> bytes:
    """Compute the CBC-MAC style checksum over the plaintext payload."""
    check = telink_encrypt(key, _pad16(nonce + bytes([len(payload)])))
    for offset in range(0, len(payload), BLOCK_SIZE):
        chunk = _pad16(payload[offset : offset + BLOCK_SIZE])
        check = telink_encrypt(key, _xor(check, chunk))
    return check


def crypt_payload(key: bytes, nonce: bytes, payload: bytes) -> bytes:
    """CTR-style payload encryption. The same call decrypts."""
    base = bytearray(_pad16(b"\x00" + nonce))
    result = bytearray()
    for offset in range(0, len(payload), BLOCK_SIZE):
        keystream = telink_encrypt(key, bytes(base))
        result += _xor(keystream, payload[offset : offset + BLOCK_SIZE])
        base[0] = (base[0] + 1) & 0xFF
    return bytes(result)


def _name_xor_password(mesh_name: bytes, mesh_password: bytes) -> bytes:
    return _xor(_pad16(mesh_name), _pad16(mesh_password))


def make_pair_packet(mesh_name: bytes, mesh_password: bytes, session_random: bytes) -> bytes:
    """Build the login packet written to the pairing characteristic."""
    if len(session_random) != 8:
        raise ValueError("session_random must be 8 bytes")
    encrypted = telink_encrypt(_pad16(session_random), _name_xor_password(mesh_name, mesh_password))
    return b"\x0c" + session_random + encrypted[:8]


def make_session_key(
    mesh_name: bytes, mesh_password: bytes, session_random: bytes, response_random: bytes
) -> bytes:
    """Derive the session key from both randoms and the mesh credentials."""
    return telink_encrypt(_name_xor_password(mesh_name, mesh_password), session_random + response_random)
