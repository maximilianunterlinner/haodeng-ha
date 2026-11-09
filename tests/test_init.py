"""Full setup with the real Home Assistant Bluetooth stack (no lights in range)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.haodeng_mesh.const import DOMAIN


async def test_setup_without_lights_in_range(hass: HomeAssistant, mock_entry, mock_bluetooth: None) -> None:
    mock_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.state is ConfigEntryState.LOADED

    mesh = mock_entry.runtime_data
    assert not mesh.connected
    assert mesh.last_error == "no light of this mesh is in Bluetooth range"
    assert hass.states.get("light.wohnzimmer_spot").state == STATE_UNAVAILABLE
    assert hass.states.get("light.kuche").state == STATE_UNAVAILABLE
    assert hass.states.get("binary_sensor.hao_deng_mesh_zuhause_mesh_connection").state == STATE_OFF

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), mock_entry.entry_id)
    assert {d.name for d in devices} == {
        "Hao Deng Mesh Zuhause",
        "Wohnzimmer Spot",
        "Küche",
        "Alle Spots",
        "Nur Küche",
    }
    assert all(d.via_device_id for d in devices if d.name != "Hao Deng Mesh Zuhause")
    spot = next(d for d in devices if d.name == "Wohnzimmer Spot")
    assert spot.via_device_id is not None
    assert spot.model == "RGBCW Spot"
    assert (DOMAIN, "a4c138000003") in spot.identifiers

    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.state is ConfigEntryState.NOT_LOADED
