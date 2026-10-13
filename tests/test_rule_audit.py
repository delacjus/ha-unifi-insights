"""Tests for rule change detection in the UniFi Insights config coordinator."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from custom_components.unifi_insights.coordinators.rule_audit import (
    RULE_CHANGE_BUFFER_SIZE,
    RULE_FAMILIES,
    RULE_TYPES,
    RuleAuditTracker,
    RuleFamily,
)

_ALL_OK = {(family.data_key, "s1"): "ok" for family in RULE_FAMILIES}


def _data(**sections: Any) -> dict[str, Any]:
    """Build coordinator data for site s1 with empty sections by default."""
    base: dict[str, Any] = {
        "sites": {"s1": {"id": "s1"}},
    }
    for family in RULE_FAMILIES:
        base[family.data_key] = {"s1": {}}
    base.update(sections)
    return base


def test_rule_types_cover_the_six_families() -> None:
    """The six audited rule families are registered in order."""
    assert RULE_TYPES == (
        "firewall_rule",
        "policy_based_route",
        "port_forward",
        "traffic_rule",
        "nat_rule",
        "static_route",
    )


def test_first_snapshot_is_a_silent_baseline() -> None:
    """The first refresh with successful fetch establishes baseline silently."""
    tracker = RuleAuditTracker()
    data = _data(
        firewall_rules={"s1": {"r1": {"id": "r1", "name": "R1", "enabled": True}}}
    )
    assert tracker.process(data, _ALL_OK) == {}


def test_unchanged_refresh_reports_nothing() -> None:
    """Subsequent refreshes with unchanged rules produce no change records."""
    tracker = RuleAuditTracker()
    data = _data(
        firewall_rules={"s1": {"r1": {"id": "r1", "name": "R1", "enabled": True}}}
    )
    tracker.process(data, _ALL_OK)
    assert tracker.process(data, _ALL_OK) == {}


@pytest.mark.parametrize("family", RULE_FAMILIES, ids=lambda f: f.rule_type)
def test_added_modified_deleted_for_each_family(family: RuleFamily) -> None:
    """Add, modify, and delete events are detected and sequenced for each family."""
    tracker = RuleAuditTracker()
    name_field = family.name_fields[0]
    rule_keep = {name_field: "Keep", "enabled": True, "action": "allow"}
    data1 = _data(**{family.data_key: {"s1": {"keep": rule_keep}}})
    tracker.process(data1, _ALL_OK)

    rule_keep_modified = {name_field: "Keep", "enabled": False, "action": "allow"}
    rule_new = {name_field: "New", "enabled": True, "action": "drop"}
    data2 = _data(
        **{family.data_key: {"s1": {"keep": rule_keep_modified, "new": rule_new}}}
    )
    changes = tracker.process(data2, _ALL_OK)

    assert [
        (c["change_type"], c["rule_type"], c["rule_id"]) for c in changes["s1"]
    ] == [
        ("added", family.rule_type, "new"),
        ("modified", family.rule_type, "keep"),
    ]
    mod_change = changes["s1"][1]
    assert mod_change["changed_fields"] == ["enabled"]
    assert mod_change["enabled"] is False
    assert mod_change["rule_name"] == "Keep"
    assert [c["sequence"] for c in changes["s1"]] == [1, 2]

    data3 = _data(**{family.data_key: {"s1": {}}})
    changes3 = tracker.process(data3, _ALL_OK)
    assert [c["change_type"] for c in changes3["s1"][-2:]] == ["deleted", "deleted"]
    assert changes3["s1"][-1]["sequence"] == 4


@pytest.mark.parametrize("outcome", ["unsupported", "failed", None])
def test_non_authoritative_fetch_keeps_baseline_and_reports_nothing(
    outcome: str | None,
) -> None:
    """Non-authoritative fetches keep the existing baseline and report nothing."""
    tracker = RuleAuditTracker()
    rule = {"name": "R1", "description": "R1", "enabled": True}
    data1 = _data(firewall_rules={"s1": {"r1": rule}})
    tracker.process(data1, _ALL_OK)

    if outcome is None:
        outcomes = {k: v for k, v in _ALL_OK.items() if k != ("firewall_rules", "s1")}
    else:
        outcomes = {**_ALL_OK, ("firewall_rules", "s1"): outcome}

    data_empty = _data(firewall_rules={"s1": {}})
    assert tracker.process(data_empty, outcomes) == {}

    # The same rules returning with ok report nothing because baseline was preserved
    assert tracker.process(data1, _ALL_OK) == {}


def test_section_first_seen_after_unsupported_is_a_silent_baseline() -> None:
    """A section first seen after unsupported establishes a silent baseline."""
    tracker = RuleAuditTracker()
    outcomes_unsupported = {**_ALL_OK, ("firewall_rules", "s1"): "unsupported"}
    tracker.process(_data(), outcomes_unsupported)

    data = _data(firewall_rules={"s1": {"r1": {"name": "R1", "enabled": True}}})
    assert tracker.process(data, _ALL_OK) == {}


def test_order_only_change_reports_nothing() -> None:
    """Volatile order keys (index, rule_index, metadata) do not trigger changes."""
    tracker = RuleAuditTracker()
    data1 = _data(
        firewall_rules={
            "s1": {
                "fw1": {
                    "name": "FW1",
                    "enabled": True,
                    "index": 1,
                    "metadata": {"origin": "USER"},
                }
            }
        },
        nat_rules={
            "s1": {
                "nat1": {
                    "description": "NAT1",
                    "enabled": True,
                    "rule_index": 1,
                    "setting_preference": "manual",
                }
            }
        },
    )
    tracker.process(data1, _ALL_OK)

    data2 = _data(
        firewall_rules={
            "s1": {
                "fw1": {
                    "name": "FW1",
                    "enabled": True,
                    "index": 2,
                    "metadata": {"origin": "MODIFIED"},
                }
            }
        },
        nat_rules={
            "s1": {
                "nat1": {
                    "description": "NAT1",
                    "enabled": True,
                    "rule_index": 2,
                    "setting_preference": "manual",
                }
            }
        },
    )
    assert tracker.process(data2, _ALL_OK) == {}


def test_predefined_rules_are_not_audited() -> None:
    """System-defined firewall and auto/predefined NAT rules are excluded from audit."""
    tracker = RuleAuditTracker()
    tracker.process(_data(), _ALL_OK)

    data = _data(
        firewall_rules={
            "s1": {
                "sys_fw": {
                    "name": "Sys",
                    "enabled": True,
                    "metadata": {"origin": "SYSTEM_DEFINED"},
                },
                "user_fw": {"name": "User FW", "enabled": True},
            }
        },
        nat_rules={
            "s1": {
                "pre_nat": {
                    "description": "Pre NAT",
                    "enabled": True,
                    "is_predefined": True,
                },
                "auto_nat": {
                    "description": "Auto NAT",
                    "enabled": True,
                    "setting_preference": "auto",
                },
                "manual_nat": {
                    "description": "Manual NAT",
                    "enabled": True,
                    "setting_preference": "manual",
                },
            }
        },
    )
    changes = tracker.process(data, _ALL_OK)
    added_ids = {c["rule_id"] for c in changes["s1"]}
    assert added_ids == {"user_fw", "manual_nat"}
    assert all(c["change_type"] == "added" for c in changes["s1"])


def test_baseline_is_not_aliased_to_coordinator_data() -> None:
    """Mutating coordinator data in place does not alter tracker baseline snapshots."""
    tracker = RuleAuditTracker()
    record = {"name": "R1", "enabled": True, "nested": ["a"]}
    data1 = _data(firewall_rules={"s1": {"r1": record}})
    tracker.process(data1, _ALL_OK)

    record["enabled"] = False
    record["nested"].append("b")
    changes = tracker.process(data1, _ALL_OK)
    assert changes["s1"][0]["changed_fields"] == ["enabled", "nested"]


def test_change_records_hold_names_never_values() -> None:
    """Change records contain metadata and field names, never field values."""
    tracker = RuleAuditTracker()
    record1 = {
        "name": "R1",
        "enabled": True,
        "src": "192.0.2.53",
        "dst": "198.51.100.0/24",
        "domain": "blocked.example",
        "gw": "10.9.9.9",
    }
    tracker.process(_data(firewall_rules={"s1": {"r1": record1}}), _ALL_OK)

    record2 = {
        "name": "R1",
        "enabled": False,
        "src": "192.0.2.54",
        "dst": "198.51.100.0/25",
        "domain": "other.example",
        "gw": "10.9.9.8",
    }
    changes = tracker.process(_data(firewall_rules={"s1": {"r1": record2}}), _ALL_OK)
    c = changes["s1"][0]
    expected_keys = {
        "change_type",
        "site_id",
        "rule_type",
        "rule_id",
        "rule_name",
        "enabled",
        "changed_fields",
        "sequence",
    }
    assert set(c.keys()) == expected_keys
    assert c["changed_fields"] == sorted(["domain", "dst", "enabled", "gw", "src"])
    dumped = json.dumps(changes)
    for forbidden in ("192.0.2.53", "198.51.100.0/24", "blocked.example", "10.9.9.9"):
        assert forbidden not in dumped


def test_removed_site_drops_baseline_and_changes() -> None:
    """When a site is removed, its baseline and changes are purged; return is silent."""
    tracker = RuleAuditTracker()
    data = _data(firewall_rules={"s1": {"r1": {"name": "R1", "enabled": True}}})
    tracker.process(data, _ALL_OK)

    data2 = _data(firewall_rules={"s1": {"r1": {"name": "R1", "enabled": False}}})
    tracker.process(data2, _ALL_OK)
    assert "s1" in tracker.process(data2, _ALL_OK)

    res_removed = tracker.process({"sites": {}}, {})
    assert res_removed == {}

    res_returned = tracker.process(data, _ALL_OK)
    assert res_returned == {}


def test_sites_are_tracked_independently() -> None:
    """Different sites are diffed independently."""
    tracker = RuleAuditTracker()
    data1 = {
        "sites": {"s1": {"id": "s1"}, "s2": {"id": "s2"}},
        "firewall_rules": {
            "s1": {"r1": {"name": "R1", "enabled": True}},
            "s2": {"r2": {"name": "R2", "enabled": True}},
        },
    }
    outcomes1 = {
        ("firewall_rules", "s1"): "ok",
        ("firewall_rules", "s2"): "ok",
    }
    tracker.process(data1, outcomes1)

    data2 = {
        "sites": {"s1": {"id": "s1"}, "s2": {"id": "s2"}},
        "firewall_rules": {
            "s1": {},
            "s2": {},
        },
    }
    outcomes2 = {
        ("firewall_rules", "s1"): "failed",
        ("firewall_rules", "s2"): "ok",
    }
    res = tracker.process(data2, outcomes2)
    assert list(res.keys()) == ["s2"]
    assert res["s2"][0]["site_id"] == "s2"
    assert res["s2"][0]["change_type"] == "deleted"


def test_buffer_is_bounded_and_overflow_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When changes exceed buffer size, oldest are dropped and a warning is logged."""
    tracker = RuleAuditTracker()
    tracker.process(_data(), _ALL_OK)

    added_rules = {
        f"r_{i}": {"name": f"Rule {i}", "enabled": True}
        for i in range(RULE_CHANGE_BUFFER_SIZE + 5)
    }
    with caplog.at_level(logging.WARNING):
        res = tracker.process(_data(firewall_rules={"s1": added_rules}), _ALL_OK)

    assert len(res["s1"]) == RULE_CHANGE_BUFFER_SIZE
    assert res["s1"][-1]["sequence"] == RULE_CHANGE_BUFFER_SIZE + 5
    assert any("only the newest" in record.message for record in caplog.records)
    assert not any("Rule 0" in record.message for record in caplog.records)


@pytest.mark.parametrize(
    "malformed",
    [
        {},
        {"sites": None},
        {"sites": {"s1": {"id": "s1"}}, "firewall_rules": None},
        {"sites": {"s1": {"id": "s1"}}, "firewall_rules": {"s1": None}},
        {"sites": {"s1": {"id": "s1"}}, "firewall_rules": {"s1": {"r1": "x"}}},
        {"sites": {"s1": {"id": "s1"}}, "firewall_rules": {"s1": {7: {"name": "R"}}}},
    ],
)
def test_malformed_data_is_tolerated(malformed: dict[str, Any]) -> None:
    """Malformed coordinator data yields empty results without raising exceptions."""
    tracker = RuleAuditTracker()
    assert tracker.process(malformed, _ALL_OK) == {}
    assert tracker.process(malformed, _ALL_OK) == {}


def test_returned_lists_are_copies() -> None:
    """Mutating returned change lists does not mutate tracker state."""
    tracker = RuleAuditTracker()
    tracker.process(_data(), _ALL_OK)
    res = tracker.process(
        _data(firewall_rules={"s1": {"r1": {"name": "R1", "enabled": True}}}),
        _ALL_OK,
    )
    res["s1"].clear()
    res2 = tracker.process(
        _data(firewall_rules={"s1": {"r1": {"name": "R1", "enabled": True}}}),
        _ALL_OK,
    )
    assert len(res2["s1"]) == 1


def test_rule_name_uses_first_non_blank_field() -> None:
    """Rule name extraction uses the first non-blank field or falls back to None."""
    tracker = RuleAuditTracker()
    tracker.process(_data(), _ALL_OK)
    data = _data(
        policy_based_routes={
            "s1": {
                "p1": {"description": "P1 Desc", "name": "P1 Name", "enabled": True},
                "p2": {"description": "   ", "name": "P2 Name", "enabled": True},
                "p3": {"enabled": True},
            }
        }
    )
    res = tracker.process(data, _ALL_OK)
    names_by_id = {c["rule_id"]: c["rule_name"] for c in res["s1"]}
    assert names_by_id["p1"] == "P1 Desc"
    assert names_by_id["p2"] == "P2 Name"
    assert names_by_id["p3"] is None
