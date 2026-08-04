"""Tests for vendored UniFi API client model parsing."""

from custom_components.unifi_insights.api.network.models.client import Client
from custom_components.unifi_insights.api.network.models.device import (
    Device,
    DeviceState,
)
from custom_components.unifi_insights.api.network.models.lag import LAG, LagType
from custom_components.unifi_insights.api.protect.models.arm_profile import ArmProfile
from custom_components.unifi_insights.api.protect.models.doorlock import DoorLock
from custom_components.unifi_insights.api.protect.models.link_station import (
    AlarmHub,
    LinkStation,
)
from custom_components.unifi_insights.api.protect.models.viewport import Viewport


def test_client_model_accepts_vpn_type() -> None:
    """Client model should parse VPN client types returned by UniFi."""
    client = Client.model_validate({"id": "client-vpn", "type": "VPN"})

    assert client.type == "VPN"


def test_client_model_accepts_teleport_type() -> None:
    """Client model should parse TELEPORT client types returned by UniFi."""
    client = Client.model_validate({"id": "client-teleport", "type": "TELEPORT"})

    assert client.type == "TELEPORT"


def test_client_model_accepts_lowercase_teleport_type() -> None:
    """Client model should parse lowercase TELEPORT values case-insensitively."""
    client = Client.model_validate({"id": "client-teleport-lower", "type": "teleport"})

    assert client.type == "TELEPORT"


def test_device_state_accepts_network_10_4_states() -> None:
    """Device model should parse new Network 10.4.57 device states."""
    device = Device.model_validate(
        {"id": "dev-1", "name": "Switch", "state": "CONNECTION_INTERRUPTED"}
    )

    assert device.state == DeviceState.CONNECTION_INTERRUPTED


def test_device_parses_interfaces_features_and_uplink() -> None:
    """Device model should parse the new interfaces/features/uplink structures."""
    device = Device.model_validate(
        {
            "id": "dev-1",
            "name": "Switch",
            "features": {"switching": {"lags": [{"id": "lag-1"}]}},
            "interfaces": {
                "ports": [{"idx": 1, "connector": "RJ45", "speedMbps": 1000}]
            },
            "uplink": {"deviceId": "gw-1"},
        }
    )

    assert device.features is not None
    assert device.features.switching is not None
    assert device.features.switching.lags == [{"id": "lag-1"}]
    assert device.interfaces is not None
    assert device.interfaces.ports[0].speed_mbps == 1000
    assert device.uplink is not None
    assert device.uplink.device_id == "gw-1"


def test_lag_model_parses_members_and_type() -> None:
    """LAG model should parse membership entries and known types."""
    lag = LAG.model_validate(
        {
            "id": "lag-1",
            "type": "LOCAL",
            "members": [{"deviceId": "dev-1", "portIdxs": [1, 2, 3]}],
        }
    )

    assert lag.type == LagType.LOCAL
    assert lag.members[0].device_id == "dev-1"
    assert lag.members[0].port_idxs == [1, 2, 3]


def test_lag_model_tolerates_unknown_type() -> None:
    """LAG model should keep unknown enum values as strings."""
    lag = LAG.model_validate({"id": "lag-1", "type": "FUTURE_TYPE"})

    assert lag.type == "FUTURE_TYPE"


def test_alarm_hub_is_link_station_alias() -> None:
    """Alarm hub should share the LinkStation model and parse aliases."""
    assert AlarmHub is LinkStation

    hub = AlarmHub.model_validate(
        {"id": "hub-1", "modelKey": "linkStation", "isAlarmHub": True}
    )

    assert hub.model_key == "linkStation"
    assert hub.is_alarm_hub is True


def test_arm_profile_parses_aliases() -> None:
    """Arm profile should parse camelCase aliases into snake_case fields."""
    profile = ArmProfile.model_validate(
        {"id": "p-1", "name": "Away", "recordEverything": True, "activationDelay": 30}
    )

    assert profile.record_everything is True
    assert profile.activation_delay == 30


def test_doorlock_and_viewport_parse_ws_payloads() -> None:
    """DoorLock and Viewport models should parse WebSocket update payloads."""
    lock = DoorLock.model_validate(
        {"id": "lock-1", "modelKey": "doorlock", "lockState": "LOCKED"}
    )
    viewport = Viewport.model_validate(
        {"id": "vp-1", "modelKey": "viewport", "liveview": "lv-1"}
    )

    assert lock.lock_state == "LOCKED"
    assert viewport.liveview == "lv-1"
