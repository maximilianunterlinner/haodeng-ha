"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haodeng_mesh.const import (
    CONF_DEVICES,
    CONF_GROUPS,
    CONF_MESH_LTK,
    CONF_MESH_NAME,
    CONF_MESH_PASSWORD,
    CONF_PLACE_ID,
    CONF_PLACE_NAME,
    CONF_REGION,
    DOMAIN,
)

ENTRY_DATA = {
    CONF_PLACE_ID: "place-1",
    CONF_PLACE_NAME: "Zuhause",
    CONF_REGION: "eu",
    CONF_MESH_NAME: "meshname",
    CONF_MESH_PASSWORD: "meshpass",
    CONF_MESH_LTK: "ltk",
    CONF_DEVICES: [
        {
            "mesh_id": 3,
            "mac": "A4:C1:38:00:00:03",
            "name": "Wohnzimmer Spot",
            "model": "RGBCW_Spot",
            "manufacturer": "Zengge",
            "firmware": "1.0",
            "device_type": 65,
            "groups": [32771],
        },
        {
            "mesh_id": 4,
            "mac": "A4:C1:38:00:00:04",
            "name": "Küche",
            "model": None,
            "manufacturer": None,
            "firmware": None,
            "device_type": 65,
            "groups": [32771, 32772],
        },
    ],
    CONF_GROUPS: [
        {"group_id": 32771, "name": "Alle Spots"},
        {"group_id": 32772, "name": "Nur Küche"},
        {"group_id": 32773, "name": "Leere Gruppe"},
    ],
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in all tests."""


@pytest.fixture
def mock_entry() -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, unique_id="place-1", title="Zuhause", data=ENTRY_DATA)


@pytest.fixture
def mock_mesh_io() -> Generator[dict[str, AsyncMock]]:
    """Stub out all Bluetooth I/O of the mesh manager."""
    with (
        patch("custom_components.haodeng_mesh.mesh.HaoDengMesh.async_start", new=AsyncMock()) as start,
        patch("custom_components.haodeng_mesh.mesh.HaoDengMesh.async_stop", new=AsyncMock()) as stop,
        patch("custom_components.haodeng_mesh.mesh.HaoDengMesh.async_send", new=AsyncMock()) as send,
    ):
        yield {"start": start, "stop": stop, "send": send}
