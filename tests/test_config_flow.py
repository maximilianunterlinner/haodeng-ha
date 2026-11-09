"""Config flow tests (cloud mocked)."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.haodeng_mesh.cloud import CloudAuthError, CloudDevice, CloudError, CloudPlace
from custom_components.haodeng_mesh.const import (
    CONF_DEVICES,
    CONF_MESH_NAME,
    CONF_REGION,
    DOMAIN,
    OPT_INVERT_CCT,
    OPT_MAX_KELVIN,
    OPT_MIN_KELVIN,
)

LOGIN = {CONF_USERNAME: "me@example.com", CONF_PASSWORD: "pw", CONF_REGION: "eu"}
PLACE_1 = CloudPlace("place-1", "Zuhause", "meshname", "meshpass", "ltk")
PLACE_2 = CloudPlace("place-2", "Garten", "mesh2", "pass2", "ltk2")
DEVICES = [CloudDevice(3, "a4c138000003", "Spot", "RGBCW_Spot", "Zengge", "1.0", 65)]


@pytest.fixture
def cloud() -> Generator[AsyncMock]:
    with patch("custom_components.haodeng_mesh.config_flow.HaoDengCloud", autospec=True) as cls:
        inst = cls.return_value
        inst.places.return_value = [PLACE_1]
        inst.devices.return_value = DEVICES
        yield inst


@pytest.fixture(autouse=True)
def no_setup() -> Generator[None]:
    with patch("custom_components.haodeng_mesh.async_setup_entry", return_value=True):
        yield


async def test_single_place(hass: HomeAssistant, cloud: AsyncMock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOGIN)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Zuhause"
    data = result["data"]
    assert data[CONF_MESH_NAME] == "meshname"
    assert data[CONF_DEVICES][0]["mac"] == "A4:C1:38:00:00:03"
    assert CONF_PASSWORD not in data and CONF_USERNAME not in data  # cloud login not stored
    assert result["result"].unique_id == "place-1"


async def test_multiple_places(hass: HomeAssistant, cloud: AsyncMock) -> None:
    cloud.places.return_value = [PLACE_1, PLACE_2]
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOGIN)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "place"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"place": "place-2"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Garten"
    cloud.devices.assert_awaited_with("place-2")


@pytest.mark.parametrize(
    ("exc", "error"), [(CloudAuthError("bad"), "invalid_auth"), (CloudError("down"), "cannot_connect")]
)
async def test_login_errors(hass: HomeAssistant, cloud: AsyncMock, exc: Exception, error: str) -> None:
    cloud.login.side_effect = exc
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOGIN)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    # recovers
    cloud.login.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOGIN)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_already_configured(hass: HomeAssistant, cloud: AsyncMock, mock_entry) -> None:
    mock_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOGIN)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_updates_devices(hass: HomeAssistant, cloud: AsyncMock, mock_entry) -> None:
    mock_entry.add_to_hass(hass)
    cloud.devices.return_value = [*DEVICES, CloudDevice(9, "a4c138000009", "Neu", None, None, None, 65)]
    result = await mock_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOGIN)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert [d["mesh_id"] for d in mock_entry.data[CONF_DEVICES]] == [3, 9]


async def test_options_flow(hass: HomeAssistant, mock_entry) -> None:
    mock_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {OPT_MIN_KELVIN: 6000, OPT_MAX_KELVIN: 3000, OPT_INVERT_CCT: True}
    )
    assert result["errors"] == {"base": "kelvin_range"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {OPT_MIN_KELVIN: 3000, OPT_MAX_KELVIN: 6000, OPT_INVERT_CCT: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_entry.options == {OPT_MIN_KELVIN: 3000, OPT_MAX_KELVIN: 6000, OPT_INVERT_CCT: True}
