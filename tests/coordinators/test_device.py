# Copyright 2026 UniFi Insights contributors
"""
Tests for the device owner's command foundations (ADR-010).

Covers PoE port eligibility, which lives next to the power-cycle command and
reads #337's port facts, and the device coordinator's reuse of the config
coordinator's legacy site-name rule.
"""

from __future__ import annotations

import copy
from contextlib import suppress
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from unifi_official_api import UniFiConnectionError, UniFiValidationError
from unifi_official_api.network.endpoints.devices import DevicesEndpoint

from custom_components.unifi_insights.const import DOMAIN
from custom_components.unifi_insights.coordinators.device import (
    _build_outlet_overrides,
    get_device_port,
    port_can_be_power_cycled,
    power_cyclable_ports,
    require_power_cyclable_port,
)
from custom_components.unifi_insights.data_transforms import (
    NETWORK_FACTS_KEY,
    build_site_network_facts,
)
from tests.fixtures.command_owners import PDU_ID, SITE_ID
from tests.fixtures.library_responses import SAMPLE_PDU_LEGACY_DEVICE

if TYPE_CHECKING:
    from tests.fixtures.command_owners import SeededOwners

SWITCH_ID = "sw1"
PORTS: list[dict[str, Any]] = [
    {"idx": 1, "poe": {"enabled": True}},
    {"idx": "2", "poe": {"enabled": True}},
    {"idx": 3, "poe": {"enabled": False}},
    {"idx": 4},
    {"idx": 5, "poe": {"enabled": "true"}},
]


def _data(ports: list[dict[str, Any]] | None = PORTS) -> dict[str, Any]:
    """Return coordinator data for one switch with its published facts."""
    switch: dict[str, Any] = {
        "id": SWITCH_ID,
        "name": "Switch",
        "macAddress": "aa:bb:cc:00:00:01",
        "features": ["switching"],
    }
    if ports is not None:
        switch["ports"] = ports
    data: dict[str, Any] = {"devices": {SITE_ID: {SWITCH_ID: switch}}, "stats": {}}
    data[NETWORK_FACTS_KEY] = {
        SITE_ID: build_site_network_facts(data["devices"][SITE_ID], None)
    }
    return data


class TestPoeEligibility:
    """PoE lookup and eligibility over the published port facts."""

    def test_only_integer_indexed_poe_ports_qualify(self) -> None:
        """Discovery keeps integer raw indexes with PoE enabled, in order."""
        ports = power_cyclable_ports(_data(), SITE_ID, SWITCH_ID)

        assert [port.raw_index for port in ports] == [1]
        assert ports[0].record == PORTS[0]

    @pytest.mark.parametrize(
        ("data", "device_id"),
        [({}, SWITCH_ID), (_data(), "missing"), (_data(None), SWITCH_ID)],
    )
    def test_no_facts_or_ports_means_no_targets(
        self, data: dict[str, Any], device_id: str
    ) -> None:
        """A device without facts or ports has nothing to power cycle."""
        assert power_cyclable_ports(data, SITE_ID, device_id) == ()

    def test_lookup_matches_the_raw_index_exactly(self) -> None:
        """``2`` never finds the port spelled ``"2"``."""
        data = _data()

        assert get_device_port(data, SITE_ID, SWITCH_ID, 1) == PORTS[0]
        assert get_device_port(data, SITE_ID, SWITCH_ID, 2) is None
        assert get_device_port(data, SITE_ID, SWITCH_ID, 9) is None
        assert get_device_port(data, None, SWITCH_ID, 1) is None
        assert get_device_port(None, SITE_ID, SWITCH_ID, 1) is None

    @pytest.mark.parametrize(
        ("port", "eligible"),
        [
            ({"poe": {"enabled": True}}, True),
            ({"poe": {"enabled": False}}, False),
            ({"poe": {"enabled": "true"}}, False),
            ({"poe": None}, False),
            ({}, False),
        ],
    )
    def test_power_cycle_needs_poe_enabled_true(
        self, port: dict[str, Any], *, eligible: bool
    ) -> None:
        """Only a literal ``True`` enables a power cycle."""
        assert port_can_be_power_cycled(port) is eligible

    def test_require_returns_the_eligible_port(self) -> None:
        """An eligible port is returned to the caller."""
        assert require_power_cyclable_port(_data(), SITE_ID, SWITCH_ID, 1) == PORTS[0]

    @pytest.mark.parametrize(
        ("target", "key", "placeholders"),
        [
            (
                (_data(), SITE_ID, "missing", 1),
                "device_not_found",
                {"device_id": "missing", "site_id": SITE_ID},
            ),
            (
                (None, None, None, 1),
                "device_not_found",
                {"device_id": "None", "site_id": "None"},
            ),
            (
                (_data(), SITE_ID, SWITCH_ID, 9),
                "port_not_found",
                {"port_idx": "9", "device_id": SWITCH_ID},
            ),
            (
                (_data(), SITE_ID, SWITCH_ID, 3),
                "port_not_poe",
                {"port_idx": "3", "device_id": SWITCH_ID},
            ),
        ],
    )
    def test_require_raises_translated_validation(
        self,
        target: tuple[dict[str, Any] | None, str | None, str | None, int],
        key: str,
        placeholders: dict[str, str],
    ) -> None:
        """Each ineligible target raises its ServiceValidationError."""
        with pytest.raises(ServiceValidationError) as caught:
            require_power_cyclable_port(*target)

        assert caught.value.translation_domain == DOMAIN
        assert caught.value.translation_key == key
        assert caught.value.translation_placeholders == placeholders


async def test_device_mapping_follows_the_config_rule(
    seeded_owners: SeededOwners,
) -> None:
    """The device coordinator reads the config mapping instead of its own."""
    device = seeded_owners.device
    config = seeded_owners.config
    network_client = seeded_owners.network_client

    assert config.data["legacy_site_names"] == {SITE_ID: "default"}
    assert config.legacy_site_names == {SITE_ID: "default"}
    network_client.sites.get_legacy_all.reset_mock()
    network_client.devices.get_legacy_site_devices.reset_mock()
    config.data = {**config.data, "legacy_site_names": {SITE_ID: "renamed"}}

    await device.async_refresh()

    assert device.last_update_success
    network_client.sites.get_legacy_all.assert_not_called()
    network_client.devices.get_legacy_site_devices.assert_awaited_once_with("renamed")


MAC = "AA:BB:CC:DD:EE:FF"
LEGACY_PDU_ID = "60a1b2c3d4e5f67890123456"


def _with_client(owners: SeededOwners, record: dict[str, Any]) -> None:
    """Publish one client record in the device owner's data."""
    owners.device.data = {**owners.device.data, "clients": {SITE_ID: {"c1": record}}}


class TestDeviceCommands:
    """Restart and PoE: one call, a translated error, no refresh."""

    async def test_restart_calls_the_device_action(
        self, seeded_owners: SeededOwners
    ) -> None:
        """A restart is sent with the integration IDs and returns its result."""
        restart = seeded_owners.network_client.devices.restart
        restart.return_value = True
        refreshes = seeded_owners.network_client.devices.get_all.await_count

        assert await seeded_owners.device.async_restart_device(SITE_ID, PDU_ID) is True

        restart.assert_awaited_once_with(SITE_ID, PDU_ID)
        assert seeded_owners.network_client.devices.get_all.await_count == refreshes

    async def test_falsy_restart_raises_restart_rejected(
        self, seeded_owners: SeededOwners
    ) -> None:
        """A restart the console does not accept raises a translated error."""
        seeded_owners.network_client.devices.restart.return_value = False

        with pytest.raises(HomeAssistantError) as caught:
            await seeded_owners.device.async_restart_device(SITE_ID, PDU_ID)

        assert caught.value.translation_domain == DOMAIN
        assert caught.value.translation_key == "restart_rejected"
        assert caught.value.translation_placeholders == {"device_id": PDU_ID}

    async def test_restart_failure_is_translated(
        self, seeded_owners: SeededOwners
    ) -> None:
        """A failed restart keeps its message and the API error as cause."""
        cause = UniFiConnectionError("down")
        seeded_owners.network_client.devices.restart.side_effect = cause

        with pytest.raises(HomeAssistantError, match=r"^Unable to restart") as caught:
            await seeded_owners.device.async_restart_device(SITE_ID, PDU_ID)

        assert caught.value.translation_key == "command_failed"
        assert caught.value.__cause__ is cause

    async def test_power_cycle_checks_the_port_first(
        self, seeded_owners: SeededOwners
    ) -> None:
        """An eligible port is power cycled; an ineligible one is never sent."""
        device = seeded_owners.device
        device.data = {**device.data, **_data()}
        action = seeded_owners.network_client.devices.execute_port_action
        action.return_value = True

        assert await device.async_power_cycle_port(SITE_ID, SWITCH_ID, 1) is True
        action.assert_awaited_once_with(SITE_ID, SWITCH_ID, 1, "POWER_CYCLE")

        action.reset_mock()
        with pytest.raises(ServiceValidationError) as caught:
            await device.async_power_cycle_port(SITE_ID, SWITCH_ID, 3)
        assert caught.value.translation_key == "port_not_poe"
        action.assert_not_awaited()


class TestOutletCommand:
    """Outlet writes: classic call, list-aware overlay, deferred refresh."""

    async def test_outlet_write_publishes_a_copy_on_write_overlay(
        self, seeded_owners: SeededOwners
    ) -> None:
        """Only the written outlet and its ancestors are replaced."""
        device = seeded_owners.device
        client = seeded_owners.network_client
        client.devices.set_outlet_state.return_value = True
        before_device = device.data["devices"][SITE_ID][PDU_ID]
        before_table = before_device["outlet_table"]
        seen: list[dict[str, Any]] = []
        device.async_add_listener(
            lambda: seen.append(device.data["devices"][SITE_ID][PDU_ID])
        )
        refreshes = client.devices.get_all.await_count

        result = await device.async_set_outlet_state(SITE_ID, PDU_ID, 2, state=True)

        assert result is True
        client.devices.set_outlet_state.assert_awaited_once_with(
            "default",
            LEGACY_PDU_ID,
            2,
            state=True,
            cycle_enabled=None,
            current_device=before_device,
        )
        overlay = seen[0]
        assert overlay is not before_device
        assert overlay["outlet_table"] is not before_table
        assert overlay["outlet_table"][1]["relay_state"] is True
        assert overlay["outlet_table"][1]["cycle_enabled"] is False
        # Unwritten outlets stay shared and the old snapshot is untouched.
        assert overlay["outlet_table"][0] is before_table[0]
        assert before_table[1]["relay_state"] is False
        # Replaced outlet_overrides is a new list with the sent overrides.
        assert overlay["outlet_overrides"] is not before_device["outlet_overrides"]
        assert overlay["outlet_overrides"] == [
            *before_device["outlet_overrides"],
            {"index": 2, "relay_state": True},
        ]
        assert client.devices.get_all.await_count == refreshes + 1

    async def test_cycle_write_overlays_cycle_enabled(
        self, seeded_owners: SeededOwners
    ) -> None:
        """A cycle write overlays both written fields."""
        device = seeded_owners.device
        seen: list[dict[str, Any]] = []
        device.async_add_listener(
            lambda: seen.append(device.data["devices"][SITE_ID][PDU_ID])
        )

        await device.async_set_outlet_state(
            SITE_ID, PDU_ID, 1, state=True, cycle_enabled=False
        )

        assert seen[0]["outlet_table"][0]["cycle_enabled"] is False
        assert seen[0]["outlet_table"][0]["relay_state"] is True
        assert seen[0]["outlet_overrides"][0]["cycle_enabled"] is False
        assert seen[0]["outlet_overrides"][0]["relay_state"] is True

    @pytest.mark.parametrize(
        ("outlet_table", "device_id"),
        [
            ([{"index": 9}, "junk", {"outlet_idx": "x"}], PDU_ID),
            ("not-a-list", PDU_ID),
            ([{"index": 2}], "missing"),
        ],
    )
    async def test_unknown_outlet_gets_no_overlay(
        self, seeded_owners: SeededOwners, outlet_table: Any, device_id: str
    ) -> None:
        """An unknown outlet leaves the outlet table unmodified."""
        device = seeded_owners.device
        pdu = device.data["devices"][SITE_ID][PDU_ID]
        before_overrides = copy.deepcopy(pdu["outlet_overrides"])
        pdu["outlet_table"] = outlet_table
        listener = MagicMock()
        device.async_add_listener(listener)
        seeded_owners.network_client.devices.get_all.side_effect = UniFiConnectionError(
            "down"
        )

        await device.async_set_outlet_state(SITE_ID, device_id, 2, state=True)

        seeded_owners.network_client.devices.set_outlet_state.assert_awaited_once()
        current_pdu = device.data["devices"][SITE_ID][PDU_ID]
        assert current_pdu["outlet_table"] == outlet_table
        if device_id == "missing":
            assert current_pdu["outlet_overrides"] == before_overrides
        else:
            assert current_pdu["outlet_overrides"] is not before_overrides
            assert current_pdu["outlet_overrides"] == [
                *before_overrides,
                {"index": 2, "relay_state": True},
            ]

    async def test_outlet_index_aliases_match(
        self, seeded_owners: SeededOwners
    ) -> None:
        """``outlet_idx`` and ``outletIdx`` identify an outlet too."""
        device = seeded_owners.device
        pdu = device.data["devices"][SITE_ID][PDU_ID]
        pdu["outlet_table"] = [{"outletIdx": "4", "relay_state": False}]
        seen: list[Any] = []
        device.async_add_listener(
            lambda: seen.append(device.data["devices"][SITE_ID][PDU_ID])
        )

        await device.async_set_outlet_state(SITE_ID, PDU_ID, 4, state=True)

        assert seen[0]["outlet_table"] == [{"outletIdx": "4", "relay_state": True}]

    async def test_failed_outlet_write_is_translated(
        self, seeded_owners: SeededOwners
    ) -> None:
        """A failed write raises, publishes nothing and does not refresh."""
        device = seeded_owners.device
        client = seeded_owners.network_client
        client.devices.set_outlet_state.side_effect = UniFiConnectionError("down")
        before = device.data
        refreshes = client.devices.get_all.await_count

        with pytest.raises(HomeAssistantError, match=r"^Unable to set outlet 2") as err:
            await device.async_set_outlet_state(SITE_ID, PDU_ID, 2, state=True)

        assert err.value.translation_key == "command_failed"
        assert device.data is before
        assert client.devices.get_all.await_count == refreshes


class _FakePduController:
    """Stateful classic-API stand-in: relay state follows the last PUT."""

    def __init__(self) -> None:
        self.device = copy.deepcopy(SAMPLE_PDU_LEGACY_DEVICE)
        self.puts: list[list[dict[str, Any]]] = []

    def apply(self, overrides: list[dict[str, Any]]) -> None:
        """Apply overrides: record deep copy, update relay states, store overrides."""
        self.puts.append(copy.deepcopy(overrides))
        by_idx: dict[int, dict[str, Any]] = {}
        for o in overrides:
            idx = o.get("index")
            if idx is None:
                idx = o.get("outlet_idx")
            if idx is not None:
                with suppress(TypeError, ValueError):
                    by_idx[int(idx)] = o
        for outlet in self.device["outlet_table"]:
            idx = outlet.get("index")
            if idx is None:
                idx = outlet.get("outlet_idx")
            if idx is not None:
                with suppress(TypeError, ValueError):
                    ov = by_idx.get(int(idx))
                    outlet["relay_state"] = ov["relay_state"] if ov else True
        self.device["outlet_overrides"] = copy.deepcopy(overrides)

    def relay(self) -> dict[int, bool]:
        """Return a mapping of outlet index to relay state."""
        return {
            int(o["index"]): o["relay_state"]
            for o in self.device["outlet_table"]
            if "index" in o
        }


def _wire_pdu_controller(
    seeded_owners: SeededOwners, controller: _FakePduController
) -> DevicesEndpoint:
    """Wire a real DevicesEndpoint transport to a fake controller."""
    client = MagicMock()

    async def put(path: str, json_data: dict[str, Any]) -> None:
        controller.apply(json_data["outlet_overrides"])

    client._put = put
    client.build_legacy_api_path = lambda site, path: f"/{site}{path}"
    endpoint = DevicesEndpoint(client)

    seeded_owners.network_client.devices.set_outlet_state.side_effect = (
        endpoint.set_outlet_state
    )
    seeded_owners.network_client.devices.get_legacy_site_devices.side_effect = (
        lambda *a, **k: [copy.deepcopy(controller.device)]
    )
    return endpoint


class TestSequentialOutletWrites:
    """Sequential PDU outlet writes mirror library read-modify-write semantics."""

    async def test_two_writes_when_refresh_after_first_write_fails(
        self, seeded_owners: SeededOwners
    ) -> None:
        """Sequential writes preserve earlier outlets even when refresh fails."""
        controller = _FakePduController()
        _wire_pdu_controller(seeded_owners, controller)
        device = seeded_owners.device
        seeded_owners.network_client.devices.get_all.side_effect = UniFiConnectionError(
            "down"
        )

        await device.async_set_outlet_state(SITE_ID, PDU_ID, 1, state=False)
        await device.async_set_outlet_state(SITE_ID, PDU_ID, 2, state=False)

        assert controller.puts == [
            [
                {
                    "cycle_enabled": True,
                    "index": 1,
                    "name": "Main Server",
                    "relay_state": False,
                }
            ],
            [
                {
                    "cycle_enabled": True,
                    "index": 1,
                    "name": "Main Server",
                    "relay_state": False,
                },
                {"index": 2, "relay_state": False},
            ],
        ]
        assert controller.relay()[1] is False

    async def test_three_writes_inside_refresh_cooldown(
        self, seeded_owners: SeededOwners
    ) -> None:
        """Three back-to-back writes keep all outlets off during refresh cooldown."""
        controller = _FakePduController()
        _wire_pdu_controller(seeded_owners, controller)
        device = seeded_owners.device
        device.async_request_refresh = AsyncMock()

        await device.async_set_outlet_state(SITE_ID, PDU_ID, 1, state=False)
        await device.async_set_outlet_state(SITE_ID, PDU_ID, 2, state=False)
        await device.async_set_outlet_state(SITE_ID, PDU_ID, 3, state=False)

        assert controller.puts == [
            [
                {
                    "cycle_enabled": True,
                    "index": 1,
                    "name": "Main Server",
                    "relay_state": False,
                }
            ],
            [
                {
                    "cycle_enabled": True,
                    "index": 1,
                    "name": "Main Server",
                    "relay_state": False,
                },
                {"index": 2, "relay_state": False},
            ],
            [
                {
                    "cycle_enabled": True,
                    "index": 1,
                    "name": "Main Server",
                    "relay_state": False,
                },
                {"index": 2, "relay_state": False},
                {"index": 3, "relay_state": False},
            ],
        ]
        assert controller.relay() == {1: False, 2: False, 3: False}

    async def test_relay_change_then_cycle_change_on_same_outlet(
        self, seeded_owners: SeededOwners
    ) -> None:
        """Relay change then cycle change preserves values when cycle_enabled=None."""
        controller = _FakePduController()
        _wire_pdu_controller(seeded_owners, controller)
        device = seeded_owners.device
        device.async_request_refresh = AsyncMock()

        # Step 1: Change relay state only (cycle_enabled=None preserves True).
        await device.async_set_outlet_state(SITE_ID, PDU_ID, 1, state=False)
        assert controller.puts[0][0]["relay_state"] is False
        assert controller.puts[0][0]["cycle_enabled"] is True

        # Step 2: Change cycle_enabled to False explicitly.
        await device.async_set_outlet_state(
            SITE_ID, PDU_ID, 1, state=False, cycle_enabled=False
        )
        assert controller.puts[1][0]["relay_state"] is False
        assert controller.puts[1][0]["cycle_enabled"] is False

        # Step 3: Change relay state back to True with cycle_enabled=None (keeps False).
        await device.async_set_outlet_state(SITE_ID, PDU_ID, 1, state=True)
        assert controller.puts[2][0]["relay_state"] is True
        assert controller.puts[2][0]["cycle_enabled"] is False

    async def test_partial_overrides_matching_then_appending(
        self, seeded_owners: SeededOwners
    ) -> None:
        """Write matching existing entry updates it; new outlet appends entry."""
        controller = _FakePduController()
        _wire_pdu_controller(seeded_owners, controller)
        device = seeded_owners.device
        device.async_request_refresh = AsyncMock()

        # First write matches existing outlet 1
        await device.async_set_outlet_state(SITE_ID, PDU_ID, 1, state=False)
        assert len(controller.puts[0]) == 1
        assert controller.puts[0][0]["index"] == 1
        assert controller.puts[0][0]["relay_state"] is False

        # Second write does not match outlet 1, appends outlet 2
        await device.async_set_outlet_state(SITE_ID, PDU_ID, 2, state=False)
        assert len(controller.puts[1]) == 2
        assert controller.puts[1][0]["index"] == 1
        assert controller.puts[1][1]["index"] == 2
        published = device.data["devices"][SITE_ID][PDU_ID]["outlet_overrides"]
        assert len(published) == 2
        assert published[0]["index"] == 1
        assert published[1]["index"] == 2

    async def test_unknown_sentinel_field_survives_in_payload_and_cache(
        self, seeded_owners: SeededOwners
    ) -> None:
        """Unknown fields in override entries survive PUT and published cache."""
        controller = _FakePduController()
        _wire_pdu_controller(seeded_owners, controller)
        device = seeded_owners.device
        device.async_request_refresh = AsyncMock()

        pdu = device.data["devices"][SITE_ID][PDU_ID]
        pdu["outlet_overrides"] = [
            {"index": 1, "relay_state": True, "sentinel_custom_field": "xyz_123"}
        ]

        await device.async_set_outlet_state(SITE_ID, PDU_ID, 1, state=False)

        assert controller.puts[0][0]["sentinel_custom_field"] == "xyz_123"
        cached_overrides = device.data["devices"][SITE_ID][PDU_ID]["outlet_overrides"]
        assert cached_overrides[0]["sentinel_custom_field"] == "xyz_123"

        # Subsequent write to outlet 2 also keeps the sentinel field in entry 0
        await device.async_set_outlet_state(SITE_ID, PDU_ID, 2, state=False)
        assert controller.puts[1][0]["sentinel_custom_field"] == "xyz_123"
        cached_overrides2 = device.data["devices"][SITE_ID][PDU_ID]["outlet_overrides"]
        assert cached_overrides2[0]["sentinel_custom_field"] == "xyz_123"

    async def test_absent_overrides_seeded_from_table_published_matches_sent(
        self, seeded_owners: SeededOwners
    ) -> None:
        """When overrides are absent, seeded table matches sent payload."""
        controller = _FakePduController()
        _wire_pdu_controller(seeded_owners, controller)
        device = seeded_owners.device
        device.async_request_refresh = AsyncMock()

        pdu = device.data["devices"][SITE_ID][PDU_ID]
        del pdu["outlet_overrides"]

        await device.async_set_outlet_state(SITE_ID, PDU_ID, 2, state=True)

        sent_payload = controller.puts[0]
        published_overrides = device.data["devices"][SITE_ID][PDU_ID][
            "outlet_overrides"
        ]
        assert published_overrides == sent_payload
        assert len(published_overrides) == 3
        by_idx = {o["index"]: o for o in published_overrides}
        assert by_idx[1]["relay_state"] is True
        assert by_idx[2]["relay_state"] is True
        assert by_idx[3]["relay_state"] is True

    async def test_endpoint_failure_does_not_publish_or_leak_into_later_write(
        self, seeded_owners: SeededOwners
    ) -> None:
        """Endpoint failure raises HomeAssistantError, publishes nothing."""
        controller = _FakePduController()
        client = MagicMock()
        client._put = AsyncMock(side_effect=UniFiConnectionError("timeout"))
        client.build_legacy_api_path = lambda site, path: f"/{site}{path}"
        endpoint = DevicesEndpoint(client)
        seeded_owners.network_client.devices.set_outlet_state.side_effect = (
            endpoint.set_outlet_state
        )

        device = seeded_owners.device
        device.async_request_refresh = AsyncMock()
        before_device = copy.deepcopy(device.data["devices"][SITE_ID][PDU_ID])

        with pytest.raises(HomeAssistantError, match=r"^Unable to set outlet 2"):
            await device.async_set_outlet_state(SITE_ID, PDU_ID, 2, state=False)

        current_device = device.data["devices"][SITE_ID][PDU_ID]
        assert current_device["outlet_overrides"] == before_device["outlet_overrides"]
        assert current_device["outlet_table"] == before_device["outlet_table"]

        # Restore working endpoint transport
        client._put = AsyncMock(
            side_effect=lambda p, json_data: controller.apply(
                json_data["outlet_overrides"]
            )
        )
        await device.async_set_outlet_state(SITE_ID, PDU_ID, 1, state=False)

        assert len(controller.puts) == 1
        # The failed outlet 2 change must NOT be in the PUT payload
        put_indices = [o["index"] for o in controller.puts[0]]
        assert 2 not in put_indices
        assert controller.puts[0][0]["index"] == 1
        assert controller.puts[0][0]["relay_state"] is False

    async def test_copy_on_write_immutability(
        self, seeded_owners: SeededOwners
    ) -> None:
        """Old snapshot and entries are unchanged; new objects are created."""
        controller = _FakePduController()
        _wire_pdu_controller(seeded_owners, controller)
        device = seeded_owners.device
        device.async_request_refresh = AsyncMock()

        old_device = device.data["devices"][SITE_ID][PDU_ID]
        old_overrides = old_device["outlet_overrides"]
        old_entry_0 = old_overrides[0]
        old_entry_0_copy = dict(old_entry_0)

        await device.async_set_outlet_state(SITE_ID, PDU_ID, 1, state=False)

        # Old snapshot unchanged
        assert old_entry_0 == old_entry_0_copy
        assert old_device["outlet_overrides"] is old_overrides

        new_device = device.data["devices"][SITE_ID][PDU_ID]
        assert new_device is not old_device
        assert new_device["outlet_overrides"] is not old_overrides
        assert new_device["outlet_overrides"][0] is not old_entry_0
        assert new_device["outlet_overrides"] is not controller.puts[0]
        for new_item, put_item in zip(
            new_device["outlet_overrides"], controller.puts[0], strict=True
        ):
            assert new_item is not put_item

    @pytest.mark.parametrize(
        "table_fixture",
        [
            None,
            "not-a-list",
            [{"index": 99, "relay_state": True}],
        ],
    )
    async def test_missing_or_malformed_table_publishes_overrides_alone(
        self, seeded_owners: SeededOwners, table_fixture: Any
    ) -> None:
        """Overrides published even when table is missing, malformed or unmatched."""
        controller = _FakePduController()
        _wire_pdu_controller(seeded_owners, controller)
        device = seeded_owners.device
        device.async_request_refresh = AsyncMock()

        pdu = device.data["devices"][SITE_ID][PDU_ID]
        if table_fixture is None:
            pdu.pop("outlet_table", None)
        else:
            pdu["outlet_table"] = table_fixture

        await device.async_set_outlet_state(SITE_ID, PDU_ID, 1, state=False)

        current_pdu = device.data["devices"][SITE_ID][PDU_ID]
        assert current_pdu["outlet_overrides"][0]["relay_state"] is False
        if table_fixture is None:
            assert "outlet_table" not in current_pdu
        else:
            assert current_pdu["outlet_table"] == table_fixture

    @pytest.mark.parametrize(
        ("device_dict", "outlet_index", "state", "cycle_enabled", "expected"),
        [
            # non-dict entries dropped in overrides
            (
                {
                    "outlet_overrides": [
                        "junk",
                        None,
                        123,
                        {"index": 1, "relay_state": True},
                    ]
                },
                1,
                False,
                None,
                [{"index": 1, "relay_state": False}],
            ),
            # non-dict entries in table dropped when seeding
            (
                {
                    "outlet_table": [
                        "junk",
                        None,
                        123,
                        {"index": 1, "relay_state": True},
                    ]
                },
                1,
                False,
                None,
                [{"index": 1, "relay_state": False}],
            ),
            # unconvertible indexes skipped in table seeding
            (
                {
                    "outlet_table": [
                        {"index": "bad_index", "relay_state": True},
                        {"index": None, "outlet_idx": "also_bad"},
                        {"index": 1, "relay_state": True},
                    ]
                },
                1,
                False,
                None,
                [{"index": 1, "relay_state": False}],
            ),
            # unconvertible indexes skipped in override matching
            (
                {
                    "outlet_overrides": [
                        {"index": "invalid", "relay_state": True},
                        {"index": 1, "relay_state": True},
                    ]
                },
                1,
                False,
                None,
                [
                    {"index": "invalid", "relay_state": True},
                    {"index": 1, "relay_state": False},
                ],
            ),
            # outlet_idx fallback in seeding
            (
                {"outlet_table": [{"outlet_idx": "2", "relay_state": True}]},
                2,
                False,
                None,
                [{"index": 2, "relay_state": False}],
            ),
            # outlet_idx fallback in override matching
            (
                {"outlet_overrides": [{"outlet_idx": 2, "relay_state": True}]},
                2,
                False,
                None,
                [{"outlet_idx": 2, "relay_state": False}],
            ),
            # index wins over outlet_idx in seeding
            (
                {"outlet_table": [{"index": 1, "outlet_idx": 2, "relay_state": True}]},
                1,
                False,
                None,
                [{"index": 1, "relay_state": False}],
            ),
            # outletIdx alias is NOT recognized (only index and outlet_idx)
            (
                {"outlet_overrides": [{"outletIdx": 1, "relay_state": True}]},
                1,
                False,
                None,
                [
                    {"outletIdx": 1, "relay_state": True},
                    {"index": 1, "relay_state": False},
                ],
            ),
            # index wins over outlet_idx in override matching
            (
                {
                    "outlet_overrides": [
                        {"index": 1, "outlet_idx": 2, "relay_state": True}
                    ]
                },
                1,
                False,
                None,
                [{"index": 1, "outlet_idx": 2, "relay_state": False}],
            ),
            # name and cycle_enabled included only when present in table seeding
            (
                {
                    "outlet_table": [
                        {"index": 1, "name": "Outlet 1"},
                        {"index": 2, "cycle_enabled": True},
                        {"index": 3},
                    ]
                },
                3,
                True,
                None,
                [
                    {"index": 1, "relay_state": False, "name": "Outlet 1"},
                    {"index": 2, "relay_state": False, "cycle_enabled": True},
                    {"index": 3, "relay_state": True},
                ],
            ),
            # first matching entry updated and breaks
            (
                {
                    "outlet_overrides": [
                        {"index": 1, "relay_state": True, "first": True},
                        {"index": 1, "relay_state": True, "first": False},
                    ]
                },
                1,
                False,
                None,
                [
                    {"index": 1, "relay_state": False, "first": True},
                    {"index": 1, "relay_state": True, "first": False},
                ],
            ),
            # cycle_enabled added when not None for appended entry
            (
                {"outlet_overrides": [{"index": 1, "relay_state": True}]},
                2,
                False,
                True,
                [
                    {"index": 1, "relay_state": True},
                    {"index": 2, "relay_state": False, "cycle_enabled": True},
                ],
            ),
            # no seed source -> returns None
            ({}, 1, True, None, None),
            ({"outlet_overrides": []}, 1, True, None, None),
            (
                {"outlet_overrides": ["junk"], "outlet_table": ["junk"]},
                1,
                True,
                None,
                None,
            ),
            ({"outlet_table": "not-a-list"}, 1, True, None, None),
        ],
    )
    def test_build_outlet_overrides_branches(
        self,
        device_dict: dict[str, Any],
        outlet_index: int,
        *,
        state: bool,
        cycle_enabled: bool | None,
        expected: list[dict[str, Any]] | None,
    ) -> None:
        """Exercise all branches and ensure input dictionary is not mutated."""
        input_copy = copy.deepcopy(device_dict)
        result = _build_outlet_overrides(
            device_dict,
            outlet_index,
            state=state,
            cycle_enabled=cycle_enabled,
        )
        assert result == expected
        assert device_dict == input_copy

    @pytest.mark.parametrize(
        "device_shape",
        [
            # overrides present with custom field
            {
                "outlet_overrides": [
                    {"index": 1, "relay_state": True, "custom": "field"}
                ]
            },
            # partial overrides
            {
                "outlet_overrides": [{"index": 1, "relay_state": True}],
                "outlet_table": [{"index": 2, "relay_state": False}],
            },
            # absent overrides, seed from table
            {
                "outlet_table": [
                    {"index": 1, "relay_state": True},
                    {"index": 2, "name": "PDU2", "cycle_enabled": False},
                ]
            },
            # overrides with junk
            {"outlet_overrides": ["junk", None, {"index": 1, "relay_state": False}]},
            # table with outlet_idx alias
            {"outlet_table": [{"outlet_idx": "3", "relay_state": True}]},
            # no seed source (raises UniFiValidationError)
            {},
            {"outlet_table": []},
        ],
    )
    async def test_builder_matches_real_endpoint(
        self, device_shape: dict[str, Any]
    ) -> None:
        """Builder output equals DevicesEndpoint PUT payload or None on error."""
        captured: list[list[dict[str, Any]]] = []
        client = MagicMock()
        client.build_legacy_api_path = lambda s, p: f"/{s}{p}"

        async def put(path: str, json_data: dict[str, Any]) -> None:
            captured.append(json_data["outlet_overrides"])

        client._put = put
        endpoint = DevicesEndpoint(client)

        builder_result = _build_outlet_overrides(
            device_shape, 1, state=False, cycle_enabled=True
        )

        try:
            await endpoint.set_outlet_state(
                "default",
                "dev1",
                1,
                state=False,
                cycle_enabled=True,
                current_device=device_shape,
            )
            assert len(captured) == 1
            endpoint_result = captured[0]
        except UniFiValidationError:
            endpoint_result = None

        assert builder_result == endpoint_result


class TestClientCommands:
    """Classic client commands resolve the MAC and the mapped site name."""

    @pytest.mark.parametrize(
        ("command", "method", "refreshed"),
        [
            ("async_block_client", "block", True),
            ("async_unblock_client", "unblock", True),
            ("async_reconnect_client", "reconnect", False),
            ("async_forget_client", "forget", False),
        ],
    )
    async def test_client_command_uses_mac_and_classic_site(
        self,
        seeded_owners: SeededOwners,
        command: str,
        method: str,
        *,
        refreshed: bool,
    ) -> None:
        """Each command targets the MAC; block and unblock refresh after."""
        _with_client(seeded_owners, {"id": "c1", "macAddress": MAC})
        client = seeded_owners.network_client
        refreshes = client.devices.get_all.await_count

        await getattr(seeded_owners.device, command)(SITE_ID, "c1")

        getattr(client.clients, method).assert_awaited_once_with("default", MAC)
        assert client.devices.get_all.await_count == refreshes + refreshed

    async def test_mapped_site_name_is_used_without_internal_reference(
        self, seeded_owners: SeededOwners
    ) -> None:
        """Client commands accept the published (fuzzy) mapping."""
        config = seeded_owners.config
        del config.data["sites"][SITE_ID]["internalReference"]
        config.data["legacy_site_names"] = {SITE_ID: "branch"}
        _with_client(seeded_owners, {"id": "c1", "mac": MAC})

        await seeded_owners.device.async_reconnect_client(SITE_ID, "c1")

        seeded_owners.network_client.clients.reconnect.assert_awaited_once_with(
            "branch", MAC
        )

    async def test_client_without_mac_is_a_translated_error(
        self, seeded_owners: SeededOwners
    ) -> None:
        """A client action without a resolvable MAC raises client_not_resolvable."""
        _with_client(seeded_owners, {"id": "c1"})

        with pytest.raises(HomeAssistantError) as caught:
            await seeded_owners.device.async_block_client(SITE_ID, "c1")

        assert caught.value.translation_key == "client_not_resolvable"
        assert caught.value.translation_placeholders == {"client_id": "c1"}
        seeded_owners.network_client.clients.block.assert_not_awaited()

    async def test_client_failure_is_translated(
        self, seeded_owners: SeededOwners
    ) -> None:
        """A failed client command keeps its message and does not refresh."""
        _with_client(seeded_owners, {"id": "c1", "macAddress": MAC})
        client = seeded_owners.network_client
        client.clients.block.side_effect = UniFiConnectionError("down")
        refreshes = client.devices.get_all.await_count

        with pytest.raises(HomeAssistantError, match=r"^Unable to block client c1"):
            await seeded_owners.device.async_block_client(SITE_ID, "c1")

        assert client.devices.get_all.await_count == refreshes

    async def test_forget_batch_uses_the_verified_site_name(
        self, seeded_owners: SeededOwners
    ) -> None:
        """Batch forget writes only to the verified classic site."""
        forget_batch = seeded_owners.network_client.clients.forget_batch
        forget_batch.return_value = True

        assert (
            await seeded_owners.device.async_forget_clients_batch(SITE_ID, [MAC])
            is True
        )
        forget_batch.assert_awaited_once_with("default", [MAC])

    async def test_forget_batch_never_uses_the_mapping(
        self, seeded_owners: SeededOwners
    ) -> None:
        """Without internalReference batch forget raises and sends nothing."""
        config = seeded_owners.config
        del config.data["sites"][SITE_ID]["internalReference"]
        forget_batch = seeded_owners.network_client.clients.forget_batch

        with pytest.raises(HomeAssistantError) as caught:
            await seeded_owners.device.async_forget_clients_batch(SITE_ID, [MAC])

        assert caught.value.translation_key == "legacy_site_not_found"
        forget_batch.assert_not_awaited()

    async def test_forget_batch_failure_is_translated(
        self, seeded_owners: SeededOwners
    ) -> None:
        """A failed batch forget raises command_failed with its message."""
        seeded_owners.network_client.clients.forget_batch.side_effect = RuntimeError(
            "dropped"
        )

        with pytest.raises(
            HomeAssistantError, match="Unable to forget clients for site"
        ) as caught:
            await seeded_owners.device.async_forget_clients_batch(SITE_ID, [MAC])

        assert caught.value.translation_key == "command_failed"
