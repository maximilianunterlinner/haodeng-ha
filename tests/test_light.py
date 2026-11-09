"""Light entity tests (mesh I/O stubbed)."""

from __future__ import annotations

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    DOMAIN as LIGHT_DOMAIN,
    ColorMode,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest

from custom_components.haodeng_mesh.mesh import _Connection
from custom_components.haodeng_mesh.protocol import LightStatus, commands

from .test_mesh import FakeLight

ENTITY = "light.wohnzimmer_spot"


def _push(entry, status: LightStatus) -> None:
    mesh = entry.runtime_data
    mesh.status[status.mesh_id] = status
    mesh.last_seen[status.mesh_id] = dt_util.utcnow()
    mesh._notify_listeners()


@pytest.fixture
async def setup(hass: HomeAssistant, mock_entry, mock_mesh_io):
    mock_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.state is ConfigEntryState.LOADED
    # pretend we are connected
    mock_entry.runtime_data._conn = _Connection(
        client=FakeLight(), mac="A4:C1:38:00:00:03", name="Wohnzimmer Spot", session_key=bytes(16)
    )
    return mock_entry


async def test_unavailable_until_status(hass: HomeAssistant, setup) -> None:
    assert hass.states.get(ENTITY).state == STATE_UNAVAILABLE
    _push(setup, LightStatus(3, True, 50, 0x41, 0))
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state.state == STATE_ON
    assert state.attributes[ATTR_BRIGHTNESS] == 128
    assert state.attributes[ATTR_COLOR_MODE] == ColorMode.COLOR_TEMP
    assert state.attributes[ATTR_COLOR_TEMP_KELVIN] == 2700  # 0 = warm by default


async def test_rgb_status(hass: HomeAssistant, setup) -> None:
    _push(setup, LightStatus(3, True, 100, 63, 170))
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state.attributes[ATTR_COLOR_MODE] == ColorMode.RGB
    assert state.attributes[ATTR_RGB_COLOR] == (0, 0, 255)


async def test_off_status(hass: HomeAssistant, setup) -> None:
    _push(setup, LightStatus(3, True, 0, 0x41, 0))
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == STATE_OFF


async def test_offline_node_unavailable(hass: HomeAssistant, setup) -> None:
    _push(setup, LightStatus(3, False, 0, 0, 0))
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == STATE_UNAVAILABLE


async def test_turn_on_color_temp(hass: HomeAssistant, setup, mock_mesh_io) -> None:
    _push(setup, LightStatus(3, True, 100, 0x41, 0))
    await hass.async_block_till_done()
    await hass.services.async_call(
        LIGHT_DOMAIN,
        "turn_on",
        {ATTR_ENTITY_ID: ENTITY, ATTR_COLOR_TEMP_KELVIN: 6500, ATTR_BRIGHTNESS: 255},
        blocking=True,
    )
    mock_mesh_io["send"].assert_awaited_once_with(3, commands.color_temperature(100, 100))
    assert hass.states.get(ENTITY).attributes[ATTR_COLOR_TEMP_KELVIN] == 6500


async def test_turn_on_rgb_keeps_exact_colour(hass: HomeAssistant, setup, mock_mesh_io) -> None:
    _push(setup, LightStatus(3, True, 100, 0x41, 0))
    await hass.async_block_till_done()
    await hass.services.async_call(
        LIGHT_DOMAIN, "turn_on", {ATTR_ENTITY_ID: ENTITY, ATTR_RGB_COLOR: (255, 128, 0)}, blocking=True
    )
    mock_mesh_io["send"].assert_awaited_once_with(3, commands.rgb(255, 128, 0))
    # lamp reports roughly the same hue -> keep the exact colour the user picked
    _push(setup, LightStatus(3, True, 100, 63, 21))
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).attributes[ATTR_RGB_COLOR] == (255, 128, 0)


async def test_turn_on_off(hass: HomeAssistant, setup, mock_mesh_io) -> None:
    _push(setup, LightStatus(3, True, 0, 0x41, 0))
    await hass.async_block_till_done()
    await hass.services.async_call(LIGHT_DOMAIN, "turn_on", {ATTR_ENTITY_ID: ENTITY}, blocking=True)
    mock_mesh_io["send"].assert_awaited_with(3, commands.power(True))
    assert hass.states.get(ENTITY).state == STATE_ON
    await hass.services.async_call(LIGHT_DOMAIN, "turn_off", {ATTR_ENTITY_ID: ENTITY}, blocking=True)
    mock_mesh_io["send"].assert_awaited_with(3, commands.power(False))
    assert hass.states.get(ENTITY).state == STATE_OFF


async def test_brightness_only(hass: HomeAssistant, setup, mock_mesh_io) -> None:
    _push(setup, LightStatus(3, True, 100, 0x41, 0))
    await hass.async_block_till_done()
    await hass.services.async_call(
        LIGHT_DOMAIN, "turn_on", {ATTR_ENTITY_ID: ENTITY, ATTR_BRIGHTNESS: 51}, blocking=True
    )
    mock_mesh_io["send"].assert_awaited_once_with(3, commands.brightness(20))


async def test_unload(hass: HomeAssistant, setup, mock_mesh_io) -> None:
    assert await hass.config_entries.async_unload(setup.entry_id)
    mock_mesh_io["stop"].assert_awaited_once()
