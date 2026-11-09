"""Constants for the Hao Deng Mesh integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "haodeng_mesh"

CONF_MESH_NAME: Final = "mesh_name"
CONF_MESH_PASSWORD: Final = "mesh_password"
CONF_MESH_LTK: Final = "mesh_ltk"
CONF_PLACE_ID: Final = "place_id"
CONF_PLACE_NAME: Final = "place_name"
CONF_DEVICES: Final = "devices"
CONF_REGION: Final = "region"

# Per device keys (stored in entry.data[CONF_DEVICES])
DEV_MESH_ID: Final = "mesh_id"
DEV_MAC: Final = "mac"
DEV_NAME: Final = "name"
DEV_MODEL: Final = "model"
DEV_MANUFACTURER: Final = "manufacturer"
DEV_FIRMWARE: Final = "firmware"
DEV_TYPE: Final = "device_type"
DEV_GROUPS: Final = "groups"

# Options
OPT_MIN_KELVIN: Final = "min_kelvin"
OPT_MAX_KELVIN: Final = "max_kelvin"
OPT_INVERT_CCT: Final = "invert_color_temp"

DEFAULT_MIN_KELVIN: Final = 2700
DEFAULT_MAX_KELVIN: Final = 6500
DEFAULT_INVERT_CCT: Final = False

# Connection behaviour
KEEPALIVE_INTERVAL: Final = timedelta(seconds=30)
# A light that has not reported for this long is marked unavailable
DEVICE_TIMEOUT: Final = timedelta(seconds=150)
# Minimum time between two automatic connection attempts
RECONNECT_COOLDOWN: Final = 10.0
# Max. number of lights tried per connection attempt (strongest signal first)
MAX_CONNECT_CANDIDATES: Final = 3
