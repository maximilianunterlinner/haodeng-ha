"""Hao Deng / Zengge Bluetooth mesh lights - local control."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_DEVICES,
    CONF_MESH_NAME,
    CONF_MESH_PASSWORD,
    CONF_PLACE_NAME,
    DEV_MAC,
    DEV_MESH_ID,
    DEV_NAME,
    DOMAIN,
)
from .mesh import HaoDengMesh, MeshDevice

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.LIGHT,
    Platform.SENSOR,
]

type HaoDengConfigEntry = ConfigEntry[HaoDengMesh]


async def async_setup_entry(hass: HomeAssistant, entry: HaoDengConfigEntry) -> bool:
    """Set up a mesh from a config entry."""
    mesh = HaoDengMesh(
        hass,
        entry.data[CONF_MESH_NAME],
        entry.data[CONF_MESH_PASSWORD],
        [
            MeshDevice(mesh_id=d[DEV_MESH_ID], mac=d[DEV_MAC], name=d[DEV_NAME])
            for d in entry.data[CONF_DEVICES]
        ],
    )
    entry.runtime_data = mesh

    # Hub device that all lights hang off (via_device)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"Hao Deng Mesh {entry.data.get(CONF_PLACE_NAME, '')}".strip(),
        manufacturer="Zengge",
        model="Telink Bluetooth mesh",
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await mesh.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HaoDengConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_stop()
    return unload_ok
