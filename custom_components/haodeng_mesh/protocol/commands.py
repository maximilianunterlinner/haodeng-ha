"""Zengge / Hao Deng mesh command set.

Opcodes and parameter layouts as reverse engineered by the original
home-assistant-zengge project. Values for brightness and color temperature
are on a 0-100 scale on the device.
"""

from __future__ import annotations

from dataclasses import dataclass

# GATT characteristics (Telink mesh service)
STATUS_CHAR_UUID = "00010203-0405-0607-0809-0a0b0c0d1911"
COMMAND_CHAR_UUID = "00010203-0405-0607-0809-0a0b0c0d1912"
OTA_CHAR_UUID = "00010203-0405-0607-0809-0a0b0c0d1913"
PAIR_CHAR_UUID = "00010203-0405-0607-0809-0a0b0c0d1914"

# Pairing replies
PAIR_OK = 0x0D
PAIR_AUTH_FAILED = 0x0E

# Opcodes
OPCODE_STATE = 0xD0
OPCODE_COLOR = 0xE2
OPCODE_STATUS_REPLY = 0xDB
OPCODE_NOTIFICATION = 0xDC

# Sub commands for OPCODE_STATE
_STATE_POWER = 0x01
_STATE_BRIGHTNESS = 0x02
_DIMMING_TARGET_AUTO = 0x06

# Sub commands for OPCODE_COLOR
_COLOR_RGB = 0x60
_COLOR_CCT = 0x62

# Address used by the Wi-Fi bridge inside the mesh
BRIDGE_MESH_ADDRESS = 0xFF
# Destination used when enabling notifications (taken from the working upstream code)
NOTIFY_ENABLE_DEST = 0x0211


@dataclass(frozen=True, slots=True)
class Command:
    """A command ready to be encrypted and sent."""

    opcode: int
    params: bytes


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def power(on: bool) -> Command:
    return Command(OPCODE_STATE, bytes([0xFF, _STATE_POWER, 1 if on else 0]))


def brightness(percent: int) -> Command:
    """Set brightness, 1-100."""
    return Command(
        OPCODE_STATE,
        bytes([0xFF, _STATE_BRIGHTNESS, _clamp(percent, 1, 100), _DIMMING_TARGET_AUTO]),
    )


def rgb(red: int, green: int, blue: int) -> Command:
    return Command(
        OPCODE_COLOR,
        bytes([0xFF, _COLOR_RGB, _clamp(red, 0, 255), _clamp(green, 0, 255), _clamp(blue, 0, 255)]),
    )


def color_temperature(cct_percent: int, brightness_percent: int) -> Command:
    """Set white mode. cct_percent 0-100 (device scale), brightness 1-100."""
    return Command(
        OPCODE_COLOR,
        bytes([0xFF, _COLOR_CCT, _clamp(cct_percent, 0, 100), _clamp(brightness_percent, 1, 100)]),
    )
