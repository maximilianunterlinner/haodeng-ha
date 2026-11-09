"""Diagnostics must not leak mesh credentials."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.haodeng_mesh.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_redacted(hass: HomeAssistant, mock_entry, mock_mesh_io) -> None:
    mock_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    diag = await async_get_config_entry_diagnostics(hass, mock_entry)
    text = repr(diag)
    assert "meshpass" not in text and "meshname" not in text
    assert diag["entry"]["mesh_password"] == "**REDACTED**"
    assert len(diag["entry"]["devices"]) == 2
