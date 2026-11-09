"""Minimal client for the Hao Deng (Zengge / MagicHue) cloud.

The cloud is only used during setup / reconfiguration to download the mesh
credentials and the list of lights. Normal operation is 100 % local.
"""

from __future__ import annotations

import binascii
from dataclasses import dataclass, field
import hashlib
import logging
import time
from typing import Any

import aiohttp
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_LOGGER = logging.getLogger(__name__)

# Region -> API host. The app picks the server by country; most of Europe uses "eu".
REGION_SERVERS: dict[str, str] = {
    "eu": "eumeshcloud.magichue.net:8081",
    "us": "usmeshcloud.magichue.net:8081",
    "cn": "cnmeshcloud.magichue.net:8081",
    "au": "oameshcloud.magichue.net:8081",
    "jp": "dymeshcloud.magichue.net:8081",
    "tt": "ttmeshcloud.magichue.net:8081",
}
DEFAULT_REGION = "eu"

_BASE_PATH = "/MeshClouds/apixp"
_LOGIN = "/User001/LoginForUser/ZG"
_PLACES = "/MeshData/GetMyMeshPlaceItems/ZG"
_DEVICES = "/MeshData/GetMyMeshDeviceItems/ZG"
_GROUPS = "/MeshData/GetMyMeshGroupInfoItems/ZG"

# Static key the app uses to sign the timestamp of the login request
_CHECKCODE_KEY = b"0FC154F9C01DFA9656524A0EFABC994F"
_HEADERS = {
    "User-Agent": "HaoDeng/1.5.7(ANDROID,10,en-US)",
    "Accept-Language": "en-US",
    "Accept": "application/json",
}
_TIMEOUT = aiohttp.ClientTimeout(total=20)


class CloudError(Exception):
    """Generic cloud error (network, unexpected response)."""


class CloudAuthError(CloudError):
    """Login rejected."""


@dataclass
class CloudPlace:
    """A 'place' (home) in the app. Each place is its own mesh network."""

    place_id: str
    name: str
    mesh_name: str
    mesh_password: str
    mesh_ltk: str
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


@dataclass
class CloudDevice:
    """A light as listed in the cloud."""

    mesh_id: int
    mac: str
    name: str
    model: str | None
    manufacturer: str | None
    firmware: str | None
    device_type: int | None
    groups: list[int] = field(default_factory=list)


@dataclass
class CloudGroup:
    """A group as defined in the app. group_id is the mesh destination address."""

    group_id: int
    name: str


def _checkcode(timestamp: str) -> str:
    padder = padding.PKCS7(128).padder()
    padded = padder.update(("ZG" + timestamp).encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(_CHECKCODE_KEY), modes.ECB()).encryptor()
    return binascii.hexlify(encryptor.update(padded) + encryptor.finalize()).decode()


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if data.get(key) not in (None, ""):
            return data[key]
    return None


class HaoDengCloud:
    """Async client. Pass Home Assistant's shared aiohttp session."""

    def __init__(self, session: aiohttp.ClientSession, region: str = DEFAULT_REGION) -> None:
        if region not in REGION_SERVERS:
            raise ValueError(f"unknown region {region}")
        self._session = session
        self._base = f"http://{REGION_SERVERS[region]}{_BASE_PATH}"
        self._user_id: str | None = None
        self._token: str | None = None

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {**_HEADERS, "token": self._token or ""}
        try:
            async with self._session.request(
                method, self._base + path, headers=headers, timeout=_TIMEOUT, **kwargs
            ) as resp:
                if resp.status != 200:
                    raise CloudError(f"HTTP {resp.status} for {path}")
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CloudError(f"cannot reach Hao Deng cloud: {err}") from err

        if not isinstance(data, dict):
            raise CloudError(f"unexpected response for {path}")
        if data.get("ok") is False:
            message = data.get("err_msg") or data.get("error") or "unknown error"
            if path == _LOGIN:
                raise CloudAuthError(message)
            raise CloudError(message)
        return data.get("result")

    async def login(self, username: str, password: str) -> None:
        timestamp = str(int(time.time() * 1000))
        payload = {
            "userID": username,
            "password": hashlib.md5(password.encode()).hexdigest(),
            "appSys": "Android",
            "timestamp": timestamp,
            "appVer": "",
            "checkcode": _checkcode(timestamp),
        }
        result = await self._request("POST", _LOGIN, json=payload)
        try:
            self._user_id = result["userId"]
            self._token = result["auth_token"]
        except (KeyError, TypeError) as err:
            raise CloudError("login response without token") from err

    async def places(self) -> list[CloudPlace]:
        result = await self._request("GET", _PLACES, params={"userId": self._user_id or ""})
        places: list[CloudPlace] = []
        for item in result or []:
            if not item.get("placeUniID") or not item.get("meshKey"):
                _LOGGER.debug("Skipping incomplete place entry: %s", list(item))
                continue
            places.append(
                CloudPlace(
                    place_id=item["placeUniID"],
                    name=_first(item, "displayName", "placeName", "name") or item["placeUniID"],
                    mesh_name=item["meshKey"],
                    mesh_password=item.get("meshPassword", ""),
                    mesh_ltk=item.get("meshLTK", ""),
                    raw=item,
                )
            )
        return places

    async def devices(self, place_id: str) -> list[CloudDevice]:
        result = await self._request(
            "GET", _DEVICES, params={"placeUniID": place_id, "userId": self._user_id or ""}
        )
        devices: list[CloudDevice] = []
        for item in result or []:
            mesh_id = item.get("meshAddress")
            mac = item.get("macAddress")
            if not mesh_id or not mac:
                _LOGGER.debug("Skipping device without mesh address/MAC: %s", item)
                continue
            if item.get("wiringType") == 0:
                # Upstream observed these entries are not controllable lights
                _LOGGER.debug("Skipping device with wiringType 0: %s", item)
                continue
            devices.append(
                CloudDevice(
                    mesh_id=int(mesh_id),
                    mac=mac,
                    name=item.get("displayName") or f"Light {mesh_id}",
                    model=item.get("modelName"),
                    manufacturer=item.get("vendor"),
                    firmware=item.get("firmwareRevision"),
                    device_type=item.get("deviceType"),
                    groups=[
                        int(item[f"group{i}ID"])
                        for i in range(1, 9)
                        if item.get(f"group{i}ID") not in (None, 0, "0")
                    ],
                )
            )
        return devices

    async def groups(self, place_id: str) -> list[CloudGroup]:
        result = await self._request(
            "GET", _GROUPS, params={"placeUniID": place_id, "userId": self._user_id or ""}
        )
        groups: list[CloudGroup] = []
        for item in result or []:
            try:
                group_id = int(item.get("groupID") or 0)
            except (TypeError, ValueError):
                group_id = 0
            if not 0 < group_id <= 0xFFFF:
                _LOGGER.debug("Skipping group with invalid id: %s", item)
                continue
            groups.append(CloudGroup(group_id=group_id, name=item.get("groupName") or f"Group {group_id}"))
        return groups
