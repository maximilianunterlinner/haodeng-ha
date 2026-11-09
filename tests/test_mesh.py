"""Mesh manager tests with a simulated light (no real Bluetooth)."""

from __future__ import annotations

import os
from unittest.mock import patch

from bleak.exc import BleakError
from homeassistant.core import HomeAssistant
import pytest

from custom_components.haodeng_mesh.mesh import (
    HaoDengMesh,
    MeshAuthError,
    MeshDevice,
    MeshError,
    _Connection,
)
from custom_components.haodeng_mesh.protocol import commands, decrypt_packet
from custom_components.haodeng_mesh.protocol.crypto import crypt_payload, make_checksum

from .test_protocol import _device_notification

MAC = "A4:C1:38:00:00:03"


class FakeLight:
    """Simulates the GATT side of a Telink mesh light."""

    def __init__(self, accept: bool = True) -> None:
        self.accept = accept
        self.is_connected = True
        self.writes: list[tuple[str, bytes]] = []
        self.fail_writes = 0
        self.response_random = os.urandom(8)
        self.notify_cb = None

    async def write_gatt_char(self, uuid: str, data: bytes, response: bool = True) -> None:
        if self.fail_writes:
            self.fail_writes -= 1
            raise BleakError("simulated write failure")
        self.writes.append((uuid, bytes(data)))

    async def read_gatt_char(self, uuid: str) -> bytes:
        assert uuid == commands.PAIR_CHAR_UUID
        if not self.accept:
            return bytes([commands.PAIR_AUTH_FAILED]) + bytes(16)
        return bytes([commands.PAIR_OK]) + self.response_random + bytes(8)

    async def start_notify(self, uuid: str, cb) -> None:
        self.notify_cb = cb

    async def disconnect(self) -> None:
        self.is_connected = False


def _mesh(hass: HomeAssistant) -> HaoDengMesh:
    return HaoDengMesh(
        hass,
        "meshname",
        "meshpass",
        [MeshDevice(3, MAC, "Spot"), MeshDevice(4, "A4:C1:38:00:00:04", "Küche")],
    )


async def test_login_derives_session_key(hass: HomeAssistant) -> None:
    mesh, light = _mesh(hass), FakeLight()
    key = await mesh._async_login(light, MAC)
    uuid, pair_packet = light.writes[0]
    assert uuid == commands.PAIR_CHAR_UUID and pair_packet[0] == 0x0C
    from custom_components.haodeng_mesh.protocol import make_session_key

    assert key == make_session_key(b"meshname", b"meshpass", pair_packet[1:9], light.response_random)


async def test_login_rejected(hass: HomeAssistant) -> None:
    with pytest.raises(MeshAuthError):
        await _mesh(hass)._async_login(FakeLight(accept=False), MAC)


async def test_notification_updates_status(hass: HomeAssistant) -> None:
    mesh, light = _mesh(hass), FakeLight()
    key = os.urandom(16)
    mesh._conn = _Connection(client=light, mac=MAC, name="Spot", session_key=key)
    calls = []
    mesh.async_add_listener(lambda: calls.append(1))

    payload = bytes([commands.OPCODE_NOTIFICATION, 0, 0]) + bytes([4, 1, 60, 0x41, 20, 0xFF, 1, 0, 0, 0])
    mesh._on_notification(None, bytearray(_device_notification(key, MAC, payload)))

    assert mesh.status[4].brightness == 60
    assert mesh.bridge_online is True
    assert mesh.is_available(4) and not mesh.is_available(3)
    assert calls == [1]

    # identical status again -> no listener call
    mesh._on_notification(None, bytearray(_device_notification(key, MAC, payload)))
    assert calls == [1]


async def test_send_encrypts_for_destination(hass: HomeAssistant) -> None:
    mesh, light = _mesh(hass), FakeLight()
    key = os.urandom(16)
    mesh._conn = _Connection(client=light, mac=MAC, name="Spot", session_key=key)
    await mesh.async_send(4, commands.power(True))

    uuid, packet = light.writes[-1]
    assert uuid == commands.COMMAND_CHAR_UUID
    # decrypt like the light would: nonce = mac[0:4] + 0x01 + seq
    nonce = bytes(reversed(bytes.fromhex(MAC.replace(":", ""))))[0:4] + b"\x01" + packet[0:3]
    plain = crypt_payload(key, nonce, packet[5:])
    assert make_checksum(key, nonce, plain)[0:2] == packet[3:5]
    assert plain[0:2] == (4).to_bytes(2, "little")
    assert plain[2] == commands.OPCODE_STATE
    assert plain[5:8] == bytes([0xFF, 0x01, 1])


async def test_send_reconnects_after_write_failure(hass: HomeAssistant) -> None:
    mesh = _mesh(hass)
    first, second = FakeLight(), FakeLight()
    first.fail_writes = 1
    mesh._conn = _Connection(client=first, mac=MAC, name="Spot", session_key=os.urandom(16))

    async def reconnect() -> bool:
        mesh._conn = _Connection(client=second, mac=MAC, name="Spot", session_key=os.urandom(16))
        return True

    with patch.object(mesh, "_async_connect_best", side_effect=reconnect):
        await mesh.async_send(3, commands.power(False))
    assert not first.is_connected
    assert second.writes and second.writes[-1][0] == commands.COMMAND_CHAR_UUID


async def test_send_without_lights_in_range(hass: HomeAssistant) -> None:
    mesh = _mesh(hass)
    with patch.object(mesh, "_candidates", return_value=[]), pytest.raises(MeshError):
        await mesh.async_send(3, commands.power(True))
    assert "range" in (mesh.last_error or "")


async def test_decrypt_helper_consistency() -> None:
    key = os.urandom(16)
    payload = bytes(13)
    assert decrypt_packet(key, MAC, _device_notification(key, MAC, payload)) is not None
