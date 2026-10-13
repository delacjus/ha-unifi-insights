"""Tests for the export_network_rules action and its builder."""

from __future__ import annotations

import copy
import json
import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant.components.diagnostics.const import REDACTED
from homeassistant.core import Context, SupportsResponse
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
)

from custom_components.unifi_insights.api import (
    UniFiAuthenticationError,
    UniFiConnectionError,
    UniFiNotFoundError,
)
from custom_components.unifi_insights.api.network.models import (
    FirewallRule,
    NatRule,
    PolicyBasedRoute,
    PortForward,
    StaticRoute,
    TrafficRule,
)
from custom_components.unifi_insights.const import (
    DOMAIN,
    SERVICE_EXPORT_NETWORK_RULES,
)
from custom_components.unifi_insights.coordinators.base import UnifiBaseCoordinator
from custom_components.unifi_insights.coordinators.rule_audit import RULE_TYPES
from custom_components.unifi_insights.coordinators.rule_export import (
    async_build_rule_export,
)
from custom_components.unifi_insights.diagnostics import redact_network_rule_export
from custom_components.unifi_insights.services import (
    async_setup_services,
    async_unload_services,
)
from tests.fixtures.network_rule_responses import (
    nat_rule_record,
    port_forward_record,
    static_route_record,
    traffic_rule_record,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry

_SITES: dict[str, Any] = {
    "site1": {"id": "site1", "name": "Home", "internalReference": "default"},
    "site2": {"id": "site2", "name": "Lab"},
}
_CONSOLE: dict[str, Any] = {"entry_id": "e1", "title": "UDM"}

# rule type -> (client attribute, list method)
_LISTERS: dict[str, tuple[str, str]] = {
    "firewall_rule": ("firewall", "list_rules"),
    "policy_based_route": ("routes", "list_routes"),
    "port_forward": ("port_forwards", "list_port_forwards"),
    "traffic_rule": ("traffic_rules", "list_traffic_rules"),
    "nat_rule": ("nat_rules", "list_nat_rules"),
    "static_route": ("static_routes", "list_static_routes"),
}


def _client(**results: Any) -> MagicMock:
    """Return a client whose six list methods return or raise per rule type."""
    client = MagicMock()
    for rule_type, (attribute, method) in _LISTERS.items():
        result = results.get(rule_type, [])
        if isinstance(result, Exception):
            lister = AsyncMock(side_effect=result)
        else:
            lister = AsyncMock(return_value=result)
        setattr(getattr(client, attribute), method, lister)
    return client


def _lister(client: MagicMock, rule_type: str) -> AsyncMock:
    attribute, method = _LISTERS[rule_type]
    lister: AsyncMock = getattr(getattr(client, attribute), method)
    return lister


async def _build(client: MagicMock, **kwargs: Any) -> dict[str, Any]:
    options: dict[str, Any] = {"site_ids": None, "rule_types": None}
    options.update(kwargs)
    return await async_build_rule_export(
        client,
        _SITES,
        console=_CONSOLE,
        is_unsupported=UnifiBaseCoordinator._is_unsupported_response,
        **options,
    )


def _entry(title: str, coordinator: MagicMock, sites: dict[str, Any]) -> MagicMock:
    coordinator.data = {"sites": sites}
    return MagicMock(
        entry_id=f"id-{title}",
        title=title,
        runtime_data=MagicMock(coordinator=coordinator),
    )


def _doc() -> dict[str, Any]:
    """Return a one-site, one-port-forward raw document."""
    return {
        "format_version": 1,
        "generated_at": "2026-01-02T03:04:05+00:00",
        "redacted": False,
        "console": _CONSOLE,
        "sites": {
            "site1": {
                "name": "Home",
                "rule_types": {
                    "port_forward": {
                        "status": "ok",
                        "count": 1,
                        "rules": [port_forward_record(fwd="192.0.2.50")],
                    }
                },
            }
        },
    }


async def _call(
    hass: HomeAssistant, entries: list[MagicMock], data: dict[str, Any], **kw: Any
) -> Any:
    await async_setup_services(hass)
    try:
        with patch.object(hass.config_entries, "async_entries", return_value=entries):
            return await hass.services.async_call(
                DOMAIN,
                SERVICE_EXPORT_NETWORK_RULES,
                data,
                blocking=True,
                return_response=True,
                **kw,
            )
    finally:
        await async_unload_services(hass)


# One record per family, each with sensitive values in nested positions. Every
# address is from an RFC 5737 documentation range, every name ends in .example.
_SENSITIVE: dict[str, tuple[str, ...]] = {
    "firewall_rule": (
        "198.51.100.7",
        "203.0.113.10",
        "aa:bb:cc:dd:ee:10",
        "fw-blocked.example",
        "::2a:3b:4c:5d",
    ),
    "policy_based_route": (
        "pbr-routed.example",
        "198.51.100.20",
        "198.51.100.30",
        "203.0.113.1",
        "203.0.113.21",
        "aa:bb:cc:dd:ee:20",
    ),
    "port_forward": ("192.0.2.50", "198.51.100.0/24", "203.0.113.7", "203.0.113.8"),
    "traffic_rule": (
        "tr-blocked.example",
        "198.51.100.101",
        "198.51.100.110",
        "203.0.113.9",
        "aa:bb:cc:dd:ee:30",
    ),
    "nat_rule": ("192.0.2.53", "192.0.2.54", "198.51.100.44"),
    "static_route": (
        "198.51.100.128/25",
        "192.0.2.1",
        "198.51.100.77",
        "aa:bb:cc:dd:ee:40",
    ),
}
# Values the redaction must leave alone: a document without names or ports is
# of no use for an audit.
_KEPT = ("Block cams", "VPN out", "Plex", "Bedtime", "All DNS to resolver")


def _six_models() -> dict[str, Any]:
    """Return one parsed rule of every family, as the endpoints return them."""
    return {
        "firewall_rule": FirewallRule.model_validate(
            {
                "id": "fw1",
                "name": "Block cams",
                "sourceAddress": "203.0.113.10",
                "source": {
                    "trafficFilter": {
                        "type": "IP_ADDRESS",
                        "ipAddressFilter": {
                            "type": "IP_ADDRESSES",
                            "items": [{"type": "IP_ADDRESS", "value": "198.51.100.7"}],
                        },
                        "macAddressFilter": {"macAddresses": ["aa:bb:cc:dd:ee:10"]},
                    }
                },
                "destination": {
                    "trafficFilter": {
                        "domainFilter": {"domains": ["fw-blocked.example"]},
                        "ipv6IidFilter": {"items": [{"value": "::2a:3b:4c:5d"}]},
                        "portFilter": {"items": [{"value": 443}]},
                    }
                },
            }
        ),
        "policy_based_route": PolicyBasedRoute.model_validate(
            {
                "_id": "pbr1",
                "description": "VPN out",
                "domains": [{"domain": "pbr-routed.example"}],
                "ipRanges": [{"ip_start": "198.51.100.20", "ip_stop": "198.51.100.30"}],
                "nextHop": "203.0.113.1",
                "ips": ["203.0.113.21"],
                "targetDevices": [{"type": "CLIENT", "clientMac": "aa:bb:cc:dd:ee:20"}],
            }
        ),
        "port_forward": PortForward.model_validate(
            port_forward_record(
                fwd="192.0.2.50",
                destination_ips=["203.0.113.8"],
            )
        ),
        "traffic_rule": TrafficRule.model_validate(
            traffic_rule_record(
                domains=["tr-blocked.example"],
                ip_addresses=[
                    {
                        "ip_or_subnet": "203.0.113.9/32",
                        "ip_version": "v4",
                        "port_ranges": [],
                        "ports": [],
                    }
                ],
                ip_ranges=[
                    {
                        "ip_start": "198.51.100.101",
                        "ip_stop": "198.51.100.110",
                        "ip_version": "v4",
                    }
                ],
                target_devices=[{"client_mac": "aa:bb:cc:dd:ee:30", "type": "CLIENT"}],
            )
        ),
        "nat_rule": NatRule.model_validate(
            nat_rule_record(
                source_filter={
                    "filter_type": "ADDRESS_AND_PORT",
                    "firewall_group_ids": [],
                    "invert_address": False,
                    "invert_port": False,
                    "address": "198.51.100.44",
                    "port": "1024",
                }
            )
        ),
        "static_route": StaticRoute.model_validate(
            static_route_record(
                **{
                    "static-route_network": "198.51.100.128/25",
                    "static-route_nexthop": "192.0.2.1",
                    # A nested copy, so the key-based redaction is proven to
                    # recurse into this family too.
                    "hops": [{"static-route_nexthop": "198.51.100.77"}],
                    "gateway_device": "aa:bb:cc:dd:ee:40",
                }
            )
        ),
    }


def _dump(model: Any) -> dict[str, Any]:
    dumped: dict[str, Any] = model.model_dump(mode="json", by_alias=True)
    return dumped


def _six_family_document() -> dict[str, Any]:
    """Return a raw export document holding the six sensitive records."""
    return {
        "format_version": 1,
        "generated_at": "2026-01-02T03:04:05+00:00",
        "redacted": False,
        "console": _CONSOLE,
        "sites": {
            "site1": {
                "name": "Home",
                "rule_types": {
                    rule_type: {
                        "status": "ok",
                        "count": 1,
                        "rules": [_dump(model)],
                    }
                    for rule_type, model in _six_models().items()
                },
            }
        },
    }


def _assert_absent(dumped: str, literals: tuple[str, ...]) -> None:
    for literal in literals:
        assert literal not in dumped, f"{literal} leaked"


async def test_export_document_shape_and_fresh_fetch(freezer: Any) -> None:
    """The document is versioned, JSON-safe and read from the console now."""
    freezer.move_to("2026-01-02 03:04:05+00:00")
    client = _client(port_forward=[PortForward.model_validate(port_forward_record())])

    document = await _build(client)

    assert document["format_version"] == 1
    assert document["generated_at"] == "2026-01-02T03:04:05+00:00"
    assert document["redacted"] is False
    assert document["console"] == _CONSOLE
    assert list(document["sites"]) == ["site1", "site2"]
    site1 = document["sites"]["site1"]
    assert site1["name"] == "Home"
    assert tuple(site1["rule_types"]) == RULE_TYPES
    assert site1["rule_types"]["port_forward"] == {
        "status": "ok",
        "count": 1,
        "rules": [port_forward_record()],
    }
    _lister(client, "firewall_rule").assert_any_await("site1")
    _lister(client, "port_forward").assert_awaited_once_with("default")
    assert json.dumps(document)


async def test_export_record_passes_plain_dicts_through() -> None:
    """A lister that returns plain dicts is exported unchanged."""
    record = {"_id": "x", "name": "Plain"}
    document = await _build(_client(port_forward=[record]))

    assert document["sites"]["site1"]["rule_types"]["port_forward"]["rules"] == [record]


async def test_site_without_classic_name_is_unsupported_for_classic_families() -> None:
    """Without an internalReference only the official firewall API can be read."""
    client = _client()

    document = await _build(client, site_ids=["site2"])

    types = document["sites"]["site2"]["rule_types"]
    assert types["firewall_rule"]["status"] == "ok"
    for rule_type in RULE_TYPES[1:]:
        assert types[rule_type] == {"status": "unsupported", "count": 0, "rules": []}
        _lister(client, rule_type).assert_not_awaited()
    _lister(client, "firewall_rule").assert_awaited_once_with("site2")


async def test_family_status_unsupported_and_failed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A family that cannot be read says so; the others are still exported."""
    caplog.set_level(logging.DEBUG)
    client = _client(
        nat_rule=UniFiNotFoundError("nope", status_code=404),
        static_route=UniFiConnectionError("secret-host 192.0.2.99"),
        traffic_rule=UniFiAuthenticationError("bad key 192.0.2.98", status_code=401),
        port_forward=[PortForward.model_validate(port_forward_record())],
    )

    document = await _build(client, site_ids=["site1"])

    types = document["sites"]["site1"]["rule_types"]
    assert types["nat_rule"] == {"status": "unsupported", "count": 0, "rules": []}
    assert types["static_route"] == {"status": "failed", "count": 0, "rules": []}
    assert types["traffic_rule"] == {"status": "failed", "count": 0, "rules": []}
    assert types["port_forward"]["status"] == "ok"
    assert types["port_forward"]["count"] == 1
    dumped = json.dumps(document)
    for text in (dumped, caplog.text):
        assert "192.0.2.99" not in text
        assert "192.0.2.98" not in text
        assert "secret-host" not in text
    assert "UniFiConnectionError" in caplog.text
    assert "UniFiAuthenticationError" in caplog.text


async def test_rule_types_filter() -> None:
    """Only the requested families are fetched and reported."""
    client = _client()

    document = await _build(client, rule_types=["nat_rule"], site_ids=["site1"])

    assert list(document["sites"]["site1"]["rule_types"]) == ["nat_rule"]
    _lister(client, "nat_rule").assert_awaited_once_with("default")
    for rule_type in RULE_TYPES:
        if rule_type != "nat_rule":
            _lister(client, rule_type).assert_not_awaited()


async def test_every_fetch_failed_raises() -> None:
    """When nothing could be read at all, the export is an error."""
    client = _client(
        **{rule_type: UniFiConnectionError("x") for rule_type in RULE_TYPES}
    )

    with pytest.raises(HomeAssistantError) as err:
        await _build(client, site_ids=["site1"])

    assert err.value.translation_key == "export_network_rules_failed"


async def test_one_failed_family_does_not_fail_the_export() -> None:
    """A single failing family is a status, not an error."""
    client = _client(nat_rule=UniFiConnectionError("x"))

    document = await _build(client, site_ids=["site1"])

    types = document["sites"]["site1"]["rule_types"]
    assert types["nat_rule"]["status"] == "failed"
    assert types["firewall_rule"]["status"] == "ok"


async def test_no_matching_site_returns_empty_sites() -> None:
    """An unknown site id selects nothing and fetches nothing."""
    client = _client()

    document = await _build(client, site_ids=["nope"])

    assert document["sites"] == {}
    for rule_type in RULE_TYPES:
        _lister(client, rule_type).assert_not_awaited()


def test_redaction_uses_diagnostics_key_sets() -> None:
    """Every family is redacted, nested filters included, and nothing else is."""
    document = _six_family_document()
    original = copy.deepcopy(document)
    raw_dump = json.dumps(document)
    # The literals are really in the raw document, so their absence below is
    # the redaction's doing.
    for literals in _SENSITIVE.values():
        for literal in literals:
            assert literal in raw_dump, f"{literal} missing from the raw fixture"

    redacted = redact_network_rule_export(document)

    dumped = json.dumps(redacted)
    for literals in _SENSITIVE.values():
        _assert_absent(dumped, literals)
    for kept in _KEPT:
        assert kept in dumped
    assert '"port": "53"' in dumped
    assert '"_id": "pf-plex"' in dumped
    assert '"value": 443' in dumped
    assert redacted["redacted"] is True
    assert document == original
    # The filter objects of a firewall policy go as a whole, not value by value.
    firewall = redacted["sites"]["site1"]["rule_types"]["firewall_rule"]["rules"][0]
    assert firewall["source"]["trafficFilter"]["ipAddressFilter"] == REDACTED
    assert firewall["source"]["trafficFilter"]["macAddressFilter"] == REDACTED
    assert firewall["destination"]["trafficFilter"]["domainFilter"] == REDACTED
    assert firewall["destination"]["trafficFilter"]["ipv6IidFilter"] == REDACTED


def test_redaction_covers_every_rule_family() -> None:
    """The redaction fixture has a sensitive record for each exported family."""
    assert set(_SENSITIVE) == set(RULE_TYPES)
    assert set(_six_models()) == set(RULE_TYPES)


async def test_service_redacts_by_default(hass: HomeAssistant) -> None:
    """Without arguments the response is redacted and targets the only console."""
    coordinator = MagicMock()
    coordinator.async_export_network_rules = AsyncMock(return_value=_doc())

    response = await _call(hass, [_entry("UDM", coordinator, _SITES)], {})

    coordinator.async_export_network_rules.assert_awaited_once_with(None, None)
    assert response["redacted"] is True
    assert "192.0.2.50" not in json.dumps(response)


async def test_service_raw_export_and_arguments(hass: HomeAssistant) -> None:
    """redact false returns the records unchanged; arguments reach the facade."""
    coordinator = MagicMock()
    coordinator.async_export_network_rules = AsyncMock(return_value=_doc())

    response = await _call(
        hass,
        [_entry("UDM", coordinator, _SITES)],
        {"site_id": "site1", "rule_types": "port_forward", "redact": False},
    )

    coordinator.async_export_network_rules.assert_awaited_once_with(
        ["site1"], ["port_forward"]
    )
    assert response == _doc()


async def test_service_exports_all_six_families_end_to_end(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    freezer: Any,
) -> None:
    """Through the real builder and service: redacted by default, raw on request."""
    freezer.move_to("2026-01-02 03:04:05+00:00")
    caplog.set_level(logging.DEBUG)
    models = _six_models()
    client = _client(**{rule_type: [model] for rule_type, model in models.items()})

    async def export(
        site_ids: list[str] | None, rule_types: list[str] | None
    ) -> dict[str, Any]:
        return await async_build_rule_export(
            client,
            _SITES,
            console=_CONSOLE,
            site_ids=site_ids,
            rule_types=rule_types,
            is_unsupported=UnifiBaseCoordinator._is_unsupported_response,
        )

    coordinator = MagicMock()
    coordinator.async_export_network_rules = AsyncMock(side_effect=export)
    entries = [_entry("UDM", coordinator, _SITES)]
    every_literal = tuple(
        literal for literals in _SENSITIVE.values() for literal in literals
    )

    redacted = await _call(hass, entries, {"site_id": "site1"})
    raw = await _call(hass, entries, {"site_id": "site1", "redact": False})

    redacted_dump = json.dumps(redacted)
    _assert_absent(redacted_dump, every_literal)
    assert redacted["redacted"] is True
    assert redacted["generated_at"] == "2026-01-02T03:04:05+00:00"
    for kept in _KEPT:
        assert kept in redacted_dump
    raw_types = raw["sites"]["site1"]["rule_types"]
    assert raw["redacted"] is False
    assert {rule_type: raw_types[rule_type]["rules"] for rule_type in RULE_TYPES} == {
        rule_type: [_dump(model)] for rule_type, model in models.items()
    }
    raw_dump = json.dumps(raw)
    for literal in every_literal:
        assert literal in raw_dump
    # Neither mode writes a rule value or a credential to the log, and the
    # document carries no secret.
    for literal in every_literal:
        assert literal not in caplog.text
    for text in (redacted_dump, raw_dump):
        assert "api_key" not in text.lower()
    assert redacted["console"] == _CONSOLE


async def test_service_requires_response(hass: HomeAssistant) -> None:
    """Calling the action without return_response is rejected."""
    await async_setup_services(hass)
    try:
        with pytest.raises(ServiceValidationError) as err:
            await hass.services.async_call(
                DOMAIN, SERVICE_EXPORT_NETWORK_RULES, {}, blocking=True
            )
        assert err.value.translation_key == "service_lacks_response_request"
        assert hass.services.has_service(DOMAIN, SERVICE_EXPORT_NETWORK_RULES)
    finally:
        await async_unload_services(hass)
    assert not hass.services.has_service(DOMAIN, SERVICE_EXPORT_NETWORK_RULES)


async def test_service_rejects_non_admin(hass: HomeAssistant) -> None:
    """A non-admin user cannot export the rules, even with a response request."""
    coordinator = MagicMock()
    coordinator.async_export_network_rules = AsyncMock(return_value=_doc())
    user = await hass.auth.async_create_user("non_admin_user")
    user.is_owner = False
    user.groups = []
    user.invalidate_cache()

    with pytest.raises(Unauthorized):
        await _call(
            hass,
            [_entry("UDM", coordinator, _SITES)],
            {},
            context=Context(user_id=user.id),
        )

    coordinator.async_export_network_rules.assert_not_awaited()


@pytest.mark.parametrize(
    "data",
    [{"rule_types": ["vpn_client"]}, {"unknown": 1}, {"redact": "maybe"}],
)
async def test_service_rejects_bad_input(
    hass: HomeAssistant, data: dict[str, Any]
) -> None:
    """Unknown rule types, unknown fields and non-boolean redact are invalid."""
    coordinator = MagicMock()
    coordinator.async_export_network_rules = AsyncMock(return_value=_doc())

    with pytest.raises(vol.Invalid):
        await _call(hass, [_entry("UDM", coordinator, _SITES)], data)

    coordinator.async_export_network_rules.assert_not_awaited()


async def test_service_console_selection(hass: HomeAssistant) -> None:
    """The console comes from console_id, the site, or the only one configured."""
    first = MagicMock()
    first.async_export_network_rules = AsyncMock(return_value=_doc())
    second = MagicMock()
    second.async_export_network_rules = AsyncMock(return_value=_doc())
    entries = [
        _entry("UDM", first, {"site1": {"id": "site1"}}),
        _entry("Cabin", second, {"site9": {"id": "site9"}}),
    ]

    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, entries, {})
    assert err.value.translation_key == "export_console_required"
    first.async_export_network_rules.assert_not_awaited()
    second.async_export_network_rules.assert_not_awaited()

    await _call(hass, entries, {"console_id": "cabin"})
    second.async_export_network_rules.assert_awaited_once_with(None, None)
    first.async_export_network_rules.assert_not_awaited()

    await _call(hass, entries, {"site_id": "site1"})
    first.async_export_network_rules.assert_awaited_once_with(["site1"], None)

    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, entries, {"console_id": "Cabin", "site_id": "site1"})
    assert err.value.translation_key == "export_site_not_on_console"
    assert err.value.translation_placeholders == {
        "site_id": "site1",
        "console": "Cabin",
    }

    with pytest.raises(ServiceValidationError, match="No configured"):
        await _call(hass, entries, {"console_id": "nope"})


async def test_service_without_console_or_sites(hass: HomeAssistant) -> None:
    """No console, or a console without a Network site, is a validation error."""
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, [], {})
    assert err.value.translation_key == "no_network_console"

    coordinator = MagicMock()
    coordinator.async_export_network_rules = AsyncMock(
        return_value={**_doc(), "sites": {}}
    )
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, [_entry("UDM", coordinator, {})], {})
    assert err.value.translation_key == "export_no_sites"


async def test_service_registered_by_integration_setup(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    enable_custom_integrations: None,
) -> None:
    """The action exists once the integration is set up (async_setup path)."""
    assert hass.services.has_service(DOMAIN, SERVICE_EXPORT_NETWORK_RULES)
    assert (
        hass.services.supports_response(DOMAIN, SERVICE_EXPORT_NETWORK_RULES)
        is SupportsResponse.ONLY
    )
