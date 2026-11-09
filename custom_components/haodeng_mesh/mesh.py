"""Connection manager for one Hao Deng / Zengge Telink mesh.

One BLE connection to any light is enough: the mesh relays commands to all
other lights and sends their status back as notifications. The manager

* picks the light with the best signal among those Home Assistant can see
  (local adapter or ESPHome Bluetooth proxies),
* logs into the mesh and keeps the connection alive,
* reconnects automatically when the connection drops or a light shows up again,
* serialises all writes through one lock.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import logging
import os
import time

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    BleakNotFoundError,
    establish_connection,
)
from homeassistant.components import bluetooth
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    DEVICE_TIMEOUT,
    KEEPALIVE_INTERVAL,
    MAX_CONNECT_CANDIDATES,
    RECONNECT_COOLDOWN,
)
from .protocol import (
    LightStatus,
    build_command,
    commands,
    decrypt_packet,
    make_pair_packet,
    make_session_key,
    normalize_mac,
    parse_notification,
)

_LOGGER = logging.getLogger(__name__)

_WRITE_GAP = 0.05  # seconds between two writes, gives the mesh time to relay
_LOGIN_SETTLE = 0.3
_CONNECT_TIMEOUT = 45


class MeshError(Exception):
    """Raised when a command cannot be delivered to the mesh."""


class MeshAuthError(MeshError):
    """The light rejected the mesh credentials."""


@dataclass(slots=True)
class MeshDevice:
    """Static info about a light in the mesh."""

    mesh_id: int
    mac: str
    name: str


@dataclass(slots=True)
class _Connection:
    client: BleakClientWithServiceCache
    mac: str
    name: str
    session_key: bytes


async def _async_esphome_subscribe(
    client: BleakClientWithServiceCache, callback: Callable[[object, bytearray], None]
) -> None:
    """Register for notifications on an ESPHome proxy without writing a CCCD.

    Uses the backend that bleak-esphome uses internally and registers the
    subscription in its bookkeeping, so stop_notify/disconnect clean it up.
    """
    backend = getattr(client, "_backend", None)
    api = getattr(backend, "_client", None)
    address = getattr(backend, "_address_as_int", None)
    cancels = getattr(backend, "_notify_cancels", None)
    if api is None or address is None or not hasattr(api, "bluetooth_gatt_start_notify"):
        raise BleakError("status characteristic has no CCCD and backend is not an ESPHome proxy")

    characteristic = client.services.get_characteristic(commands.STATUS_CHAR_UUID)
    if characteristic is None:
        raise BleakError("status characteristic not found")
    if cancels is not None and characteristic.handle in cancels:
        return  # already subscribed

    def _on_notify(_handle: int, data: bytes | bytearray) -> None:
        callback(characteristic, bytearray(data))

    cancel = await api.bluetooth_gatt_start_notify(address, characteristic.handle, _on_notify, 30.0)
    if cancels is not None:
        cancels[characteristic.handle] = cancel


class HaoDengMesh:
    """Manage the connection to a single mesh network."""

    def __init__(
        self,
        hass: HomeAssistant,
        mesh_name: str,
        mesh_password: str,
        devices: list[MeshDevice],
    ) -> None:
        self.hass = hass
        self._mesh_name = mesh_name.encode()
        self._mesh_password = mesh_password.encode()
        if len(self._mesh_name) > 16 or len(self._mesh_password) > 16:
            raise ValueError("mesh name and password can hold max 16 bytes")

        self.devices: dict[int, MeshDevice] = {d.mesh_id: d for d in devices}
        self._by_mac: dict[str, MeshDevice] = {normalize_mac(d.mac): d for d in devices}

        self._conn: _Connection | None = None
        self._connect_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._connect_task: asyncio.Task[bool] | None = None
        self._last_connect_attempt = 0.0
        self._stopping = False
        self._unsubs: list[CALLBACK_TYPE] = []

        self.status: dict[int, LightStatus] = {}
        self.last_seen: dict[int, datetime] = {}
        self.bridge_online: bool | None = None
        self.last_error: str | None = None
        self.auth_failed = False
        self._listeners: list[CALLBACK_TYPE] = []

    # ------------------------------------------------------------------ public

    @property
    def connected(self) -> bool:
        return self._conn is not None and self._conn.client.is_connected

    @property
    def connected_device(self) -> MeshDevice | None:
        if self._conn is None:
            return None
        return self._by_mac.get(self._conn.mac)

    def is_available(self, mesh_id: int) -> bool:
        if not self.connected:
            return False
        seen = self.last_seen.get(mesh_id)
        status = self.status.get(mesh_id)
        if seen is None or status is None or not status.online:
            return False
        return dt_util.utcnow() - seen < DEVICE_TIMEOUT

    @callback
    def async_add_listener(self, listener: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Register a listener called on any state change. Returns unsubscribe."""
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    async def async_start(self) -> None:
        """Start background handling. Does not wait for a connection."""
        self._stopping = False
        for mac in self._by_mac:
            self._unsubs.append(
                bluetooth.async_register_callback(
                    self.hass,
                    self._async_on_advertisement,
                    bluetooth.BluetoothCallbackMatcher(address=mac, connectable=True),
                    bluetooth.BluetoothScanningMode.PASSIVE,
                )
            )
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._async_keepalive, KEEPALIVE_INTERVAL, name="haodeng_mesh keepalive"
            )
        )
        self._schedule_connect()

    async def async_stop(self) -> None:
        self._stopping = True
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._connect_task and not self._connect_task.done():
            self._connect_task.cancel()
        await self._async_disconnect()

    async def async_reconnect(self) -> None:
        """Drop the current connection and connect again (e.g. via button)."""
        await self._async_disconnect()
        self._last_connect_attempt = 0.0
        if not await self._async_ensure_connected():
            raise MeshError(self.last_error or "no light in range")

    async def async_send(self, mesh_id: int, command: commands.Command) -> None:
        """Send a command to a light. Connects on demand, retries once."""
        for attempt in (1, 2):
            if not await self._async_ensure_connected():
                raise MeshError(self.last_error or "no light of this mesh is in Bluetooth range")
            conn = self._conn
            if conn is None:
                continue
            packet = build_command(conn.session_key, conn.mac, mesh_id, command.opcode, command.params)
            try:
                async with self._write_lock:
                    await conn.client.write_gatt_char(commands.COMMAND_CHAR_UUID, packet, True)
                    await asyncio.sleep(_WRITE_GAP)
            except (BleakError, TimeoutError, EOFError) as err:
                _LOGGER.debug("Write to %s failed (attempt %s): %s", conn.name, attempt, err)
                self.last_error = f"write failed: {err}"
                await self._async_disconnect()
                self._last_connect_attempt = 0.0
                continue
            return
        raise MeshError(self.last_error or "command could not be delivered")

    async def async_request_status(self) -> None:
        conn = self._conn
        if conn is None:
            return
        async with self._write_lock:
            await conn.client.write_gatt_char(commands.STATUS_CHAR_UUID, b"\x01", True)

    # ---------------------------------------------------------- connection

    @callback
    def _schedule_connect(self) -> None:
        if self._stopping or self.connected:
            return
        if self._connect_task and not self._connect_task.done():
            return
        if time.monotonic() - self._last_connect_attempt < RECONNECT_COOLDOWN:
            return
        self._connect_task = self.hass.async_create_background_task(
            self._async_ensure_connected(), "haodeng_mesh connect"
        )

    async def _async_ensure_connected(self) -> bool:
        if self.connected:
            return True
        async with self._connect_lock:
            if self.connected:
                return True
            if self._stopping:
                return False
            self._last_connect_attempt = time.monotonic()
            try:
                async with asyncio.timeout(_CONNECT_TIMEOUT):
                    return await self._async_connect_best()
            except TimeoutError:
                self.last_error = "connection attempt timed out"
                _LOGGER.debug("Connection attempt timed out")
                await self._async_disconnect()
                return False

    def _candidates(self) -> list[BLEDevice]:
        seen = [
            info
            for info in bluetooth.async_discovered_service_info(self.hass, connectable=True)
            if info.address.upper() in self._by_mac
        ]
        seen.sort(key=lambda info: info.rssi if info.rssi is not None else -999, reverse=True)
        return [info.device for info in seen[:MAX_CONNECT_CANDIDATES]]

    async def _async_connect_best(self) -> bool:
        candidates = self._candidates()
        if not candidates:
            self.last_error = "no light of this mesh is in Bluetooth range"
            _LOGGER.debug("No connectable light seen by any Bluetooth adapter or proxy")
            return False

        for ble_device in candidates:
            mac = ble_device.address.upper()
            name = self._by_mac[mac].name
            try:
                await self._async_connect_to(ble_device, mac, name)
            except MeshAuthError as err:
                self.auth_failed = True
                self.last_error = str(err)
                _LOGGER.error("%s", err)
                return False
            except (BleakError, BleakNotFoundError, TimeoutError, EOFError, MeshError) as err:
                self.last_error = f"{name}: {err}"
                _LOGGER.debug("Could not connect via %s (%s): %s", name, mac, err)
                continue
            self.auth_failed = False
            self.last_error = None
            _LOGGER.info("Connected to mesh via %s (%s)", name, mac)
            self._notify_listeners()
            return True
        return False

    async def _async_connect_to(self, ble_device: BLEDevice, mac: str, name: str) -> None:
        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            name,
            disconnected_callback=self._on_disconnected,
            max_attempts=2,
            ble_device_callback=lambda: (
                bluetooth.async_ble_device_from_address(self.hass, mac, connectable=True) or ble_device
            ),
        )
        try:
            session_key = await self._async_login(client, mac)
            self._conn = _Connection(client=client, mac=mac, name=name, session_key=session_key)
            await self._async_enable_notifications()
            await self.async_request_status()
        except BaseException:
            self._conn = None
            await client.disconnect()
            raise

    async def _async_login(self, client: BleakClientWithServiceCache, mac: str) -> bytes:
        session_random = os.urandom(8)
        await client.write_gatt_char(
            commands.PAIR_CHAR_UUID,
            make_pair_packet(self._mesh_name, self._mesh_password, session_random),
            True,
        )
        await asyncio.sleep(_LOGIN_SETTLE)
        reply = bytes(await client.read_gatt_char(commands.PAIR_CHAR_UUID))
        if reply[:1] == bytes([commands.PAIR_OK]) and len(reply) >= 9:
            return make_session_key(self._mesh_name, self._mesh_password, session_random, reply[1:9])
        if reply[:1] == bytes([commands.PAIR_AUTH_FAILED]):
            raise MeshAuthError(
                "The lights rejected the mesh credentials. Were they re-paired in the "
                "Hao Deng app? Reconfigure the integration to download fresh credentials."
            )
        raise MeshError(f"unexpected login reply from {mac}: {reply.hex()}")

    async def _async_enable_notifications(self) -> None:
        conn = self._conn
        assert conn is not None
        # Sequence taken from the working upstream implementation
        packet = build_command(conn.session_key, conn.mac, commands.NOTIFY_ENABLE_DEST, 0x01, b"")
        await conn.client.write_gatt_char(commands.STATUS_CHAR_UUID, packet, True)
        await asyncio.sleep(_LOGIN_SETTLE)
        try:
            await conn.client.start_notify(commands.STATUS_CHAR_UUID, self._on_notification)
        except BleakError as err:
            if "client config descriptor" not in str(err):
                raise
            # Telink lights have no CCCD on the status characteristic; they enable
            # notifications through the 0x01 write above. ESPHome proxies insist on
            # writing a CCCD and roll back, so subscribe on the proxy directly.
            _LOGGER.debug("No CCCD on status characteristic, using ESPHome proxy fallback")
            await _async_esphome_subscribe(conn.client, self._on_notification)

    async def _async_disconnect(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                await conn.client.disconnect()
            except (BleakError, TimeoutError, EOFError) as err:
                _LOGGER.debug("Error while disconnecting: %s", err)
            self._notify_listeners()

    @callback
    def _on_disconnected(self, client: BleakClientWithServiceCache) -> None:
        if self._conn is not None and self._conn.client is client:
            _LOGGER.info("Lost connection to mesh via %s", self._conn.name)
            self._conn = None
            self._notify_listeners()
        if not self._stopping:
            # Give the light a moment before reconnecting
            async_call_later(self.hass, 2, self._async_delayed_reconnect)

    @callback
    def _async_delayed_reconnect(self, _now: datetime) -> None:
        self._schedule_connect()

    @callback
    def _async_on_advertisement(
        self, service_info: bluetooth.BluetoothServiceInfoBleak, change: bluetooth.BluetoothChange
    ) -> None:
        if not self.connected and not self.auth_failed:
            self._schedule_connect()

    async def _async_keepalive(self, _now: datetime) -> None:
        if not self.connected:
            if not self.auth_failed:
                self._schedule_connect()
            self._notify_listeners()  # refresh availability
            return
        try:
            await self.async_request_status()
        except (BleakError, TimeoutError, EOFError) as err:
            _LOGGER.debug("Status request failed, reconnecting: %s", err)
            await self._async_disconnect()
            self._last_connect_attempt = 0.0
            self._schedule_connect()
        self._notify_listeners()

    # ---------------------------------------------------------- notifications

    @callback
    def _on_notification(self, _sender: object, data: bytearray) -> None:
        conn = self._conn
        if conn is None:
            return
        decrypted = decrypt_packet(conn.session_key, conn.mac, bytes(data))
        if decrypted is None:
            _LOGGER.debug("Dropping notification with invalid checksum: %s", bytes(data).hex())
            return
        changed = False
        now = dt_util.utcnow()
        for status in parse_notification(decrypted):
            if status.is_bridge:
                self.bridge_online = status.online
                continue
            if status.mesh_id not in self.devices:
                _LOGGER.debug("Status for unknown mesh id %s: %s", status.mesh_id, status)
                continue
            self.last_seen[status.mesh_id] = now
            if self.status.get(status.mesh_id) != status:
                self.status[status.mesh_id] = status
                changed = True
        if changed:
            self._notify_listeners()

    @callback
    def _notify_listeners(self) -> None:
        for listener in list(self._listeners):
            listener()
