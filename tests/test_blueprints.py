"""Tests for the UniFi Insights automation blueprints.

Every blueprint is loaded with the Home Assistant YAML loader (which understands
``!input``), validated by the blueprint loader Home Assistant itself uses, and
then installed into the config directory of the test instance. The execution
tests set up a real automation with ``use_blueprint``, change states or fire the
trigger, and assert on what the user-supplied actions did.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from freezegun import api as freezegun_api
from homeassistant.components.automation.helpers import async_get_blueprints
from homeassistant.components.blueprint.schemas import BLUEPRINT_SCHEMA
from homeassistant.components.device_tracker import ScannerEntity, SourceType
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.setup import async_setup_component
from homeassistant.util import yaml as yaml_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockEntityPlatform,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.unifi_insights.const import CONF_TRACK_WIFI_CLIENTS, DOMAIN

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from unittest.mock import MagicMock

    from freezegun.api import FrozenDateTimeFactory
    from homeassistant.core import HomeAssistant, ServiceCall
    from homeassistant.helpers import entity_registry as er

BLUEPRINT_SOURCE = Path(__file__).parent.parent / "blueprints" / "automation" / DOMAIN
AP_OVERLOAD = "ap_overload_alert.yaml"
INFRASTRUCTURE_OFFLINE = "infrastructure_offline_alert.yaml"
SECURE_VLAN = "secure_vlan_new_client_alert.yaml"
ALL_BLUEPRINTS = (AP_OVERLOAD, INFRASTRUCTURE_OFFLINE, SECURE_VLAN)
AUTOMATION_ENTITY_ID = "automation.blueprint_under_test"

# Real seconds a test waits for a run to reach the state it expects, and for the
# event loop to react to one simulated second of the freezer.
WAIT_TIMEOUT_SECONDS = 10.0
STEP_SETTLE_SECONDS = 0.02

# The version floor of this integration (hacs.json "homeassistant").
MIN_HOME_ASSISTANT_VERSION = "2026.6.0"

EXPECTED_ENTITY_SELECTORS: dict[str, dict[str, dict[str, Any]]] = {
    AP_OVERLOAD: {
        "ap_client_sensors": {
            "entity": {"integration": DOMAIN, "domain": "sensor", "multiple": True}
        },
        # Utilisation can come from any integration: no integration filter.
        "utilisation_sensors": {"entity": {"domain": "sensor", "multiple": True}},
    },
    INFRASTRUCTURE_OFFLINE: {
        "connectivity_sensors": {
            "entity": {
                "integration": DOMAIN,
                "domain": "binary_sensor",
                "device_class": "connectivity",
                "multiple": True,
            }
        },
    },
    SECURE_VLAN: {
        "allowed_trackers": {
            "entity": {
                "integration": DOMAIN,
                "domain": "device_tracker",
                "multiple": True,
            }
        },
    },
}

FIVE_MINUTES = {"hours": 0, "minutes": 5, "seconds": 0}


def _load(name: str) -> dict[str, Any]:
    """Load a blueprint from the repository with the Home Assistant loader."""
    return yaml_util.load_yaml_dict(BLUEPRINT_SOURCE / name)


# Loggers that report a blueprint automation which fails or misbehaves at run time.
WATCHED_LOGGERS = (
    "homeassistant.components.automation",
    "homeassistant.components.homeassistant.triggers",
    "homeassistant.helpers.condition",
    "homeassistant.helpers.script",
    "homeassistant.helpers.template",
)


@pytest.fixture(autouse=True)
def _no_automation_warnings(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Fail a test whose automation logged a warning or an error.

    A dropped run ("Already running"), a template error or a trigger that could
    not initialise would otherwise only show up as a missing call.
    """
    yield
    noisy = [
        f"{record.name}: {record.getMessage()}"
        for record in caplog.records
        if record.levelno >= logging.WARNING and record.name.startswith(WATCHED_LOGGERS)
    ]
    assert not noisy, noisy


# ---------------------------------------------------------------------------
# Static checks: parse, schema, structure
# ---------------------------------------------------------------------------


def test_blueprint_directory_holds_exactly_the_three_blueprints() -> None:
    """The distributed directory contains the three blueprints and nothing else."""
    assert sorted(path.name for path in BLUEPRINT_SOURCE.iterdir()) == sorted(
        ALL_BLUEPRINTS
    )


@pytest.mark.parametrize("name", ALL_BLUEPRINTS)
def test_blueprint_parses_and_matches_the_blueprint_schema(name: str) -> None:
    """Each file loads with ``!input`` support and passes the blueprint schema."""
    data = _load(name)
    validated = BLUEPRINT_SCHEMA(data)

    metadata = validated["blueprint"]
    assert metadata["domain"] == "automation"
    assert metadata["name"].startswith("UniFi Insights")
    assert metadata["description"].strip()
    assert metadata["homeassistant"] == {"min_version": MIN_HOME_ASSISTANT_VERSION}
    # Every input is described for the blueprint UI.
    for input_name, definition in metadata["input"].items():
        assert definition["name"], input_name
        assert definition["description"], input_name
        assert "selector" in definition, input_name


@pytest.mark.parametrize("name", ALL_BLUEPRINTS)
def test_blueprint_uses_the_modern_automation_syntax(name: str) -> None:
    """Plural ``triggers``/``conditions``/``actions`` keys, no legacy singular keys."""
    data = _load(name)

    assert "triggers" in data
    assert "actions" in data
    assert not {"trigger", "condition", "action", "platform"} & set(data)
    for trigger in data["triggers"]:
        assert "trigger" in trigger
        assert "platform" not in trigger


@pytest.mark.parametrize("name", ALL_BLUEPRINTS)
def test_blueprint_selectors_that_filter_by_integration_use_unifi_insights(
    name: str,
) -> None:
    """No selector filters on any integration other than UniFi Insights."""
    inputs = _load(name)["blueprint"]["input"]

    for input_name, definition in inputs.items():
        entity = definition["selector"].get("entity", {})
        if "integration" in entity:
            assert entity["integration"] == DOMAIN, input_name


@pytest.mark.parametrize(
    ("name", "input_name", "selector"),
    [
        pytest.param(name, input_name, selector, id=f"{name}-{input_name}")
        for name, selectors in EXPECTED_ENTITY_SELECTORS.items()
        for input_name, selector in selectors.items()
    ],
)
def test_entity_selectors_are_exactly_the_planned_filters(
    name: str, input_name: str, selector: dict[str, Any]
) -> None:
    """The entity pickers show only the entities the blueprint can work with."""
    definition = _load(name)["blueprint"]["input"][input_name]

    assert definition["selector"] == selector


def test_optional_inputs_default_to_empty_or_on() -> None:
    """Optional inputs have defaults so a minimal setup validates."""
    ap = _load(AP_OVERLOAD)["blueprint"]["input"]
    offline = _load(INFRASTRUCTURE_OFFLINE)["blueprint"]["input"]
    vlan = _load(SECURE_VLAN)["blueprint"]["input"]

    assert ap["utilisation_sensors"]["default"] == []
    assert offline["recovery_actions"]["default"] == []
    assert offline["treat_unavailable_as_offline"]["default"] is True
    assert offline["treat_unavailable_as_offline"]["selector"] == {"boolean": {}}
    assert vlan["allowed_trackers"]["default"] == []
    # The secure prefixes are required: without one the blueprint is meaningless.
    assert "default" not in vlan["secure_prefixes"]
    assert vlan["secure_prefixes"]["selector"] == {"text": {"multiple": True}}


def test_ap_overload_uses_numeric_state_triggers_with_ids_and_a_duration() -> None:
    """Client overload and utilisation are separate ``for:`` numeric triggers."""
    triggers = _load(AP_OVERLOAD)["triggers"]

    assert [(t["trigger"], t["id"]) for t in triggers] == [
        ("numeric_state", "client_overload"),
        ("numeric_state", "utilisation"),
    ]
    assert all("for" in trigger for trigger in triggers)


def test_ap_overload_description_says_there_is_no_utilisation_sensor() -> None:
    """Users must be told UniFi Insights has no channel utilisation sensor."""
    metadata = _load(AP_OVERLOAD)["blueprint"]
    text = " ".join(
        [metadata["description"]]
        + [
            definition.get("description", "")
            for definition in metadata["input"].values()
        ]
    ).lower()

    assert "does not currently" in text
    assert "channel utilisation sensor" in text
    assert "another" in text


def test_offline_description_states_the_unavailable_limits() -> None:
    """A confirmed offline device and a polling failure both read unavailable."""
    description = _load(INFRASTRUCTURE_OFFLINE)["blueprint"]["description"].lower()

    assert "confirmed offline device" in description
    assert "controller" in description
    assert description.count("unavailable") >= 2


def test_offline_blueprint_separates_offline_and_recovery_with_trigger_ids() -> None:
    """Offline goes to off/unavailable for a duration, recovery returns to on."""
    triggers = _load(INFRASTRUCTURE_OFFLINE)["triggers"]

    offline, recovery = triggers
    assert offline["id"] == "offline"
    assert offline["to"] == ["off", "unavailable"]
    assert "for" in offline
    assert recovery["id"] == "recovery"
    assert recovery["from"] == ["off", "unavailable"]
    assert recovery["to"] == "on"


def test_secure_vlan_triggers_on_new_entity_registry_entries() -> None:
    """A new client is a new tracker, so the trigger is a registry ``create``."""
    assert _load(SECURE_VLAN)["triggers"] == [
        {
            "trigger": "event",
            "event_type": "entity_registry_updated",
            "event_data": {"action": "create"},
        }
    ]


def test_secure_vlan_description_states_the_prerequisites_and_limits() -> None:
    """Tracking is opt-in, the VLAN comes from the IP, and the burst has a limit."""
    data = _load(SECURE_VLAN)
    description = " ".join(data["blueprint"]["description"].lower().split())

    assert "client tracking" in description
    assert "opt-in" in description or "opt in" in description
    assert "ip" in description
    assert "inferred" in description
    assert "first time" in description
    assert "many" in description

    # ``mode: parallel`` drops every run beyond ``max``: the text must say so
    # and name the limit that is really configured.
    sentences = re.split(r"(?<=[.!?])\s+", description)
    dropped = [sentence for sentence in sentences if "dropped" in sentence]
    assert dropped, "the description must say that runs beyond the limit are dropped"
    assert any(str(data["max"]) in sentence for sentence in dropped), (
        f"the sentence about dropped runs must name the limit ({data['max']})"
    )


def test_secure_vlan_exposes_name_entity_and_ip_but_never_the_mac() -> None:
    """The actions get ``client_entity``, ``client_name`` and ``client_ip`` only."""
    data = _load(SECURE_VLAN)
    variable_steps = [step for step in data["actions"] if "variables" in step]

    assert len(variable_steps) == 1
    assert set(variable_steps[0]["variables"]) == {
        "client_entity",
        "client_name",
        "client_ip",
    }
    everything = str({key: data[key] for key in data if key != "blueprint"})
    assert not re.search(r"\bmac", everything, re.IGNORECASE)


@pytest.mark.parametrize("name", ALL_BLUEPRINTS)
async def test_home_assistant_loads_each_blueprint_from_its_config_directory(
    hass: HomeAssistant, blueprint_dir: Path, name: str
) -> None:
    """The production loader accepts the installed file and the version floor."""
    blueprint = await async_get_blueprints(hass).async_get_blueprint(f"{DOMAIN}/{name}")

    assert blueprint.domain == "automation"
    assert blueprint.validate() is None
    assert blueprint.name.startswith("UniFi Insights")


# ---------------------------------------------------------------------------
# Execution harness
# ---------------------------------------------------------------------------


@pytest.fixture
async def blueprint_dir(hass: HomeAssistant, tmp_path: Path) -> Path:
    """Copy the blueprints into the config directory of the test instance."""
    hass.config.config_dir = str(tmp_path)
    target = Path(hass.config.path("blueprints/automation/unifi_insights"))
    await hass.async_add_executor_job(shutil.copytree, BLUEPRINT_SOURCE, target)
    return target


@pytest.fixture
def calls(hass: HomeAssistant) -> list[ServiceCall]:
    """Record every call of the ``test.record`` service the user actions invoke."""
    return async_mock_service(hass, "test", "record")


async def _use_blueprint(
    hass: HomeAssistant, name: str, inputs: dict[str, Any]
) -> None:
    """Set up one automation that uses the installed blueprint."""
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "alias": "Blueprint under test",
                "use_blueprint": {"path": f"{DOMAIN}/{name}", "input": inputs},
            }
        },
    )
    await hass.async_block_till_done()
    state = hass.states.get(AUTOMATION_ENTITY_ID)
    assert state is not None
    assert state.state == "on", "the blueprint did not produce a working automation"


async def _advance(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, **delta: int
) -> None:
    """Move time forward and let every due timer run."""
    freezer.tick(timedelta(**delta))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def _active_runs(hass: HomeAssistant) -> int:
    """Return how many runs of the automation under test are active or queued."""
    state = hass.states.get(AUTOMATION_ENTITY_ID)
    assert state is not None
    return int(state.attributes["current"])


async def _poll(condition: Callable[[], bool], seconds: float) -> bool:
    """Let the event loop run until ``condition`` holds or ``seconds`` have passed.

    The freezer also freezes the loop clock, so the limit is measured with the
    real clock; ``asyncio.sleep`` with a positive delay would never return.
    ``freezegun_api.real_monotonic`` is read through the module on purpose:
    freezegun replaces a real clock function imported into any other namespace.
    """
    deadline = freezegun_api.real_monotonic() + seconds
    while not condition():
        if freezegun_api.real_monotonic() >= deadline:
            return False
        await asyncio.sleep(0)
    return True


async def _wait_until(condition: Callable[[], bool], expected: str) -> None:
    """Wait for ``condition`` without moving time, or fail with what was expected.

    Runs parked on a ``delay`` or a ``wait_template`` must be observed through
    their run count or their recorded calls: ``async_block_till_done`` would
    wait for them to finish, which is exactly what the caller wants to watch.
    """
    if not await _poll(condition, WAIT_TIMEOUT_SECONDS):
        pytest.fail(
            f"Timed out after {WAIT_TIMEOUT_SECONDS:g} s waiting for {expected}"
        )


async def _advance_while_runs_wait(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, **delta: int
) -> None:
    """Move time forward and fire the due timers, without waiting for any run.

    The caller then waits for what it expects with ``_wait_until``.
    """
    freezer.tick(timedelta(**delta))
    async_fire_time_changed(hass)


async def _advance_until(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    condition: Callable[[], bool],
    expected: str,
    *,
    limit_seconds: int = 30,
) -> None:
    """Let simulated time pass one second at a time until ``condition`` holds.

    A ``delay`` or a timeout only starts counting when its run reaches it, so one
    big step could pass before the timer exists. Small steps cannot miss it, and
    each step gives the event loop a moment to react before the next tick.
    """
    for _ in range(limit_seconds):
        await _advance_while_runs_wait(hass, freezer, seconds=1)
        if await _poll(condition, STEP_SETTLE_SECONDS):
            return
    pytest.fail(
        f"Timed out after {limit_seconds} simulated seconds waiting for {expected}"
    )


async def _set_state(
    hass: HomeAssistant,
    entity_id: str,
    state: str,
    attributes: dict[str, Any] | None = None,
) -> None:
    """Write a state and let the automation react."""
    hass.states.async_set(entity_id, state, attributes)
    await hass.async_block_till_done()


def _data(calls: list[ServiceCall]) -> list[dict[str, Any]]:
    """Return the data of every recorded call."""
    return [dict(call.data) for call in calls]


# ---------------------------------------------------------------------------
# AP overload
# ---------------------------------------------------------------------------

AP_CLIENTS = "sensor.lobby_ap_wireless_clients"
AP_CLIENTS_2 = "sensor.garage_ap_wireless_clients"
AP_UTILISATION = "sensor.lobby_ap_channel_utilisation"
AP_ACTIONS = [
    {
        "action": "test.record",
        "data": {
            "id": "{{ trigger.id }}",
            "entity": "{{ trigger.entity_id }}",
            "value": "{{ trigger.to_state.state }}",
        },
    }
]


def _ap_inputs(**overrides: Any) -> dict[str, Any]:
    """Return the AP overload inputs: 30 clients, 80% utilisation, five minutes."""
    inputs: dict[str, Any] = {
        "ap_client_sensors": [AP_CLIENTS],
        "client_threshold": 30,
        "utilisation_threshold": 80,
        "duration": FIVE_MINUTES,
        "actions": AP_ACTIONS,
    }
    inputs.update(overrides)
    return inputs


async def test_ap_overload_alerts_when_clients_stay_above_the_threshold(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    blueprint_dir: Path,
    calls: list[ServiceCall],
) -> None:
    """Crossing the client threshold runs the actions once the duration passes."""
    hass.states.async_set(AP_CLIENTS, "12")
    await _use_blueprint(hass, AP_OVERLOAD, _ap_inputs())

    await _set_state(hass, AP_CLIENTS, "31")
    await _advance(hass, freezer, minutes=4)
    assert calls == []

    await _advance(hass, freezer, minutes=2)
    assert _data(calls) == [
        {"id": "client_overload", "entity": AP_CLIENTS, "value": 31}
    ]


async def test_ap_overload_alerts_when_utilisation_stays_above_the_threshold(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    blueprint_dir: Path,
    calls: list[ServiceCall],
) -> None:
    """A utilisation sensor from another integration triggers its own alert."""
    hass.states.async_set(AP_CLIENTS, "12")
    hass.states.async_set(AP_UTILISATION, "40")
    await _use_blueprint(
        hass, AP_OVERLOAD, _ap_inputs(utilisation_sensors=[AP_UTILISATION])
    )

    await _set_state(hass, AP_UTILISATION, "79")
    await _advance(hass, freezer, minutes=6)
    assert calls == []

    await _set_state(hass, AP_UTILISATION, "92")
    await _advance(hass, freezer, minutes=6)
    assert _data(calls) == [
        {"id": "utilisation", "entity": AP_UTILISATION, "value": 92}
    ]


async def test_ap_overload_with_no_utilisation_sensor_still_alerts_on_clients(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    blueprint_dir: Path,
    calls: list[ServiceCall],
) -> None:
    """The optional utilisation input can stay at its empty default."""
    hass.states.async_set(AP_CLIENTS, "5")
    await _use_blueprint(hass, AP_OVERLOAD, _ap_inputs())

    await _set_state(hass, AP_CLIENTS, "45")
    await _advance(hass, freezer, minutes=6)

    assert _data(calls) == [
        {"id": "client_overload", "entity": AP_CLIENTS, "value": 45}
    ]


async def test_ap_overload_ignores_a_value_equal_to_the_threshold(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    blueprint_dir: Path,
    calls: list[ServiceCall],
) -> None:
    """Overload means strictly more clients than the threshold."""
    hass.states.async_set(AP_CLIENTS, "5")
    await _use_blueprint(hass, AP_OVERLOAD, _ap_inputs())

    await _set_state(hass, AP_CLIENTS, "30")
    await _advance(hass, freezer, minutes=10)

    assert calls == []


async def test_ap_overload_drop_before_the_duration_cancels_the_alert(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    blueprint_dir: Path,
    calls: list[ServiceCall],
) -> None:
    """A short spike must not alert."""
    hass.states.async_set(AP_CLIENTS, "5")
    await _use_blueprint(hass, AP_OVERLOAD, _ap_inputs())

    await _set_state(hass, AP_CLIENTS, "50")
    await _advance(hass, freezer, minutes=2)
    await _set_state(hass, AP_CLIENTS, "10")
    await _advance(hass, freezer, minutes=10)

    assert calls == []


@pytest.mark.parametrize("gap_state", [STATE_UNKNOWN, STATE_UNAVAILABLE])
@pytest.mark.parametrize(
    ("entity_id", "high", "low", "trigger_id"),
    [
        pytest.param(AP_CLIENTS, "50", "10", "client_overload", id="clients"),
        pytest.param(AP_UTILISATION, "95", "20", "utilisation", id="utilisation"),
    ],
)
async def test_ap_overload_ignores_a_crossing_that_follows_unknown_or_unavailable(
    hass: HomeAssistant,
    *,
    freezer: FrozenDateTimeFactory,
    blueprint_dir: Path,
    calls: list[ServiceCall],
    gap_state: str,
    entity_id: str,
    high: str,
    low: str,
    trigger_id: str,
) -> None:
    """After an outage the first high reading says nothing about a real change."""
    hass.states.async_set(AP_CLIENTS, "10")
    hass.states.async_set(AP_UTILISATION, "20")
    await _use_blueprint(
        hass, AP_OVERLOAD, _ap_inputs(utilisation_sensors=[AP_UTILISATION])
    )

    await _set_state(hass, entity_id, gap_state)
    await _set_state(hass, entity_id, high)
    await _advance(hass, freezer, minutes=10)
    assert calls == [], "a reading that follows a gap must not alert"

    # The same automation still alerts for a genuine crossing afterwards.
    await _set_state(hass, entity_id, low)
    await _set_state(hass, entity_id, high)
    await _advance(hass, freezer, minutes=10)
    assert _data(calls) == [{"id": trigger_id, "entity": entity_id, "value": int(high)}]


@pytest.mark.parametrize("gap_state", [STATE_UNKNOWN, STATE_UNAVAILABLE])
async def test_ap_overload_does_not_alert_while_the_sensor_is_unknown_or_unavailable(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    blueprint_dir: Path,
    calls: list[ServiceCall],
    gap_state: str,
) -> None:
    """Going unknown or unavailable on its own never runs the actions."""
    hass.states.async_set(AP_CLIENTS, "50")
    await _use_blueprint(hass, AP_OVERLOAD, _ap_inputs())

    await _set_state(hass, AP_CLIENTS, gap_state)
    await _advance(hass, freezer, minutes=10)

    assert calls == []


async def test_ap_overload_alerts_for_two_access_points_at_the_same_time(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    blueprint_dir: Path,
    calls: list[ServiceCall],
) -> None:
    """Simultaneous overloads are queued, not dropped as 'already running'."""
    hass.states.async_set(AP_CLIENTS, "5")
    hass.states.async_set(AP_CLIENTS_2, "5")
    actions = [
        {"delay": {"seconds": 5}},
        *AP_ACTIONS,
    ]
    await _use_blueprint(
        hass,
        AP_OVERLOAD,
        _ap_inputs(ap_client_sensors=[AP_CLIENTS, AP_CLIENTS_2], actions=actions),
    )

    hass.states.async_set(AP_CLIENTS, "40")
    hass.states.async_set(AP_CLIENTS_2, "41")
    await hass.async_block_till_done()
    # Both timers fire together; the first run parks on its delay, the second queues.
    await _advance_while_runs_wait(hass, freezer, minutes=6)
    await _wait_until(lambda: _active_runs(hass) == 2, "both runs to start")
    assert calls == []
    await _advance_until(
        hass, freezer, lambda: len(calls) >= 1, "the first run to record its call"
    )
    assert len(calls) == 1
    await _advance_until(
        hass, freezer, lambda: len(calls) >= 2, "the queued run to record its call"
    )
    await hass.async_block_till_done()

    assert sorted(call["entity"] for call in _data(calls)) == sorted(
        [AP_CLIENTS, AP_CLIENTS_2]
    )


# ---------------------------------------------------------------------------
# Infrastructure offline
# ---------------------------------------------------------------------------

SWITCH_ONLINE = "binary_sensor.core_switch_status"
SWITCH_2_ONLINE = "binary_sensor.garage_switch_status"
OFFLINE_ACTIONS = [
    {
        "action": "test.record",
        "data": {
            "event": "offline",
            "entity": "{{ trigger.entity_id }}",
            "state": "{{ trigger.to_state.state }}",
        },
    }
]
RECOVERY_ACTIONS = [
    {
        "action": "test.record",
        "data": {
            "event": "recovery",
            "entity": "{{ trigger.entity_id }}",
            "state": "{{ trigger.to_state.state }}",
        },
    }
]


def _offline_inputs(**overrides: Any) -> dict[str, Any]:
    """Return the offline inputs with a five minute duration and both actions."""
    inputs: dict[str, Any] = {
        "connectivity_sensors": [SWITCH_ONLINE],
        "offline_duration": FIVE_MINUTES,
        "offline_actions": OFFLINE_ACTIONS,
        "recovery_actions": RECOVERY_ACTIONS,
    }
    inputs.update(overrides)
    return inputs


async def test_offline_actions_run_when_a_device_stays_off(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    blueprint_dir: Path,
    calls: list[ServiceCall],
) -> None:
    """A connectivity sensor that is ``off`` for the duration is offline."""
    hass.states.async_set(SWITCH_ONLINE, "on")
    await _use_blueprint(hass, INFRASTRUCTURE_OFFLINE, _offline_inputs())

    await _set_state(hass, SWITCH_ONLINE, "off")
    await _advance(hass, freezer, minutes=4)
    assert calls == []

    await _advance(hass, freezer, minutes=2)
    assert _data(calls) == [
        {"event": "offline", "entity": SWITCH_ONLINE, "state": "off"}
    ]


async def test_offline_actions_run_when_a_device_stays_unavailable(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    blueprint_dir: Path,
    calls: list[ServiceCall],
) -> None:
    """By default ``unavailable`` counts as offline: that is how a lost device reads."""
    hass.states.async_set(SWITCH_ONLINE, "on")
    await _use_blueprint(hass, INFRASTRUCTURE_OFFLINE, _offline_inputs())

    await _set_state(hass, SWITCH_ONLINE, STATE_UNAVAILABLE)
    await _advance(hass, freezer, minutes=6)

    assert _data(calls) == [
        {"event": "offline", "entity": SWITCH_ONLINE, "state": "unavailable"}
    ]


async def test_unavailable_is_ignored_when_it_is_not_treated_as_offline(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    blueprint_dir: Path,
    calls: list[ServiceCall],
) -> None:
    """With the switch off, unavailable stays quiet but ``off`` still alerts."""
    hass.states.async_set(SWITCH_ONLINE, "on")
    await _use_blueprint(
        hass,
        INFRASTRUCTURE_OFFLINE,
        _offline_inputs(treat_unavailable_as_offline=False),
    )

    await _set_state(hass, SWITCH_ONLINE, STATE_UNAVAILABLE)
    await _advance(hass, freezer, minutes=6)
    assert calls == []

    await _set_state(hass, SWITCH_ONLINE, "off")
    await _advance(hass, freezer, minutes=6)
    assert _data(calls) == [
        {"event": "offline", "entity": SWITCH_ONLINE, "state": "off"}
    ]


@pytest.mark.parametrize("previous", ["off", STATE_UNAVAILABLE])
async def test_recovery_actions_run_when_a_device_comes_back_on(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    blueprint_dir: Path,
    calls: list[ServiceCall],
    previous: str,
) -> None:
    """Returning to ``on`` from ``off`` or ``unavailable`` is a recovery."""
    hass.states.async_set(SWITCH_ONLINE, previous)
    await _use_blueprint(hass, INFRASTRUCTURE_OFFLINE, _offline_inputs())

    await _set_state(hass, SWITCH_ONLINE, "on")

    assert _data(calls) == [
        {"event": "recovery", "entity": SWITCH_ONLINE, "state": "on"}
    ]


async def test_offline_then_recovery_runs_each_action_list_once(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    blueprint_dir: Path,
    calls: list[ServiceCall],
) -> None:
    """The trigger IDs keep the two action lists apart."""
    hass.states.async_set(SWITCH_ONLINE, "on")
    await _use_blueprint(hass, INFRASTRUCTURE_OFFLINE, _offline_inputs())

    await _set_state(hass, SWITCH_ONLINE, "off")
    await _advance(hass, freezer, minutes=6)
    await _set_state(hass, SWITCH_ONLINE, "on")

    assert [call["event"] for call in _data(calls)] == ["offline", "recovery"]


async def test_a_short_outage_does_not_raise_the_offline_alert(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    blueprint_dir: Path,
    calls: list[ServiceCall],
) -> None:
    """Coming back inside the duration cancels the offline alert."""
    hass.states.async_set(SWITCH_ONLINE, "on")
    await _use_blueprint(hass, INFRASTRUCTURE_OFFLINE, _offline_inputs())

    await _set_state(hass, SWITCH_ONLINE, "off")
    await _advance(hass, freezer, minutes=2)
    await _set_state(hass, SWITCH_ONLINE, "on")
    await _advance(hass, freezer, minutes=10)

    assert [call["event"] for call in _data(calls)] == ["recovery"]


async def test_recovery_actions_are_optional(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    blueprint_dir: Path,
    calls: list[ServiceCall],
) -> None:
    """With no recovery actions the offline alert works and recovery is silent."""
    inputs = _offline_inputs()
    del inputs["recovery_actions"]
    hass.states.async_set(SWITCH_ONLINE, "on")
    await _use_blueprint(hass, INFRASTRUCTURE_OFFLINE, inputs)

    await _set_state(hass, SWITCH_ONLINE, "off")
    await _advance(hass, freezer, minutes=6)
    await _set_state(hass, SWITCH_ONLINE, "on")

    assert [call["event"] for call in _data(calls)] == ["offline"]


async def test_offline_alerts_for_several_devices_that_fail_together(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    blueprint_dir: Path,
    calls: list[ServiceCall],
) -> None:
    """A failed uplink takes several devices down at once: none may be dropped."""
    hass.states.async_set(SWITCH_ONLINE, "on")
    hass.states.async_set(SWITCH_2_ONLINE, "on")
    actions = [{"delay": {"seconds": 5}}, *OFFLINE_ACTIONS]
    await _use_blueprint(
        hass,
        INFRASTRUCTURE_OFFLINE,
        _offline_inputs(
            connectivity_sensors=[SWITCH_ONLINE, SWITCH_2_ONLINE],
            offline_actions=actions,
        ),
    )

    hass.states.async_set(SWITCH_ONLINE, STATE_UNAVAILABLE)
    hass.states.async_set(SWITCH_2_ONLINE, STATE_UNAVAILABLE)
    await hass.async_block_till_done()
    # Both timers fire together; the first run parks on its delay, the second queues.
    await _advance_while_runs_wait(hass, freezer, minutes=6)
    await _wait_until(lambda: _active_runs(hass) == 2, "both runs to start")
    assert calls == []
    await _advance_until(
        hass, freezer, lambda: len(calls) >= 1, "the first run to record its call"
    )
    assert len(calls) == 1
    await _advance_until(
        hass, freezer, lambda: len(calls) >= 2, "the queued run to record its call"
    )
    await hass.async_block_till_done()

    assert sorted(call["entity"] for call in _data(calls)) == sorted(
        [SWITCH_ONLINE, SWITCH_2_ONLINE]
    )


async def test_offline_ignores_sensors_that_were_not_selected(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    blueprint_dir: Path,
    calls: list[ServiceCall],
) -> None:
    """Only the selected connectivity sensors count."""
    hass.states.async_set(SWITCH_ONLINE, "on")
    hass.states.async_set(SWITCH_2_ONLINE, "on")
    await _use_blueprint(hass, INFRASTRUCTURE_OFFLINE, _offline_inputs())

    await _set_state(hass, SWITCH_2_ONLINE, "off")
    await _advance(hass, freezer, minutes=10)
    await _set_state(hass, SWITCH_2_ONLINE, "on")

    assert calls == []


# ---------------------------------------------------------------------------
# Secure VLAN: new client alert, against the real device_tracker platform
# ---------------------------------------------------------------------------

VLAN_ACTIONS = [
    {
        "action": "test.record",
        "data": {
            "entity": "{{ client_entity }}",
            "name": "{{ client_name }}",
            "ip": "{{ client_ip }}",
        },
    }
]


def _vlan_inputs(**overrides: Any) -> dict[str, Any]:
    """Return the secure VLAN inputs with one secure prefix."""
    inputs: dict[str, Any] = {
        "secure_prefixes": ["10.0.50."],
        "actions": VLAN_ACTIONS,
    }
    inputs.update(overrides)
    return inputs


def _client(number: int, name: str, ip: str) -> dict[str, Any]:
    """Build one connected wireless client payload."""
    return {
        "id": f"client_{number}",
        "macAddress": f"aa:bb:cc:dd:ee:{number:02x}",
        "name": name,
        "hostname": name.lower().replace(" ", "-"),
        "type": "WIRELESS",
        "connected": True,
        "uplinkDeviceId": None,
        "ipAddress": ip,
    }


@pytest.fixture
async def tracking_entry(
    hass: HomeAssistant,
    *,
    mock_config_entry: MockConfigEntry,
    mock_network_client: MagicMock,
    mock_protect_client: MagicMock,
    mock_local_auth: MagicMock,
    enable_custom_integrations: None,
) -> MockConfigEntry:
    """Set up the integration with client tracking on and no client connected."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_TRACK_WIFI_CLIENTS: True}
    )
    mock_network_client.sites.get_all.return_value = [
        {"id": "default", "name": "Default"}
    ]
    mock_network_client.clients.get_all.return_value = []
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry


async def _connect(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    network_client: MagicMock,
    *clients: dict[str, Any],
) -> None:
    """Make clients appear on the controller and let the integration poll them."""
    network_client.clients.get_all.return_value = list(clients)
    await entry.runtime_data.device_coordinator.async_refresh()
    await hass.async_block_till_done()


async def test_new_tracker_on_a_secure_prefix_runs_the_actions(
    hass: HomeAssistant,
    blueprint_dir: Path,
    calls: list[ServiceCall],
    tracking_entry: MockConfigEntry,
    mock_network_client: MagicMock,
) -> None:
    """A tracker created for a client in a secure prefix reaches the actions."""
    await _use_blueprint(hass, SECURE_VLAN, _vlan_inputs())

    await _connect(
        hass,
        tracking_entry,
        mock_network_client,
        _client(1, "Guest Laptop", "10.0.50.23"),
    )

    # The real platform publishes the ip attribute the blueprint filters on.
    state = hass.states.get("device_tracker.guest_laptop")
    assert state is not None
    assert state.attributes["ip"] == "10.0.50.23"
    assert _data(calls) == [
        {
            "entity": "device_tracker.guest_laptop",
            "name": "Guest Laptop",
            "ip": "10.0.50.23",
        }
    ]


async def test_new_tracker_on_another_prefix_is_ignored(
    hass: HomeAssistant,
    blueprint_dir: Path,
    calls: list[ServiceCall],
    tracking_entry: MockConfigEntry,
    mock_network_client: MagicMock,
) -> None:
    """Clients outside the secure prefixes do not alert."""
    await _use_blueprint(hass, SECURE_VLAN, _vlan_inputs())

    await _connect(
        hass,
        tracking_entry,
        mock_network_client,
        _client(2, "Living Room TV", "192.168.1.40"),
        # 10.0.5. is a different network from 10.0.50.
        _client(3, "Printer", "10.0.5.12"),
    )

    assert hass.states.get("device_tracker.living_room_tv") is not None
    assert hass.states.get("device_tracker.printer") is not None
    assert calls == []


async def test_allowlisted_tracker_on_a_secure_prefix_is_excluded(
    hass: HomeAssistant,
    blueprint_dir: Path,
    calls: list[ServiceCall],
    tracking_entry: MockConfigEntry,
    mock_network_client: MagicMock,
) -> None:
    """A known device on the secure VLAN does not alert; a stranger still does."""
    await _use_blueprint(
        hass,
        SECURE_VLAN,
        _vlan_inputs(allowed_trackers=["device_tracker.alarm_panel"]),
    )

    await _connect(
        hass,
        tracking_entry,
        mock_network_client,
        _client(4, "Alarm Panel", "10.0.50.10"),
        _client(5, "Stranger Phone", "10.0.50.77"),
    )

    # Both trackers exist; the allowlisted entity id is the one that was created.
    assert hass.states.get("device_tracker.alarm_panel") is not None
    assert [call["entity"] for call in _data(calls)] == [
        "device_tracker.stranger_phone"
    ]


async def test_first_time_tracking_creates_many_trackers_and_each_secure_one_alerts(
    hass: HomeAssistant,
    blueprint_dir: Path,
    calls: list[ServiceCall],
    tracking_entry: MockConfigEntry,
    mock_network_client: MagicMock,
) -> None:
    """A burst of new trackers is processed completely, across several prefixes."""
    await _use_blueprint(
        hass,
        SECURE_VLAN,
        _vlan_inputs(secure_prefixes=["10.0.50.", "10.0.60."]),
    )
    clients = [
        _client(10 + n, f"Camera {n}", f"10.0.{50 if n % 2 else 60}.{n}")
        for n in range(1, 7)
    ] + [_client(30 + n, f"Laptop {n}", f"192.168.1.{n}") for n in range(1, 7)]

    await _connect(hass, tracking_entry, mock_network_client, *clients)

    assert sorted(call["name"] for call in _data(calls)) == [
        f"Camera {n}" for n in range(1, 7)
    ]
    assert sorted(call["ip"] for call in _data(calls)) == sorted(
        f"10.0.{50 if n % 2 else 60}.{n}" for n in range(1, 7)
    )


async def test_blank_secure_prefix_never_matches_every_client(
    hass: HomeAssistant,
    blueprint_dir: Path,
    calls: list[ServiceCall],
    tracking_entry: MockConfigEntry,
    mock_network_client: MagicMock,
) -> None:
    """An empty or whitespace prefix entry is ignored, not a wildcard."""
    await _use_blueprint(
        hass, SECURE_VLAN, _vlan_inputs(secure_prefixes=["", "  ", "10.0.50."])
    )

    await _connect(
        hass,
        tracking_entry,
        mock_network_client,
        _client(6, "Elsewhere", "192.168.9.9"),
    )
    assert calls == []

    await _connect(
        hass,
        tracking_entry,
        mock_network_client,
        _client(6, "Elsewhere", "192.168.9.9"),
        _client(7, "Inside", "10.0.50.9"),
    )
    assert [call["name"] for call in _data(calls)] == ["Inside"]


async def test_prefix_must_match_the_start_of_the_ip_address(
    hass: HomeAssistant,
    blueprint_dir: Path,
    calls: list[ServiceCall],
    tracking_entry: MockConfigEntry,
    mock_network_client: MagicMock,
) -> None:
    """``168.1.`` is inside 192.168.1.40 but is not its prefix."""
    await _use_blueprint(hass, SECURE_VLAN, _vlan_inputs(secure_prefixes=["168.1."]))

    await _connect(
        hass,
        tracking_entry,
        mock_network_client,
        _client(20, "Inside Only", "192.168.1.40"),
        _client(21, "Starts With", "168.1.2.3"),
    )

    assert [call["name"] for call in _data(calls)] == ["Starts With"]


async def test_new_secure_clients_that_connect_together_all_run_slow_actions(
    hass: HomeAssistant,
    *,
    freezer: FrozenDateTimeFactory,
    blueprint_dir: Path,
    calls: list[ServiceCall],
    tracking_entry: MockConfigEntry,
    mock_network_client: MagicMock,
) -> None:
    """Actions that take time must not make later new clients get dropped."""
    await _use_blueprint(
        hass,
        SECURE_VLAN,
        _vlan_inputs(actions=[{"delay": {"seconds": 5}}, *VLAN_ACTIONS]),
    )

    mock_network_client.clients.get_all.return_value = [
        _client(22, "First Camera", "10.0.50.22"),
        _client(23, "Second Camera", "10.0.50.23"),
    ]
    await tracking_entry.runtime_data.device_coordinator.async_refresh()
    # Parallel mode: both runs are alive at once, each parked on its slow action.
    await _wait_until(lambda: _active_runs(hass) == 2, "both runs to start")
    assert calls == []

    await _advance_until(
        hass, freezer, lambda: len(calls) >= 2, "both runs to record their call"
    )
    await hass.async_block_till_done()

    assert sorted(call["name"] for call in _data(calls)) == [
        "First Camera",
        "Second Camera",
    ]


async def test_single_octet_prefix_keeps_its_trailing_dot(
    hass: HomeAssistant,
    blueprint_dir: Path,
    calls: list[ServiceCall],
    tracking_entry: MockConfigEntry,
    mock_network_client: MagicMock,
) -> None:
    """``10.`` means the whole 10.x network, not the number 10.0 and not 100.x."""
    await _use_blueprint(hass, SECURE_VLAN, _vlan_inputs(secure_prefixes=["10."]))

    await _connect(
        hass,
        tracking_entry,
        mock_network_client,
        _client(8, "Inside Ten", "10.5.1.1"),
        _client(9, "Carrier Grade NAT", "100.64.0.9"),
    )

    assert [call["name"] for call in _data(calls)] == ["Inside Ten"]


class _UnifiSensorWithAnIp(SensorEntity):
    """A UniFi Insights sensor that carries an ``ip`` attribute like a tracker."""

    _attr_name = "Gateway Address"
    _attr_unique_id = "gateway-address"
    _attr_native_value = 1
    _attr_extra_state_attributes = {"ip": "10.0.50.1"}  # noqa: RUF012


async def test_a_new_entity_that_is_not_a_device_tracker_is_ignored(
    hass: HomeAssistant,
    blueprint_dir: Path,
    calls: list[ServiceCall],
    tracking_entry: MockConfigEntry,
) -> None:
    """Only ``device_tracker.`` entities count, even from UniFi Insights."""
    await _use_blueprint(hass, SECURE_VLAN, _vlan_inputs())

    platform = MockEntityPlatform(hass, domain="sensor", platform_name=DOMAIN)
    await platform.async_add_entities([_UnifiSensorWithAnIp()])
    await hass.async_block_till_done()

    state = hass.states.get("sensor.gateway_address")
    assert state is not None
    assert state.attributes["ip"] == "10.0.50.1"
    assert calls == []


class _OtherIntegrationTracker(ScannerEntity):
    """A tracker that belongs to another integration, inside the secure prefix."""

    _attr_name = "Other Integration Phone"
    _attr_ip_address = "10.0.50.99"
    _attr_source_type = SourceType.ROUTER

    @property
    def unique_id(self) -> str:
        """Return a unique id that does not depend on a MAC address."""
        return "other-integration-phone"

    @property
    def is_connected(self) -> bool:
        """Report the device as connected."""
        return True


async def test_a_secure_tracker_from_another_integration_is_ignored(
    hass: HomeAssistant,
    blueprint_dir: Path,
    calls: list[ServiceCall],
    tracking_entry: MockConfigEntry,
) -> None:
    """The IP match alone is not enough: the tracker must belong to UniFi Insights."""
    await _use_blueprint(hass, SECURE_VLAN, _vlan_inputs())

    platform = MockEntityPlatform(
        hass, domain="device_tracker", platform_name="other_integration"
    )
    await platform.async_add_entities([_OtherIntegrationTracker()])
    await hass.async_block_till_done()

    state = hass.states.get("device_tracker.other_integration_phone")
    assert state is not None
    assert state.attributes["ip"] == "10.0.50.99"
    assert calls == []


async def test_a_tracker_that_never_gets_a_state_is_dropped_after_the_timeout(
    hass: HomeAssistant,
    *,
    entity_registry: er.EntityRegistry,
    blueprint_dir: Path,
    calls: list[ServiceCall],
    tracking_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A registry entry without a state ends the run instead of hanging or alerting."""
    await _use_blueprint(hass, SECURE_VLAN, _vlan_inputs())

    entity_registry.async_get_or_create(
        "device_tracker",
        DOMAIN,
        f"{DOMAIN}_aa:bb:cc:dd:ee:99",
        config_entry=tracking_entry,
        suggested_object_id="stateless_client",
    )
    # The run is parked on the wait: do not block on it.
    await _wait_until(lambda: _active_runs(hass) == 1, "the run to wait for a state")

    await _advance_until(
        hass, freezer, lambda: _active_runs(hass) == 0, "the wait to time out"
    )
    await hass.async_block_till_done()

    assert calls == []
    assert _active_runs(hass) == 0
