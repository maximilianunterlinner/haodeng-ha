"""Cloud client: request format and response parsing (HTTP mocked)."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.haodeng_mesh.cloud import CloudAuthError, HaoDengCloud, _checkcode

BASE = "http://eumeshcloud.magichue.net:8081/MeshClouds/apixp"


async def test_full_download(aioclient_mock: AiohttpClientMocker, hass) -> None:
    aioclient_mock.post(
        f"{BASE}/User001/LoginForUser/ZG",
        json={"ok": True, "result": {"userId": "me@example.com", "auth_token": "tok", "deviceSecret": "x"}},
    )
    aioclient_mock.get(
        f"{BASE}/MeshData/GetMyMeshPlaceItems/ZG",
        json={
            "ok": True,
            "result": [
                {
                    "placeUniID": "p1",
                    "displayName": "Zuhause",
                    "meshKey": "mk",
                    "meshPassword": "mp",
                    "meshLTK": "ltk",
                },
                {"placeUniID": "p2"},  # incomplete -> skipped
            ],
        },
    )
    aioclient_mock.get(
        f"{BASE}/MeshData/GetMyMeshDeviceItems/ZG",
        json={
            "ok": True,
            "result": [
                {
                    "meshAddress": 3,
                    "macAddress": "A4:C1:38:00:00:03",
                    "displayName": "Spot",
                    "deviceType": 65,
                },
                {"meshAddress": 255, "macAddress": "A4:C1:38:00:00:FF", "wiringType": 0},  # skipped
                {"meshAddress": 0, "macAddress": "A4:C1:38:00:00:05"},  # skipped
            ],
        },
    )
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    cloud = HaoDengCloud(async_get_clientsession(hass), "eu")
    await cloud.login("me@example.com", "secret")
    login_body = aioclient_mock.mock_calls[0][2]
    assert login_body["password"] == "5ebe2294ecd0e0f08eab7690d2a6ee69"  # md5("secret")
    assert len(login_body["checkcode"]) == 32  # one AES block

    places = await cloud.places()
    assert [(p.place_id, p.name, p.mesh_name) for p in places] == [("p1", "Zuhause", "mk")]
    devices = await cloud.devices("p1")
    assert [(d.mesh_id, d.name) for d in devices] == [(3, "Spot")]
    headers = aioclient_mock.mock_calls[2][3]
    assert headers["token"] == "tok"
    assert str(aioclient_mock.mock_calls[2][1]).endswith("placeUniID=p1&userId=me@example.com")


async def test_login_rejected(aioclient_mock: AiohttpClientMocker, hass) -> None:
    aioclient_mock.post(f"{BASE}/User001/LoginForUser/ZG", json={"ok": False, "err_msg": "wrong password"})
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    with pytest.raises(CloudAuthError):
        await HaoDengCloud(async_get_clientsession(hass)).login("a", "b")


def test_checkcode_matches_upstream() -> None:
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    ts = "1700000000000"
    padder = padding.PKCS7(algorithms.AES(b"0FC154F9C01DFA9656524A0EFABC994F").block_size).padder()
    data = padder.update(("ZG" + ts).encode()) + padder.finalize()
    enc = Cipher(algorithms.AES(b"0FC154F9C01DFA9656524A0EFABC994F"), modes.ECB()).encryptor()
    assert _checkcode(ts) == (enc.update(data) + enc.finalize()).hex()
