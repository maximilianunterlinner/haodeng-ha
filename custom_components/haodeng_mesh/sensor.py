"""Diagnostic sensor: which light HA is connected through."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HaoDengConfigEntry
from .entity import HaoDengHubEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaoDengConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ConnectedViaSensor(entry.runtime_data, entry.entry_id, "connected_via")])


class ConnectedViaSensor(HaoDengHubEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str | None:
        device = self._mesh.connected_device
        return device.name if device else None

    @property
    def extra_state_attributes(self) -> dict[str, str | bool | None]:
        return {
            "last_error": self._mesh.last_error,
            "wifi_bridge_online": self._mesh.bridge_online,
        }
