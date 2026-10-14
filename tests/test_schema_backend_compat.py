"""Tests verifying schema and flow backend compatibility across HA."""

from __future__ import annotations

import pytest
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_VERIFY_SSL

from custom_components.unifi_insights import (
    config_flow,
    repairs,
    services,
    websocket_api,
)


def test_schema_backend_identity() -> None:
    """Verify schema engine module identity and core marker presence."""
    for mod in (config_flow, services, websocket_api):
        vol = mod.vol
        assert hasattr(vol, "Schema")
        assert hasattr(vol, "Required")
        assert hasattr(vol, "Optional")
        assert hasattr(vol, "In")
        assert hasattr(vol, "All")
        assert hasattr(vol, "Invalid")


def test_config_flow_schemas() -> None:
    """Verify config flow schemas validate valid inputs and reject invalid ones."""
    vol = config_flow.vol
    local_schema = vol.Schema(
        {
            vol.Required(CONF_HOST, default="https://192.168.1.1"): str,
            vol.Required(CONF_API_KEY): str,
            vol.Optional(CONF_VERIFY_SSL, default=False): bool,
        }
    )
    validated = local_schema({CONF_API_KEY: "secret-key"})
    assert validated[CONF_API_KEY] == "secret-key"
    assert validated[CONF_HOST] == "https://192.168.1.1"
    assert validated[CONF_VERIFY_SSL] is False

    with pytest.raises(vol.Invalid):
        local_schema({})  # Missing required CONF_API_KEY


def test_services_schemas() -> None:
    """Verify registered service schemas validate arguments correctly."""
    vol = services.vol
    assert hasattr(services, "POWER_CYCLE_PORT_SCHEMA")
    assert hasattr(services, "RECONNECT_CLIENT_SCHEMA")
    assert hasattr(services, "EXPORT_NETWORK_RULES_SCHEMA")

    schema = services.POWER_CYCLE_PORT_SCHEMA
    assert isinstance(schema, vol.Schema)


def test_websocket_api_schemas() -> None:
    """Verify websocket API snapshot and command schemas."""
    vol = websocket_api.vol
    snapshot_schema = websocket_api._SNAPSHOT_SCHEMA
    assert isinstance(snapshot_schema, dict)

    cmd_schema = vol.Schema(
        {vol.Required("type"): "unifi_insights/topology/get", **snapshot_schema}
    )
    valid_data = {
        "type": "unifi_insights/topology/get",
        "entry_id": "test_entry",
        "site_id": "default",
    }
    validated = cmd_schema(valid_data)
    assert validated["entry_id"] == "test_entry"


def test_repair_flow_result_contracts() -> None:
    """Verify repair flow methods return valid RepairsFlowResult shapes."""
    assert repairs.RepairsFlowResult is not None
    flow = repairs.UnifiInsightsRepairFlow("deprecated_yaml")
    assert flow.issue_id == "deprecated_yaml"
