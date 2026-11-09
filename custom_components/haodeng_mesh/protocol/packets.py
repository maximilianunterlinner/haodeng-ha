"""Building and decoding encrypted mesh packets."""

from __future__ import annotations

import os
import struct

from .crypto import crypt_payload, make_checksum

# Zengge vendor id (0x0211) as it appears on the wire.
VENDOR_ID = b"\x11\x02"
MAX_PARAMS = 10


def normalize_mac(mac: str) -> str:
    """Return a MAC address as upper case AA:BB:CC:DD:EE:FF."""
    cleaned = "".join(ch for ch in mac if ch.isalnum()).upper()
    if len(cleaned) != 12:
        raise ValueError(f"invalid MAC address: {mac!r}")
    int(cleaned, 16)  # raises ValueError on non-hex characters
    return ":".join(cleaned[i : i + 2] for i in range(0, 12, 2))


def _reversed_mac(mac: str) -> bytes:
    return bytes(reversed(bytes.fromhex(normalize_mac(mac).replace(":", ""))))


def build_command(
    session_key: bytes,
    mac: str,
    dest: int,
    opcode: int,
    params: bytes,
    sequence: bytes | None = None,
) -> bytes:
    """Build an encrypted 20-byte command packet.

    Args:
        session_key: key from the mesh login.
        mac: MAC of the light we are connected to (not the destination!).
        dest: mesh address of the destination light.
        opcode: command opcode.
        params: command parameters (max 10 bytes).
        sequence: 3 byte sequence number; random if omitted.
    """
    if len(params) > MAX_PARAMS:
        raise ValueError(f"params must be at most {MAX_PARAMS} bytes")
    seq = sequence if sequence is not None else os.urandom(3)
    if len(seq) != 3:
        raise ValueError("sequence must be 3 bytes")

    nonce = _reversed_mac(mac)[0:4] + b"\x01" + seq
    payload = (struct.pack("<H", dest) + bytes([opcode]) + VENDOR_ID + params).ljust(15, b"\x00")
    check = make_checksum(session_key, nonce, payload)
    return seq + check[0:2] + crypt_payload(session_key, nonce, payload)


def decrypt_packet(session_key: bytes, mac: str, packet: bytes) -> bytes | None:
    """Decrypt a 20-byte notification. Returns None if the checksum fails."""
    if len(packet) < 8:
        return None
    nonce = _reversed_mac(mac)[0:3] + bytes(packet[0:5])
    payload = crypt_payload(session_key, nonce, bytes(packet[7:]))
    check = make_checksum(session_key, nonce, payload)
    if check[0:2] != bytes(packet[5:7]):
        return None
    return bytes(packet[0:7]) + payload
