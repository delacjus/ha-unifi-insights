"""Tests for the vendored UniFi API package."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.unifi_insights.api import ApiKeyAuth, ConnectionType
from custom_components.unifi_insights.api.exceptions import UniFiResponseError
from custom_components.unifi_insights.api.network import (
    UniFiNetworkClient,
    VpnClient,
)
from custom_components.unifi_insights.api.protect import UniFiProtectClient


def _network_client() -> UniFiNetworkClient:
    """Build a local Network client for tests."""
    return UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        base_url="https://192.168.1.1",
        connection_type=ConnectionType.LOCAL,
    )


def _protect_client() -> UniFiProtectClient:
    """Build a local Protect client for tests."""
    return UniFiProtectClient(
        auth=ApiKeyAuth(api_key="test-key"),
        base_url="https://192.168.1.1",
        connection_type=ConnectionType.LOCAL,
    )


def test_build_legacy_api_path_local() -> None:
    """Test building legacy API paths for local connections."""
    client = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        base_url="https://192.168.1.1",
        connection_type=ConnectionType.LOCAL,
    )

    assert (
        client.build_legacy_api_path("default", "/stat/device/aa:bb:cc")
        == "/proxy/network/api/s/default/stat/device/aa:bb:cc"
    )


def test_build_legacy_api_path_remote() -> None:
    """Test building legacy API paths for remote connections."""
    client = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        connection_type=ConnectionType.REMOTE,
        console_id="console-id",
    )

    assert (
        client.build_legacy_api_path("default", "stat/device/aa:bb:cc")
        == "/v1/connector/consoles/console-id/network/api/s/default/"
        "stat/device/aa:bb:cc"
    )


def test_build_api_path_remote_requires_console_id() -> None:
    """Test proxied remote API paths require a console ID."""
    client = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        connection_type=ConnectionType.REMOTE,
    )

    with pytest.raises(ValueError, match="console_id"):
        client.build_api_path("/sites")


def test_build_legacy_global_api_path_remote() -> None:
    """Test building global legacy API paths for remote connections."""
    client = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        connection_type=ConnectionType.REMOTE,
        console_id="console-id",
    )

    assert (
        client.build_legacy_global_api_path("/self/sites")
        == "/v1/connector/consoles/console-id/network/api/self/sites"
    )


async def test_get_hosts_remote_without_console_id() -> None:
    """Test remote host discovery works before a console ID is selected."""
    client = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        connection_type=ConnectionType.REMOTE,
    )
    client._get = AsyncMock(
        return_value={
            "data": [
                {
                    "id": "console-id",
                    "type": "console",
                    "reportedState": {"hostname": "Dream Router 7"},
                }
            ]
        }
    )

    result = await client.get_hosts()

    assert result == [
        {
            "id": "console-id",
            "type": "console",
            "reportedState": {"hostname": "Dream Router 7"},
        }
    ]
    client._get.assert_awaited_once_with("/v1/hosts")


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            {"data": [{"_id": "legacy-1", "port_table": []}]},
            {"_id": "legacy-1", "port_table": []},
        ),
        (
            {"_id": "legacy-2", "port_table": [{"port_idx": 1}]},
            {"_id": "legacy-2", "port_table": [{"port_idx": 1}]},
        ),
    ],
)
async def test_get_legacy_device_stats_handles_wrapped_and_unwrapped_responses(
    response: dict[str, object],
    expected: dict[str, object],
) -> None:
    """Test raw legacy device stats parsing for wrapped and unwrapped payloads."""
    client = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        connection_type=ConnectionType.REMOTE,
        console_id="console-id",
    )
    client._get = AsyncMock(return_value=response)

    result = await client.devices.get_legacy_device_stats(
        "default", "aa:bb:cc:dd:ee:ff"
    )

    assert result == expected
    client._get.assert_awaited_once_with(
        "/v1/connector/consoles/console-id/network/api/s/default/"
        "stat/device/aa:bb:cc:dd:ee:ff"
    )


async def test_get_legacy_all_sites_returns_raw_site_dicts() -> None:
    """Test raw legacy site list parsing."""
    client = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        base_url="https://192.168.1.1",
        connection_type=ConnectionType.LOCAL,
    )
    client._get = AsyncMock(
        return_value={"data": [{"name": "default", "desc": "Default"}]}
    )

    result = await client.sites.get_legacy_all()

    assert result == [{"name": "default", "desc": "Default"}]
    client._get.assert_awaited_once_with("/proxy/network/api/self/sites")


async def test_sites_get_all_handles_missing_id_payload() -> None:
    """Sites get_all should handle Dream 7 payloads missing id (Issue 80)."""
    client = _network_client()
    client._get = AsyncMock(
        return_value={"data": [{"internalReference": "default", "name": "Default"}]}
    )

    result = await client.sites.get_all()

    assert len(result) == 1
    assert result[0].id == "default"
    assert result[0].internal_reference == "default"
    assert result[0].name == "Default"
    client._get.assert_awaited_once_with(client.build_api_path("/sites"), params=None)


async def test_sites_get_all_skips_malformed_items() -> None:
    """Sites get_all should skip malformed items that fail ValidationError."""
    client = _network_client()
    client._get = AsyncMock(
        return_value={
            "data": [
                {"internalReference": "default", "name": "Default"},
                {"deviceCount": "not-an-int-and-invalid"},
            ]
        }
    )

    result = await client.sites.get_all()

    assert len(result) == 1
    assert result[0].id == "default"


async def test_sites_get_returns_site() -> None:
    """Sites get should return a parsed Site model."""
    client = _network_client()
    client._get = AsyncMock(return_value={"data": {"id": "site-1", "name": "Default"}})

    result = await client.sites.get("site-1")

    assert result.id == "site-1"
    assert result.name == "Default"
    client._get.assert_awaited_once_with(client.build_api_path("/sites/site-1"))


async def test_sites_get_missing_raises_value_error() -> None:
    """Sites get should raise ValueError if site is not found."""
    client = _network_client()
    client._get = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="not found"):
        await client.sites.get("missing-site")


async def test_get_legacy_site_devices_returns_device_list() -> None:
    """Test raw legacy site device list parsing."""
    client = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        base_url="https://192.168.1.1",
        connection_type=ConnectionType.LOCAL,
    )
    client._get = AsyncMock(
        return_value={
            "data": [
                {
                    "mac": "aa:bb:cc:dd:ee:ff",
                    "general_temperature": 47.5,
                }
            ]
        }
    )

    result = await client.devices.get_legacy_site_devices("default")

    assert result == [{"mac": "aa:bb:cc:dd:ee:ff", "general_temperature": 47.5}]
    client._get.assert_awaited_once_with("/proxy/network/api/s/default/stat/device")


async def test_get_port_metrics_normalizes_and_derives_total() -> None:
    """Test normalized legacy port metrics with derived total PoE."""
    client = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        connection_type=ConnectionType.REMOTE,
        console_id="console-id",
    )
    client._get = AsyncMock(
        return_value={
            "data": [
                {
                    "port_table": [
                        {
                            "port_idx": 1,
                            "port_poe": True,
                            "poe_power": "1.25",
                            "rx_bytes": 10,
                            "tx_bytes": 20,
                        },
                        {
                            "portIdx": "2",
                            "portPoe": True,
                            "poePower": "2.75",
                            "rxBytes": 30,
                            "txBytes": 40,
                        },
                    ]
                }
            ]
        }
    )

    metrics = await client.devices.get_port_metrics("default", "aa:bb:cc:dd:ee:ff")

    assert metrics.poe_total_w == 4.0
    assert metrics.poe_ports == {1: 1.25, 2: 2.75}
    assert metrics.port_bytes[1].rx_bytes == 10
    assert metrics.port_bytes[1].tx_bytes == 20
    assert metrics.port_bytes[2].rx_bytes == 30
    assert metrics.port_bytes[2].tx_bytes == 40


async def test_get_port_metrics_skips_non_poe_ports() -> None:
    """Test that ports with port_poe=false are excluded from poe_ports."""
    client = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        connection_type=ConnectionType.REMOTE,
        console_id="console-id",
    )
    client._get = AsyncMock(
        return_value={
            "data": [
                {
                    "port_table": [
                        {
                            "port_idx": 1,
                            "port_poe": False,
                            "poe_power": "0.00",
                            "poe_enable": False,
                            "poe_class": "Class 0",
                            "rx_bytes": 100,
                            "tx_bytes": 200,
                        },
                        {
                            "port_idx": 9,
                            "port_poe": False,
                            "poe_power": "0.00",
                            "rx_bytes": 300,
                            "tx_bytes": 400,
                        },
                    ]
                }
            ]
        }
    )

    metrics = await client.devices.get_port_metrics("default", "aa:bb:cc:dd:ee:ff")

    assert metrics.poe_total_w is None
    assert metrics.poe_ports == {}
    # TX/RX bytes should still be collected
    assert metrics.port_bytes[1].rx_bytes == 100
    assert metrics.port_bytes[9].tx_bytes == 400


async def test_get_port_metrics_returns_defaults_for_empty_payload() -> None:
    """Test empty or malformed payloads return default metrics."""
    client = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        base_url="https://192.168.1.1",
        connection_type=ConnectionType.LOCAL,
    )
    client._get = AsyncMock(return_value={"data": []})

    metrics = await client.devices.get_port_metrics("default", "aa:bb:cc:dd:ee:ff")

    assert metrics.poe_total_w is None
    assert metrics.poe_ports == {}
    assert metrics.port_bytes == {}


async def test_wifi_update_uses_put_with_existing_payload() -> None:
    """Test WiFi updates fetch current config and send a full PUT payload."""
    client = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        base_url="https://192.168.1.1",
        connection_type=ConnectionType.LOCAL,
    )
    client._get = AsyncMock(
        return_value={
            "data": {
                "id": "wifi-1",
                "type": "STANDARD",
                "name": "Guest WiFi",
                "metadata": {"origin": "USER_DEFINED"},
                "enabled": False,
                "network": {"id": "network-1", "type": "CORPORATE"},
                "securityConfiguration": {"type": "OPEN"},
                "multicastToUnicastConversionEnabled": False,
                "clientIsolationEnabled": True,
                "hideName": False,
                "uapsdEnabled": True,
                "broadcastingFrequenciesGHz": ["2.4", "5"],
            }
        }
    )
    client._put = AsyncMock(
        return_value={
            "data": {
                "id": "wifi-1",
                "type": "STANDARD",
                "name": "Guest WiFi",
                "enabled": True,
                "network": {"id": "network-1", "type": "CORPORATE"},
                "securityConfiguration": {"type": "OPEN"},
                "multicastToUnicastConversionEnabled": False,
                "clientIsolationEnabled": True,
                "hideName": False,
                "uapsdEnabled": True,
                "broadcastingFrequenciesGHz": ["2.4", "5"],
            }
        }
    )
    client._patch = AsyncMock()

    result = await client.wifi.update("site-1", "wifi-1", enabled=True)

    path = "/proxy/network/integration/v1/sites/site-1/wifi/broadcasts/wifi-1"
    client._get.assert_awaited_once_with(path)
    client._put.assert_awaited_once_with(
        path,
        json_data={
            "type": "STANDARD",
            "name": "Guest WiFi",
            "enabled": True,
            "network": {"id": "network-1", "type": "CORPORATE"},
            "securityConfiguration": {"type": "OPEN"},
            "multicastToUnicastConversionEnabled": False,
            "clientIsolationEnabled": True,
            "hideName": False,
            "uapsdEnabled": True,
            "broadcastingFrequenciesGHz": ["2.4", "5"],
        },
    )
    client._patch.assert_not_awaited()
    assert result.enabled is True


async def test_clients_get_all_paginates_automatically() -> None:
    """Test that get_all fetches all pages when total exceeds page size."""
    client = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        base_url="https://192.168.1.1",
        connection_type=ConnectionType.LOCAL,
    )

    page1 = {
        "offset": 0,
        "limit": 100,
        "count": 2,
        "totalCount": 3,
        "data": [
            {
                "id": "c1",
                "macAddress": "aa:bb:cc:dd:ee:01",
                "type": "WIRED",
                "name": "Client 1",
            },
            {
                "id": "c2",
                "macAddress": "aa:bb:cc:dd:ee:02",
                "type": "WIRED",
                "name": "Client 2",
            },
        ],
    }
    page2 = {
        "offset": 2,
        "limit": 100,
        "count": 1,
        "totalCount": 3,
        "data": [
            {
                "id": "c3",
                "macAddress": "aa:bb:cc:dd:ee:03",
                "type": "WIRELESS",
                "name": "Client 3",
            },
        ],
    }
    client._get = AsyncMock(side_effect=[page1, page2])

    result = await client.clients.get_all("site-1")

    assert len(result) == 3
    assert result[0].name == "Client 1"
    assert result[2].name == "Client 3"
    assert client._get.await_count == 2


async def test_clients_get_all_single_page() -> None:
    """Test that get_all stops after one page when all clients fit."""
    client = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        base_url="https://192.168.1.1",
        connection_type=ConnectionType.LOCAL,
    )
    client._get = AsyncMock(
        return_value={
            "offset": 0,
            "limit": 100,
            "count": 2,
            "totalCount": 2,
            "data": [
                {
                    "id": "c1",
                    "macAddress": "aa:bb:cc:dd:ee:01",
                    "type": "WIRED",
                    "name": "Client 1",
                },
                {
                    "id": "c2",
                    "macAddress": "aa:bb:cc:dd:ee:02",
                    "type": "WIRELESS",
                    "name": "Client 2",
                },
            ],
        }
    )

    result = await client.clients.get_all("site-1")

    assert len(result) == 2
    assert client._get.await_count == 1


async def test_clients_get_all_explicit_limit_no_pagination() -> None:
    """Test that explicit offset/limit skips auto-pagination."""
    client = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        base_url="https://192.168.1.1",
        connection_type=ConnectionType.LOCAL,
    )
    client._get = AsyncMock(
        return_value={
            "offset": 0,
            "limit": 5,
            "count": 5,
            "totalCount": 20,
            "data": [
                {
                    "id": f"c{i}",
                    "macAddress": f"aa:bb:cc:dd:ee:{i:02d}",
                    "type": "WIRED",
                    "name": f"Client {i}",
                }
                for i in range(5)
            ],
        }
    )

    result = await client.clients.get_all("site-1", limit=5)

    assert len(result) == 5
    assert client._get.await_count == 1


# ---------------------------------------------------------------------------
# Network v10.4.57 - LAGs, MC-LAG domains, switch stacks
# ---------------------------------------------------------------------------


async def test_lags_get_all_paginates_automatically() -> None:
    """LAG get_all should fetch all pages when total exceeds one page."""
    client = _network_client()
    page1 = {
        "offset": 0,
        "limit": 100,
        "count": 1,
        "totalCount": 2,
        "data": [
            {
                "id": "lag-1",
                "type": "LOCAL",
                "members": [{"deviceId": "dev-1", "portIdxs": [1, 2]}],
            }
        ],
    }
    page2 = {
        "offset": 1,
        "limit": 100,
        "count": 1,
        "totalCount": 2,
        "data": [
            {
                "id": "lag-2",
                "type": "SWITCH_STACK",
                "members": [{"deviceId": "dev-2", "portIdxs": [5]}],
                "switchStackId": "stack-9",
            }
        ],
    }
    client._get = AsyncMock(side_effect=[page1, page2])

    result = await client.lags.get_all("site-1")

    assert len(result) == 2
    assert result[0].id == "lag-1"
    assert result[0].type == "LOCAL"
    assert result[0].members[0].device_id == "dev-1"
    assert result[0].members[0].port_idxs == [1, 2]
    assert result[1].switch_stack_id == "stack-9"
    assert client._get.await_count == 2
    client._get.assert_any_await(
        client.build_api_path("/sites/site-1/switching/lags"),
        params={"offset": 0, "limit": 100},
    )


async def test_lags_get_all_explicit_limit_single_page() -> None:
    """Explicit offset/limit should fetch a single page."""
    client = _network_client()
    client._get = AsyncMock(
        return_value={
            "offset": 0,
            "limit": 5,
            "count": 1,
            "totalCount": 20,
            "data": [{"id": "lag-1", "type": "LOCAL"}],
        }
    )

    result = await client.lags.get_all("site-1", offset=0, limit=5)

    assert len(result) == 1
    assert client._get.await_count == 1
    client._get.assert_awaited_once_with(
        client.build_api_path("/sites/site-1/switching/lags"),
        params={"offset": 0, "limit": 5},
    )


async def test_lags_get_returns_model_from_wrapped_response() -> None:
    """LAG get should unwrap a ``data`` envelope."""
    client = _network_client()
    client._get = AsyncMock(
        return_value={"data": {"id": "lag-1", "type": "MULTI_CHASSIS"}}
    )

    result = await client.lags.get("site-1", "lag-1")

    assert result.id == "lag-1"
    assert result.type == "MULTI_CHASSIS"
    client._get.assert_awaited_once_with(
        client.build_api_path("/sites/site-1/switching/lags/lag-1")
    )


async def test_lags_get_returns_model_from_unwrapped_response() -> None:
    """LAG get should accept a bare object response."""
    client = _network_client()
    client._get = AsyncMock(return_value={"id": "lag-2", "type": "LOCAL"})

    result = await client.lags.get("site-1", "lag-2")

    assert result.id == "lag-2"


async def test_lags_get_missing_raises_value_error() -> None:
    """LAG get should raise ValueError when nothing is returned."""
    client = _network_client()
    client._get = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="not found"):
        await client.lags.get("site-1", "missing")


async def test_mc_lag_domains_get_all() -> None:
    """MC-LAG domain get_all should parse peers and local LAGs."""
    client = _network_client()
    client._get = AsyncMock(
        return_value={
            "offset": 0,
            "limit": 100,
            "count": 1,
            "totalCount": 1,
            "data": [
                {
                    "id": "mclag-1",
                    "name": "Core",
                    "peers": [
                        {"deviceId": "dev-1", "linkPortIdxs": [23], "role": "TOP"},
                        {"deviceId": "dev-2", "linkPortIdxs": [24], "role": "BOTTOM"},
                    ],
                    "lags": [{"id": "lag-1", "members": []}],
                }
            ],
        }
    )

    result = await client.lags.get_mc_lag_domains("site-1")

    assert len(result) == 1
    assert result[0].name == "Core"
    assert result[0].peers[0].role == "TOP"
    assert result[0].peers[1].device_id == "dev-2"
    client._get.assert_awaited_with(
        client.build_api_path("/sites/site-1/switching/mc-lag-domains"),
        params={"offset": 0, "limit": 100},
    )


async def test_stacks_get_all_and_get() -> None:
    """Switch stack get_all and get should parse members and LAGs."""
    client = _network_client()
    client._get = AsyncMock(
        return_value={
            "offset": 0,
            "limit": 100,
            "count": 1,
            "totalCount": 1,
            "data": [
                {
                    "id": "stack-1",
                    "name": "Rack A",
                    "members": [{"deviceId": "dev-1"}, {"deviceId": "dev-2"}],
                    "lags": [{"id": "lag-1", "members": []}],
                }
            ],
        }
    )

    result = await client.stacks.get_all("site-1")

    assert len(result) == 1
    assert result[0].name == "Rack A"
    assert result[0].members[1].device_id == "dev-2"
    client._get.assert_awaited_with(
        client.build_api_path("/sites/site-1/switching/switch-stacks"),
        params={"offset": 0, "limit": 100},
    )

    client._get = AsyncMock(return_value={"data": {"id": "stack-1", "name": "Rack A"}})
    single = await client.stacks.get("site-1", "stack-1")
    assert single.id == "stack-1"
    client._get.assert_awaited_once_with(
        client.build_api_path("/sites/site-1/switching/switch-stacks/stack-1")
    )


# ---------------------------------------------------------------------------
# Protect v7.1.87 - alarm hubs, arm profiles, relays, sirens, speakers, bridges
# ---------------------------------------------------------------------------


async def test_alarm_hubs_get_all_wrapped_and_unwrapped() -> None:
    """Alarm hub get_all should handle wrapped and bare list responses."""
    client = _protect_client()
    client._get = AsyncMock(
        return_value={
            "data": [{"id": "hub-1", "modelKey": "linkStation", "isAlarmHub": True}]
        }
    )

    wrapped = await client.alarm_hubs.get_all()
    assert len(wrapped) == 1
    assert wrapped[0].id == "hub-1"
    assert wrapped[0].is_alarm_hub is True
    client._get.assert_awaited_once_with(client.build_api_path("/alarm-hubs"))

    client._get = AsyncMock(return_value=[{"id": "hub-2", "modelKey": "linkStation"}])
    unwrapped = await client.alarm_hubs.get_all()
    assert len(unwrapped) == 1
    assert unwrapped[0].id == "hub-2"


async def test_alarm_hubs_trigger_output_posts_expected_payload() -> None:
    """Alarm hub trigger_output should POST to the outputs trigger path."""
    client = _protect_client()
    client._post = AsyncMock(return_value=None)

    result = await client.alarm_hubs.trigger_output("hub-1", "out-1", durationMs=5000)

    assert result is True
    client._post.assert_awaited_once_with(
        client.build_api_path("/alarm-hubs/hub-1/outputs/out-1/trigger"),
        json_data={"durationMs": 5000},
    )


async def test_arm_profiles_get_all_and_enable() -> None:
    """Arm profile get_all should parse and enable should POST."""
    client = _protect_client()
    client._get = AsyncMock(
        return_value=[{"id": "profile-1", "name": "Away", "recordEverything": True}]
    )

    profiles = await client.arm_profiles.get_all()
    assert profiles[0].name == "Away"
    assert profiles[0].record_everything is True
    client._get.assert_awaited_once_with(client.build_api_path("/arm-profiles"))

    client._post = AsyncMock(return_value=None)
    assert await client.arm_profiles.enable(armProfileId="profile-1") is True
    client._post.assert_awaited_once_with(
        client.build_api_path("/arm-profiles/enable"),
        json_data={"armProfileId": "profile-1"},
    )


async def test_relays_activate_output_posts_expected_path() -> None:
    """Relay activate_output should POST to the outputs activate path."""
    client = _protect_client()
    client._post = AsyncMock(return_value=None)

    result = await client.relays.activate_output("relay-1", "out-2")

    assert result is True
    client._post.assert_awaited_once_with(
        client.build_api_path("/relays/relay-1/outputs/out-2/activate"),
        json_data=None,
    )


async def test_sirens_play_and_speakers_test_sound() -> None:
    """Siren play and speaker test_sound should POST to their action paths."""
    client = _protect_client()
    client._post = AsyncMock(return_value=None)

    assert await client.sirens.play("siren-1") is True
    client._post.assert_awaited_with(client.build_api_path("/sirens/siren-1/play"))

    assert await client.speakers.test_sound("spk-1") is True
    client._post.assert_awaited_with(
        client.build_api_path("/speakers/spk-1/test-sound")
    )


async def test_bridges_get_all_uses_base_endpoint() -> None:
    """Bridge get_all should parse via the shared device endpoint base."""
    client = _protect_client()
    client._get = AsyncMock(
        return_value=[{"id": "bridge-1", "modelKey": "bridge", "maxClients": 4}]
    )

    result = await client.bridges.get_all()

    assert result[0].id == "bridge-1"
    assert result[0].max_clients == 4
    client._get.assert_awaited_once_with(client.build_api_path("/bridges"))


async def test_link_stations_get_returns_model() -> None:
    """Link station get should return a parsed model from wrapped data."""
    client = _protect_client()
    client._get = AsyncMock(
        return_value={"data": {"id": "ls-1", "modelKey": "linkStation"}}
    )

    result = await client.link_stations.get("ls-1")

    assert result.id == "ls-1"
    client._get.assert_awaited_once_with(client.build_api_path("/link-stations/ls-1"))


async def test_devices_get_all_skips_malformed_items() -> None:
    """Devices get_all should skip invalid/malformed items without failing."""
    client = _network_client()
    client._get = AsyncMock(
        return_value={
            "data": [
                {"id": "dev-1", "name": "Valid AP", "features": ["accessPoint"]},
                "not-a-dict",
                {"name": "Missing ID"},
            ]
        }
    )

    result = await client.devices.get_all("site-1")

    assert len(result) == 1
    assert result[0].id == "dev-1"
    assert result[0].features == ["accessPoint"]


async def test_devices_get_pending_adoption_skips_malformed_items() -> None:
    """Devices get_pending_adoption should skip invalid items."""
    client = _network_client()
    client._get = AsyncMock(
        return_value={
            "data": [
                {"id": "pend-1", "name": "Pending Device"},
                123,
                {"name": "No ID"},
            ]
        }
    )

    result = await client.devices.get_pending_adoption()

    assert len(result) == 1
    assert result[0].id == "pend-1"


def _make_response(*, status: int = 200, text: str = "", json_side_effect=None):
    """Build a fake aiohttp.ClientResponse for _handle_response tests."""
    response = MagicMock()
    response.status = status
    response.text = AsyncMock(return_value=text)
    response.headers = {}
    if json_side_effect is not None:
        response.json = AsyncMock(side_effect=json_side_effect)
    else:
        response.json = AsyncMock(return_value={})
    return response


async def test_handle_response_2xx_non_json_raises() -> None:
    """A 2xx status with a non-JSON body must raise, not be treated as success.

    Regression test: a UniFi console/proxy that considers the request
    unauthenticated can return a 2xx status with an HTML login page body.
    Silently returning None here (the old behavior) meant no exception ever
    reached the coordinator, so entities kept serving stale data for 47h in
    production instead of surfacing as unavailable.
    """
    client = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        base_url="https://192.168.1.1",
        connection_type=ConnectionType.LOCAL,
    )
    response = _make_response(
        status=200,
        text="<!doctype html><html><body>login</body></html>",
        json_side_effect=aiohttp.ContentTypeError(MagicMock(), MagicMock()),
    )

    with pytest.raises(UniFiResponseError) as exc_info:
        await client._handle_response(response)

    assert exc_info.value.status_code == 200


async def test_handle_response_empty_body_returns_none() -> None:
    """An empty 2xx body (e.g. a 204-style response) is still a valid no-op."""
    client = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        base_url="https://192.168.1.1",
        connection_type=ConnectionType.LOCAL,
    )
    response = _make_response(status=200, text="")

    result = await client._handle_response(response)

    assert result is None


async def test_handle_response_valid_json_returns_data() -> None:
    """A normal JSON response still parses and returns as before."""
    client = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        base_url="https://192.168.1.1",
        connection_type=ConnectionType.LOCAL,
    )
    response = _make_response(status=200, text='{"ok": true}')
    response.json = AsyncMock(return_value={"ok": True})

    result = await client._handle_response(response)

    assert result == {"ok": True}


def test_vpn_client_model() -> None:
    """Test VpnClient model validation and fields."""
    client: VpnClient = VpnClient.model_validate(
        {
            "_id": "vpn1",
            "name": "Example VPN",
            "purpose": "vpn-client",
            "vpn_type": "openvpn-client",
            "enabled": True,
            "ip_subnet": "172.21.25.217/32",
            "openvpn_id": 1,
            "remote_host": "vpn.example.com",
        }
    )
    assert client.id == "vpn1"
    assert client.name == "Example VPN"
    assert client.purpose == "vpn-client"
    assert client.vpn_type == "openvpn-client"
    assert client.enabled is True
    assert client.ip_subnet == "172.21.25.217/32"
    assert client.openvpn_id == 1
    assert client.remote_host == "vpn.example.com"


async def test_vpn_clients_endpoint_list_vpn_clients() -> None:
    """Test listing VPN client configurations."""
    client: UniFiNetworkClient = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        base_url="https://192.168.1.1",
        connection_type=ConnectionType.LOCAL,
    )
    client._get = AsyncMock(
        return_value={
            "meta": {"rc": "ok"},
            "data": [
                {
                    "_id": "vpn1",
                    "name": "Example VPN",
                    "purpose": "vpn-client",
                    "vpn_type": "openvpn-client",
                    "enabled": True,
                },
                {
                    "_id": "lan1",
                    "name": "LAN",
                    "purpose": "corporate",
                    "enabled": True,
                },
            ],
        }
    )

    clients: list[VpnClient] = await client.vpn_clients.list_vpn_clients("default")
    assert len(clients) == 1
    assert clients[0].id == "vpn1"
    assert clients[0].name == "Example VPN"
    assert clients[0].enabled is True
    client._get.assert_awaited_once_with(
        "/proxy/network/api/s/default/rest/networkconf"
    )


async def test_vpn_clients_endpoint_list_vpn_clients_unwrapped_and_empty() -> None:
    """Test listing VPN client configurations with bare list and None responses."""
    client: UniFiNetworkClient = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        base_url="https://192.168.1.1",
        connection_type=ConnectionType.LOCAL,
    )

    # Bare list
    client._get = AsyncMock(
        return_value=[
            {
                "_id": "vpn1",
                "name": "Example VPN",
                "purpose": "vpn-client",
                "vpn_type": "openvpn-client",
                "enabled": True,
            }
        ]
    )
    clients: list[VpnClient] = await client.vpn_clients.list_vpn_clients("default")
    assert len(clients) == 1
    assert clients[0].id == "vpn1"

    # None / empty response
    client._get = AsyncMock(return_value=None)
    clients = await client.vpn_clients.list_vpn_clients("default")
    assert clients == []


async def test_vpn_clients_endpoint_get_vpn_client() -> None:
    """Test getting a specific VPN client configuration."""
    client: UniFiNetworkClient = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        base_url="https://192.168.1.1",
        connection_type=ConnectionType.LOCAL,
    )
    client._get = AsyncMock(
        return_value={
            "meta": {"rc": "ok"},
            "data": [
                {
                    "_id": "vpn1",
                    "name": "Example VPN",
                    "purpose": "vpn-client",
                    "enabled": True,
                }
            ],
        }
    )

    vpn_client: VpnClient = await client.vpn_clients.get_vpn_client("default", "vpn1")
    assert vpn_client.id == "vpn1"
    assert vpn_client.name == "Example VPN"


async def test_vpn_clients_endpoint_get_vpn_client_not_found_raises() -> None:
    """Test getting a missing VPN client raises ValueError."""
    client: UniFiNetworkClient = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        base_url="https://192.168.1.1",
        connection_type=ConnectionType.LOCAL,
    )
    client._get = AsyncMock(return_value={"meta": {"rc": "ok"}, "data": []})
    with pytest.raises(ValueError, match="VPN Client missing not found"):
        await client.vpn_clients.get_vpn_client("default", "missing")


async def test_vpn_clients_endpoint_update_vpn_client() -> None:
    """Test updating a VPN client configuration via PUT."""
    client: UniFiNetworkClient = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        base_url="https://192.168.1.1",
        connection_type=ConnectionType.LOCAL,
    )
    client._get = AsyncMock(
        return_value={
            "meta": {"rc": "ok"},
            "data": [
                {
                    "_id": "vpn1",
                    "name": "Example VPN",
                    "purpose": "vpn-client",
                    "enabled": True,
                }
            ],
        }
    )
    client._put = AsyncMock(
        return_value={
            "meta": {"rc": "ok"},
            "data": [
                {
                    "_id": "vpn1",
                    "name": "Example VPN",
                    "purpose": "vpn-client",
                    "enabled": False,
                }
            ],
        }
    )

    updated: VpnClient = await client.vpn_clients.update_vpn_client(
        "default", "vpn1", enabled=False
    )
    assert updated.id == "vpn1"
    assert updated.enabled is False
    client._put.assert_awaited_once_with(
        "/proxy/network/api/s/default/rest/networkconf/vpn1",
        json_data={
            "_id": "vpn1",
            "name": "Example VPN",
            "purpose": "vpn-client",
            "enabled": False,
        },
    )


async def test_vpn_clients_endpoint_update_not_found_raises() -> None:
    """Test updating a missing VPN client raises ValueError."""
    client: UniFiNetworkClient = UniFiNetworkClient(
        auth=ApiKeyAuth(api_key="test-key"),
        base_url="https://192.168.1.1",
        connection_type=ConnectionType.LOCAL,
    )
    client._get = AsyncMock(return_value={"meta": {"rc": "ok"}, "data": []})

    with pytest.raises(ValueError, match="VPN Client missing not found"):
        await client.vpn_clients.update_vpn_client("default", "missing", enabled=False)
