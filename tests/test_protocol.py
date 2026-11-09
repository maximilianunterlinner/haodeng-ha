"""Protocol tests: byte-exact against the proven upstream implementation."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from custom_components.haodeng_mesh.protocol import (
    build_command,
    commands,
    crypto,
    decrypt_packet,
    normalize_mac,
    parse_notification,
    rgb_to_hue_byte,
)
from custom_components.haodeng_mesh.protocol.crypto import crypt_payload, make_checksum

from .reference import upstream_packetutils as ref

MAC = "A4:C1:38:12:34:56"


@pytest.mark.parametrize("_", range(200))
def test_crypto_matches_upstream(_: int) -> None:
    key, nonce, payload = os.urandom(16), os.urandom(8), os.urandom(15)
    assert crypto.telink_encrypt(key, payload) == bytes(ref.encrypt(key, payload))
    assert make_checksum(key, nonce, payload) == bytes(ref.make_checksum(key, nonce, payload))
    assert crypt_payload(key, nonce, payload) == bytes(ref.crypt_payload(key, nonce, payload))

    name, password = b"meshname123", b"secret"
    srand, rrand = os.urandom(8), os.urandom(8)
    assert crypto.make_pair_packet(name, password, srand) == bytes(
        ref.make_pair_packet(name, password, srand)
    )
    assert crypto.make_session_key(name, password, srand, rrand) == bytes(
        ref.make_session_key(name, password, srand, rrand)
    )


@pytest.mark.parametrize("_", range(50))
def test_command_packet_matches_upstream(_: int) -> None:
    key, seq = os.urandom(16), os.urandom(3)
    dest = int.from_bytes(os.urandom(1), "little") + 1
    params = bytes([0xFF, 0x02, 50, 0x06])
    with patch.object(ref, "urandom", return_value=seq):
        expected = bytes(ref.make_command_packet(key, MAC, dest, 0xD0, params))
    assert build_command(key, MAC, dest, 0xD0, params, sequence=seq) == expected
    assert len(expected) == 20


def _device_notification(key: bytes, mac: str, plain_payload: bytes) -> bytes:
    """Encrypt a notification the way a light does (inverse of decrypt_packet)."""
    header = os.urandom(5)
    nonce = bytes(reversed(bytes.fromhex(mac.replace(":", ""))))[0:3] + header
    check = make_checksum(key, nonce, plain_payload)
    return header + check[0:2] + crypt_payload(key, nonce, plain_payload)


def test_decrypt_and_parse_notification() -> None:
    key = os.urandom(16)
    # payload starts at byte 7: [opcode][?][?] then two 5-byte node records
    payload = bytes([commands.OPCODE_NOTIFICATION, 0x11, 0x02]) + bytes(
        [3, 1, 80, 63, 170] + [0xFF, 1, 0, 0, 0]
    )
    packet = _device_notification(key, MAC, payload)

    decrypted = decrypt_packet(key, MAC, packet)
    assert decrypted is not None
    statuses = parse_notification(decrypted)
    assert len(statuses) == 2
    light, bridge = statuses
    assert (light.mesh_id, light.online, light.brightness, light.is_rgb, light.value) == (
        3,
        True,
        80,
        True,
        170,
    )
    assert light.is_on
    assert bridge.is_bridge and bridge.online

    # matches upstream decryption too
    assert decrypted == bytes(ref.decrypt_packet(key, MAC, packet))


def test_decrypt_rejects_tampered_packet() -> None:
    key = os.urandom(16)
    packet = bytearray(_device_notification(key, MAC, bytes(13)))
    packet[10] ^= 0xFF
    assert decrypt_packet(key, MAC, bytes(packet)) is None


def test_white_mode_and_offline_node() -> None:
    data = (
        bytes(7)
        + bytes([commands.OPCODE_NOTIFICATION, 0, 0])
        + bytes([5, 1, 0, 0x41, 30] + [6, 0, 50, 0x41, 10])
    )
    first, second = parse_notification(data)
    assert not first.is_rgb and not first.is_on and first.value == 30
    assert not second.online and not second.is_on


def test_other_opcode_ignored() -> None:
    assert parse_notification(bytes(7) + bytes([commands.OPCODE_STATUS_REPLY]) + bytes(12)) == []


def test_command_layouts() -> None:
    assert commands.power(True).params == bytes([0xFF, 0x01, 1])
    assert commands.power(False).params == bytes([0xFF, 0x01, 0])
    assert commands.brightness(150).params == bytes([0xFF, 0x02, 100, 0x06])
    assert commands.brightness(0).params == bytes([0xFF, 0x02, 1, 0x06])
    assert commands.rgb(255, 0, 300).params == bytes([0xFF, 0x60, 255, 0, 255])
    assert commands.color_temperature(40, 70) == commands.Command(0xE2, bytes([0xFF, 0x62, 40, 70]))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a4c138123456", "A4:C1:38:12:34:56"),
        ("a4-c1-38-12-34-56", "A4:C1:38:12:34:56"),
        ("A4:C1:38:12:34:56", "A4:C1:38:12:34:56"),
    ],
)
def test_normalize_mac(raw: str, expected: str) -> None:
    assert normalize_mac(raw) == expected


def test_normalize_mac_invalid() -> None:
    with pytest.raises(ValueError):
        normalize_mac("nope")


def test_hue_roundtrip() -> None:
    assert rgb_to_hue_byte(255, 0, 0) == 0
    assert rgb_to_hue_byte(0, 255, 0) == 85
    assert rgb_to_hue_byte(0, 0, 255) == 170
