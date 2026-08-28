"""Tests for translation key completeness.

`translations/en.json` is the file Home Assistant actually loads at
runtime for a custom integration; `strings.json` is the source of truth
maintainers edit. These two files had drifted apart for the Protect
binary_sensor entities specifically - see
`test_binary_sensor_camera_and_sensor_translation_keys_present_in_en_json`.
"""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.unifi_insights.binary_sensor import BINARY_SENSOR_TYPES

_INTEGRATION_DIR = Path(__file__).parent.parent / "custom_components" / "unifi_insights"
_EN_JSON = _INTEGRATION_DIR / "translations" / "en.json"
_STRINGS_JSON = _INTEGRATION_DIR / "strings.json"


def test_binary_sensor_camera_and_sensor_translation_keys_present_in_en_json() -> None:
    """Every camera_*/sensor_* binary_sensor translation_key must resolve
    in translations/en.json, matching strings.json.

    Regression test: translations/en.json's entity.binary_sensor section
    had only 6 keys (device_status, door, doorbell, is_dark, is_recording,
    motion) while strings.json correctly defined camera_motion,
    camera_person_detection, etc. HA falls back to the device_class name
    ("Motion") when a translation_key lookup fails, so all four per-camera
    detection sensors rendered as "Motion" and collided into _2/_3/_4
    entity_id suffixes.
    """
    en_data = json.loads(_EN_JSON.read_text())
    en_keys = set(en_data["entity"]["binary_sensor"].keys())

    camera_and_sensor_keys = {
        description.translation_key
        for description in BINARY_SENSOR_TYPES
        if description.translation_key
        and description.translation_key.startswith(("camera_", "sensor_"))
    }

    missing = camera_and_sensor_keys - en_keys
    assert missing == set()


def test_en_json_camera_and_sensor_names_match_strings_json() -> None:
    """The values added to en.json must mirror strings.json exactly, not
    just exist as keys - a mismatched display name would be its own bug.
    """
    en_data = json.loads(_EN_JSON.read_text())
    strings_data = json.loads(_STRINGS_JSON.read_text())
    en_binary_sensor = en_data["entity"]["binary_sensor"]
    strings_binary_sensor = strings_data["entity"]["binary_sensor"]

    for key, value in strings_binary_sensor.items():
        if key.startswith(("camera_", "sensor_")):
            assert key in en_binary_sensor, f"{key} missing from translations/en.json"
            assert en_binary_sensor[key] == value
