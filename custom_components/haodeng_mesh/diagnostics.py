"""Diagnostics download (secrets redacted)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import HaoDengConfigEntry
from .const import CONF_MESH_LTK, CONF_MESH_NAME, CONF_MESH_PASSWORD

TO_REDACT = {CONF_MESH_NAME, CONF_MESH_PASSWORD, CONF_MESH_LTK}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HaoDengConfigEntry
) -> dict[str, Any]:
    mesh = entry.runtime_data
    connected = mesh.connected_device
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "mesh": {
            "connected": mesh.connected,
            "connected_via": connected.mac if connected else None,
            "last_error": mesh.last_error,
            "auth_failed": mesh.auth_failed,
            "wifi_bridge_online": mesh.bridge_online,
            "status": {
                mesh_id: {
                    "online": s.online,
                    "brightness": s.brightness,
                    "mode": s.mode,
                    "value": s.value,
                    "last_seen": mesh.last_seen.get(mesh_id),
                }
                for mesh_id, s in mesh.status.items()
            },
        },
    }
