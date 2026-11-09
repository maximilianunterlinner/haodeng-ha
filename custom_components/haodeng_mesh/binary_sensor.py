"""Diagnostic binary sensor: is HA connected to the mesh."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
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
    async_add_entities([MeshConnectedSensor(entry.runtime_data, entry.entry_id, "mesh_connected")])


class MeshConnectedSensor(HaoDengHubEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return self._mesh.connected
