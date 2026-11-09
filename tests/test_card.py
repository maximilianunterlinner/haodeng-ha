"""The dashboard card is served by the integration."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.haodeng_mesh import CARD_URL


async def test_card_is_served(hass: HomeAssistant, hass_client, mock_entry, mock_mesh_io) -> None:
    assert await async_setup_component(hass, "http", {})
    hass.config.components.add("frontend")
    with patch("homeassistant.components.frontend.add_extra_js_url") as add_js:
        mock_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_entry.entry_id)
        await hass.async_block_till_done()
    add_js.assert_called_once()
    assert add_js.call_args[0][1].startswith(f"{CARD_URL}?v=")

    client = await hass_client()
    resp = await client.get(CARD_URL)
    assert resp.status == 200
    body = await resp.text()
    assert 'customElements.define("haodeng-light-card"' in body
