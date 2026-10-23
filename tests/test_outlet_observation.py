# Copyright 2026 UniFi Insights contributors
"""
Tests for the hardware-test PDU outlet observation (test branch only).

The observation is evidence, so the tests check that it records what a
hardware run needs (both raw arrays, the payload verdict, the array about to be
sent and its non-target comparison), that a poll counts only after a
successful root publication, that the command context (epoch, deadline, first
write) is enforced, and that a present-but-invalid profile fails writes closed
instead of silently disappearing.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from custom_components.unifi_insights.outlet_observation import (
    _ABSENT,
    MAX_OBSERVED_EVENTS,
    OBSERVATION_SCHEMA,
    SECOND_WRITE_GAP_SECONDS,
    SENSED_TELEMETRY_KEYS,
    ObservationProfileState,
    OutletObservation,
    _relay_value,
    _status_token,
    compare_rows,
    config_fields,
    load_profile_state,
    project_rows,
    row_digest,
    row_digest_norelay,
    row_index,
    row_projection,
)

if TYPE_CHECKING:
    from pathlib import Path

SITE_ID = "88f7af54-98f8-306a-a1c7-c9349722b1f6"
DEVICE_ID = "ac5795e3-3430-3b24-850e-9e134002ec21"
NAME_CANARY = "Owner Home Office Lamp"
STATUS_WORD = "GETTING_READY"


def _profile_file(tmp_path: Path, **overrides: Any) -> Path:
    """Write a valid profile file, with optional field overrides."""
    payload: dict[str, Any] = {
        "schema": OBSERVATION_SCHEMA,
        "enabled": True,
        "site_id": SITE_ID,
        "device_id": DEVICE_ID,
        "targets": [17, 18],
    }
    payload.update(overrides)
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _row(index: int, *, relay: Any = False, cycle: bool = True) -> dict[str, Any]:
    """Return a raw outlet row shaped like the controller's."""
    return {
        "index": index,
        "name": NAME_CANARY,
        "relay_state": relay,
        "cycle_enabled": cycle,
        "outlet_power": "0.0",
        "outlet_current": "0.00",
        "outlet_voltage": "120.2",
        "outlet_power_factor": "0.98",
    }


def _valid_observation(tmp_path: Path, **overrides: Any) -> OutletObservation:
    """Return an observation holding a valid profile state."""
    observation = OutletObservation()
    observation.set_profile_state(
        load_profile_state(_profile_file(tmp_path, **overrides))
    )
    return observation


def _stage(observation: OutletObservation, **overrides: Any) -> Any:
    """Stage one poll record for the profiled device."""
    values: dict[str, Any] = {
        "site_id": SITE_ID,
        "device_id": DEVICE_ID,
        "source": "legacy",
        "raw": {
            "outlet_table": [_row(17), _row(18)],
            "outlet_overrides": [_row(17), _row(18)],
        },
        "published": {"state": STATUS_WORD, "outlet_table": [_row(17)]},
        "trusted": True,
        "required_indexes": [17, 18],
        "required_row_fields": [(17, "name")],
        "pending": {17: {"relay_state": True}},
    }
    values.update(overrides)
    return observation.stage_poll(**values)


# -- profile loading -----------------------------------------------------
def test_load_profile_accepts_the_documented_shape(tmp_path: Path) -> None:
    """A valid profile yields the site, device and index set."""
    state = load_profile_state(_profile_file(tmp_path))

    assert state.status == "valid"
    assert state.reason is None
    assert state.profile is not None
    assert state.profile.site_id == SITE_ID
    assert state.profile.device_id == DEVICE_ID
    assert state.profile.targets == frozenset({17, 18})
    assert state.profile.command is None


def test_load_profile_parses_a_command_context(tmp_path: Path) -> None:
    """A command context carries the epoch, deadline and first-write flag."""
    state = load_profile_state(
        _profile_file(
            tmp_path,
            command={
                "operation": "on18",
                "expected_epoch": 7,
                "deadline_epoch": 1761300000.5,
                "require_prior_write": True,
            },
        )
    )

    assert state.profile is not None
    command = state.profile.command
    assert command is not None
    assert command.operation == "on18"
    assert command.expected_epoch == 7
    assert command.deadline_epoch == 1761300000.5
    assert command.require_prior_write is True


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"schema": 1}, "schema"),
        ({"enabled": False}, "disabled"),
        ({"enabled": "yes"}, "disabled"),
        ({"site_id": ""}, "site"),
        ({"site_id": None}, "site"),
        ({"device_id": ""}, "device"),
        ({"targets": []}, "targets"),
        ({"targets": "17"}, "targets"),
        ({"targets": [True]}, "targets"),
        ({"targets": [0]}, "targets"),
        ({"targets": [17, 17]}, "targets"),
        ({"command": {"operation": "", "expected_epoch": 1}}, "command"),
        ({"command": {"operation": "on17", "expected_epoch": -1}}, "command"),
        ({"command": {"operation": "on17", "expected_epoch": True}}, "command"),
        ({"command": {"operation": "on17", "deadline_epoch": "soon"}}, "command"),
        ({"command": {"operation": "on17", "require_prior_write": 1}}, "command"),
        ({"command": "on17"}, "command"),
    ],
)
def test_load_profile_refuses_anything_else(
    tmp_path: Path, overrides: dict[str, Any], reason: str | None
) -> None:
    """Anything but a complete, current profile is invalid, never absent."""
    state = load_profile_state(_profile_file(tmp_path, **overrides))

    assert state.status == "invalid"
    assert state.profile is None
    assert state.reason == reason


@pytest.mark.parametrize("content", [None, "", "not json", "[]", "{}"])
def test_load_profile_is_fail_closed(tmp_path: Path, content: str | None) -> None:
    """A missing profile is absent; an unreadable or wrong one is invalid."""
    path = tmp_path / "profile.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    state = load_profile_state(path)
    if content is None:
        assert state.status == "absent"
    else:
        assert state.status == "invalid"
        assert state.reason in {"unreadable", "schema", "shape"}
    assert load_profile_state(None).status == "absent"


def test_load_profile_reports_an_unreadable_file(tmp_path: Path) -> None:
    """An OSError is invalid, not an unrestricted default."""
    directory = tmp_path / "profile.json"
    directory.mkdir()

    state = load_profile_state(directory)

    assert state.status == "invalid"
    assert state.reason == "unreadable"


def test_valid_profile_clears_the_invalid_state(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Recovering from an invalid profile is logged and visible as state."""
    observation = OutletObservation()
    observation.set_profile_state(
        ObservationProfileState("invalid", None, "unreadable")
    )

    observation.set_profile_state(load_profile_state(_profile_file(tmp_path)))

    assert observation.profile_state.status == "valid"
    assert observation.profile is not None
    assert observation.profile.site_id == SITE_ID
    infos = [record for record in caplog.records if record.levelname == "INFO"]
    assert any("no longer invalid" in record.getMessage() for record in infos)


def test_invalid_profile_is_logged_once_per_transition(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The operator sees the refusal once, with no file content."""
    observation = OutletObservation()
    observation.set_profile_state(ObservationProfileState("invalid", None, "command"))
    observation.set_profile_state(ObservationProfileState("invalid", None, "command"))

    warnings = [record for record in caplog.records if record.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "invalid" in warnings[0].getMessage()
    assert NAME_CANARY not in warnings[0].getMessage()


# -- rows and digests ----------------------------------------------------
def test_row_index_reads_every_alias_and_rejects_junk() -> None:
    """The observer reads the same index aliases the builder does."""
    assert row_index({"index": 17}) == 17
    assert row_index({"outlet_idx": "18"}) == 18
    assert row_index({"outletIdx": 19}) == 19
    assert row_index({"index": True}) is None
    assert row_index({"index": 1.5}) is None
    assert row_index({"index": "x"}) is None
    assert row_index({"index": None}) is None
    assert row_index({"name": "no index"}) is None
    assert row_index("not a row") is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        (STATUS_WORD, STATUS_WORD),
        ("mixed Case", None),
        (2, None),
        (None, None),
        ({"nested": True}, None),
    ],
)
def test_relay_value_keeps_only_booleans_and_status_words(
    value: Any, expected: Any
) -> None:
    """A status word survives; free text, names and numbers do not."""
    assert _relay_value({"relay_state": value}) == expected


def test_status_token_drops_anything_but_a_short_word() -> None:
    """Only allowlisted status words are recorded as text."""
    assert _status_token(STATUS_WORD) == STATUS_WORD
    assert _status_token("online") is None
    assert _status_token("A B") is None
    not_a_token = True
    assert _status_token(not_a_token) is None
    assert _status_token("X" * 40) is None


def test_exact_telemetry_allowlist_keeps_writable_keys_visible() -> None:
    """Only sensed values are excluded from the config digest."""
    assert {
        "outlet_power",
        "outlet_current",
        "outlet_voltage",
        "outlet_power_factor",
    } == SENSED_TELEMETRY_KEYS
    fields = config_fields(_row(17))
    for key in SENSED_TELEMETRY_KEYS:
        assert key not in fields
    assert "name" in fields
    assert "power_on_state" in config_fields({"index": 17, "power_on_state": False})


def test_row_digest_is_stable_and_never_carries_the_row() -> None:
    """A digest is comparable across polls and leaks no content."""
    row = _row(17)
    digest = row_digest(row)

    assert digest == row_digest({**row})
    assert digest != row_digest({**row, "relay_state": True})
    assert NAME_CANARY not in digest
    assert len(digest) == 16


def test_row_digest_ignores_sensed_telemetry_only() -> None:
    """Sensed values move every poll; a writable key must not be hidden."""
    row = _row(17)

    for key in SENSED_TELEMETRY_KEYS:
        assert row_digest(row) == row_digest({**row, key: "999.9"})
    assert row_digest(row) != row_digest({**row, "name": "Other"})
    assert row_digest(row) != row_digest({**row, "power_on_state": True})


def test_row_projection_records_fields_and_digest() -> None:
    """The projection keeps the writable values and a content digest."""
    projected = row_projection(_row(17, relay=True))

    assert projected["relay_state"] is True
    assert projected["cycle_enabled"] is True
    assert set(projected) == {
        "relay_state",
        "cycle_enabled",
        "config_sha",
        "config_norel_sha",
        "config_fields",
    }
    assert "name" in projected["config_fields"]
    assert "outlet_power" not in projected["config_fields"]
    assert NAME_CANARY not in json.dumps(projected)


def test_row_digest_norelay_is_stable_across_relay_writes() -> None:
    """The relay-tolerant digest moves with any other writable field only."""
    on = row_projection(_row(17, relay=True))
    off = row_projection(_row(17, relay=False))

    assert on["config_sha"] != off["config_sha"]
    assert on["config_norel_sha"] == off["config_norel_sha"]
    assert row_digest_norelay(_row(17)) != row_digest_norelay(
        {**_row(17), "cycle_enabled": False}
    )
    assert row_digest_norelay(_row(17)) != row_digest_norelay(
        {**_row(17), "power_on_state": True}
    )


def test_project_rows_separates_absent_malformed_and_duplicate_rows() -> None:
    """Missing arrays, junk rows and duplicate indexes are all visible."""
    absent = project_rows(_ABSENT)
    assert absent == {
        "present": False,
        "is_list": False,
        "count": 0,
        "indexes": [],
        "rows": {},
        "malformed": 0,
        "duplicates": [],
    }
    assert project_rows(None)["present"] is True
    assert project_rows(None)["is_list"] is False

    projected = project_rows([_row(17), _row(18), {"name": "no index"}, _row(17)])
    assert projected["count"] == 4
    assert projected["indexes"] == [17, 18]
    assert projected["malformed"] == 1
    assert projected["duplicates"] == [17]
    assert set(projected["rows"]) == {17, 18}


def test_compare_rows_reports_missing_and_changed_only() -> None:
    """Only baseline indexes that vanished or changed are reported."""
    baseline = {17: row_projection(_row(17)), 18: row_projection(_row(18))}
    sent = {
        17: row_projection(_row(17)),
        18: row_projection(_row(18, cycle=False)),
        19: row_projection(_row(19)),
    }

    assert compare_rows(baseline, sent) == {"missing": [], "changed": [18]}
    assert compare_rows(baseline, {17: baseline[17]}) == {
        "missing": [18],
        "changed": [],
    }


# -- staging and committed epochs ---------------------------------------
def test_staged_poll_does_not_count_until_the_root_is_published(
    tmp_path: Path,
) -> None:
    """Staging alone changes no buffer and no epoch."""
    observation = _valid_observation(tmp_path)

    record = _stage(observation)

    assert record is not None
    assert record["epoch"] is None
    assert observation.epoch == 0
    snapshot = observation.snapshot()
    assert snapshot is not None
    assert snapshot["polls"] == []
    assert snapshot["poll_count"] == 0


def test_commit_stamps_the_epoch_and_publication_time(tmp_path: Path) -> None:
    """A committed poll carries the epoch and the published root time."""
    observation = _valid_observation(tmp_path)
    _stage(observation)

    assert observation.commit_refresh("2026-10-23T12:00:00Z") == 1

    snapshot = observation.snapshot()
    assert snapshot is not None
    assert snapshot["epoch"] == 1
    poll = snapshot["polls"][-1]
    assert poll["epoch"] == 1
    assert poll["published_at"] == "2026-10-23T12:00:00Z"
    assert poll["raw"]["outlet_table"]["indexes"] == [17, 18]
    assert poll["raw"]["outlet_overrides"]["indexes"] == [17, 18]
    assert poll["published"]["rows"][17]["relay_state"] is False
    assert poll["provenance"]["required_row_fields"] == ["17:name"]
    assert poll["pending"] == {"17": {"relay_state": True}} or poll["pending"] == {
        17: {"relay_state": True}
    }
    assert NAME_CANARY not in json.dumps(poll)


def test_commit_without_a_poll_advances_nothing(tmp_path: Path) -> None:
    """A refresh that staged nothing (other site, no profile) keeps the epoch."""
    observation = _valid_observation(tmp_path)

    assert observation.commit_refresh("2026-10-23T12:00:00Z") == 0
    assert observation.epoch == 0


def test_begin_refresh_discards_a_cancelled_stage(tmp_path: Path) -> None:
    """A refresh that failed before publication leaves no committed record."""
    observation = _valid_observation(tmp_path)
    _stage(observation)

    observation.begin_refresh()
    assert observation.commit_refresh("2026-10-23T12:00:00Z") == 0

    snapshot = observation.snapshot()
    assert snapshot is not None
    assert snapshot["polls"] == []
    assert snapshot["epoch"] == 0


def test_stage_ignores_another_site_device_or_absent_profile(
    tmp_path: Path,
) -> None:
    """Only the profiled device is staged, and nothing is staged when disabled."""
    observation = _valid_observation(tmp_path)
    assert _stage(observation, site_id="other-site") is None
    assert _stage(observation, device_id="other-device") is None

    absent = OutletObservation()
    assert _stage(absent) is None
    observation.commit_refresh("2026-10-23T12:00:00Z")


def test_snapshot_is_absent_until_a_profile_exists(tmp_path: Path) -> None:
    """No profile, no diagnostics section - the feature is off by default."""
    assert OutletObservation().snapshot() is None


def test_snapshot_reports_an_invalid_profile_without_a_profile_body() -> None:
    """An invalid profile is visible to diagnostics and carries no content."""
    observation = OutletObservation()
    observation.set_profile_state(
        ObservationProfileState("invalid", None, "unreadable")
    )

    snapshot = observation.snapshot()

    assert snapshot is not None
    assert snapshot["status"] == "invalid"
    assert snapshot["reason"] == "unreadable"
    assert "profile" not in snapshot
    assert snapshot["polls"] == []


def test_snapshot_reports_the_command_context(tmp_path: Path) -> None:
    """Diagnostics show exactly which epoch and deadline were expected."""
    observation = _valid_observation(
        tmp_path,
        command={
            "operation": "on17",
            "expected_epoch": 3,
            "deadline_epoch": 1761300000.0,
            "require_prior_write": False,
        },
    )

    snapshot = observation.snapshot()

    assert snapshot is not None
    assert snapshot["profile"]["command"] == {
        "operation": "on17",
        "expected_epoch": 3,
        "deadline_epoch": 1761300000.0,
        "require_prior_write": False,
    }


def test_snapshot_buffers_stay_bounded(tmp_path: Path) -> None:
    """The newest records survive; the buffers never grow without limit."""
    observation = _valid_observation(tmp_path)
    for _ in range(MAX_OBSERVED_EVENTS + 3):
        _stage(observation)
        observation.commit_refresh("2026-10-23T12:00:00Z")

    snapshot = observation.snapshot()

    assert snapshot is not None
    assert snapshot["poll_count"] == MAX_OBSERVED_EVENTS + 3
    assert len(snapshot["polls"]) == MAX_OBSERVED_EVENTS
    assert snapshot["polls"][-1]["epoch"] == MAX_OBSERVED_EVENTS + 3


# -- allowlist and command context --------------------------------------
def test_allowlist_is_exact(tmp_path: Path) -> None:
    """Only the profiled site, device and indexes are allowed."""
    observation = _valid_observation(tmp_path)

    assert observation.allows(site_id=SITE_ID, device_id=DEVICE_ID, outlet_index=17)
    assert not observation.allows(site_id=SITE_ID, device_id=DEVICE_ID, outlet_index=19)
    assert not observation.allows(site_id="other", device_id=DEVICE_ID, outlet_index=17)
    assert not observation.allows(site_id=SITE_ID, device_id="other", outlet_index=17)


def test_command_verdict_without_a_profile_allows_everything() -> None:
    """The absent default never restricts a normal integration."""
    observation = OutletObservation()

    assert (
        observation.command_verdict(
            site_id=SITE_ID,
            device_id=DEVICE_ID,
            outlet_index=1,
            now_wall=0.0,
            state=True,
            cycle_enabled=None,
        )
        is None
    )


def test_command_verdict_refuses_every_outlet_for_an_invalid_profile() -> None:
    """An invalid profile fails closed, including outlets outside the list."""
    observation = OutletObservation()
    observation.set_profile_state(
        ObservationProfileState("invalid", None, "unreadable")
    )

    assert (
        observation.command_verdict(
            site_id=SITE_ID,
            device_id=DEVICE_ID,
            outlet_index=17,
            now_wall=0.0,
            state=True,
            cycle_enabled=None,
        )
        == "observation profile is invalid"
    )


def test_command_verdict_enforces_the_allowlist(tmp_path: Path) -> None:
    """A valid profile without a command context still blocks other outlets."""
    observation = _valid_observation(tmp_path)

    assert (
        observation.command_verdict(
            site_id=SITE_ID,
            device_id=DEVICE_ID,
            outlet_index=17,
            now_wall=0.0,
            state=True,
            cycle_enabled=None,
        )
        is None
    )
    assert (
        observation.command_verdict(
            site_id=SITE_ID,
            device_id=DEVICE_ID,
            outlet_index=19,
            now_wall=0.0,
            state=True,
            cycle_enabled=None,
        )
        == "outlet is not in the observation allowlist"
    )


def test_command_verdict_enforces_the_committed_epoch(tmp_path: Path) -> None:
    """A poll committed since the run read the epoch rejects the command."""
    observation = _valid_observation(
        tmp_path, command={"operation": "on17", "expected_epoch": 1}
    )

    assert (
        observation.command_verdict(
            site_id=SITE_ID,
            device_id=DEVICE_ID,
            outlet_index=17,
            now_wall=0.0,
            state=True,
            cycle_enabled=None,
        )
        == "the committed poll epoch changed"
    )

    _stage(observation)
    observation.commit_refresh("2026-10-23T12:00:00Z")
    assert (
        observation.command_verdict(
            site_id=SITE_ID,
            device_id=DEVICE_ID,
            outlet_index=17,
            now_wall=0.0,
            state=True,
            cycle_enabled=None,
        )
        is None
    )


def test_command_verdict_enforces_the_deadline(tmp_path: Path) -> None:
    """A command after its deadline is refused."""
    observation = _valid_observation(
        tmp_path,
        command={
            "operation": "on18",
            "expected_epoch": 0,
            "deadline_epoch": 1000.0,
        },
    )

    assert (
        observation.command_verdict(
            site_id=SITE_ID,
            device_id=DEVICE_ID,
            outlet_index=18,
            now_wall=1000.0,
            state=True,
            cycle_enabled=None,
        )
        is None
    )
    assert (
        observation.command_verdict(
            site_id=SITE_ID,
            device_id=DEVICE_ID,
            outlet_index=18,
            now_wall=1000.5,
            state=True,
            cycle_enabled=None,
        )
        == "the command deadline expired"
    )


@pytest.mark.parametrize(
    ("operation", "index", "state", "cycle", "refusal"),
    [
        ("on18", 17, True, None, "the command operation names a different outlet"),
        (
            "on18",
            18,
            False,
            None,
            "the command operation does not match the requested state",
        ),
        (
            "off17",
            17,
            True,
            None,
            "the command operation does not match the requested state",
        ),
        ("on17", 19, True, None, "outlet is not in the observation allowlist"),
        ("on17", 17, True, False, "the command operation is relay-only"),
        (
            "cycle17",
            17,
            True,
            None,
            "the command operation is not an on/off outlet operation",
        ),
        (
            "reboot",
            17,
            True,
            None,
            "the command operation is not an on/off outlet operation",
        ),
    ],
)
def test_command_verdict_binds_the_operation_to_the_actual_write(
    tmp_path: Path,
    *,
    operation: str,
    index: int,
    state: bool,
    cycle: bool | None,
    refusal: str,
) -> None:
    """Only the exact relay write the operation names is authorised."""
    observation = _valid_observation(
        tmp_path, command={"operation": operation, "expected_epoch": 0}
    )

    assert (
        observation.command_verdict(
            site_id=SITE_ID,
            device_id=DEVICE_ID,
            outlet_index=index,
            now_wall=0.0,
            state=state,
            cycle_enabled=cycle,
        )
        == refusal
    )


def test_command_verdict_requires_a_confirmed_first_write(tmp_path: Path) -> None:
    """The second command needs a recent, confirmed, different-outlet write."""
    observation = _valid_observation(
        tmp_path,
        command={
            "operation": "on18",
            "expected_epoch": 0,
            "require_prior_write": True,
        },
    )

    def verdict(now: float) -> str | None:
        return observation.command_verdict(
            site_id=SITE_ID,
            device_id=DEVICE_ID,
            outlet_index=18,
            now_wall=now,
            state=True,
            cycle_enabled=None,
        )

    assert verdict(10.0) == "no confirmed first write"

    failed = observation.record_write(
        site_id=SITE_ID,
        device_id=DEVICE_ID,
        outlet_index=17,
        state=True,
        cycle_enabled=None,
        sent=[_row(17, relay=True)],
        baseline=[_row(17)],
        required_indexes=[17],
        expected_epoch=0,
        operation="on17",
        deadline_epoch=None,
    )
    observation.finish_write(failed, result=False)
    assert verdict(10.0) == "no confirmed first write"

    sent = observation.record_write(
        site_id=SITE_ID,
        device_id=DEVICE_ID,
        outlet_index=17,
        state=True,
        cycle_enabled=None,
        sent=[_row(17, relay=True)],
        baseline=[_row(17)],
        required_indexes=[17],
        expected_epoch=0,
        operation="on17",
        deadline_epoch=None,
    )
    observation.finish_write(sent, result=True)
    assert verdict(sent["written_wall"] + 1.0) is None
    assert verdict(sent["written_wall"] + SECOND_WRITE_GAP_SECONDS + 1.0) == (
        "the first write is outside the guard window"
    )

    same_outlet = observation.record_write(
        site_id=SITE_ID,
        device_id=DEVICE_ID,
        outlet_index=18,
        state=True,
        cycle_enabled=None,
        sent=[_row(18, relay=True)],
        baseline=[_row(18)],
        required_indexes=[18],
        expected_epoch=0,
        operation="on18",
        deadline_epoch=None,
    )
    observation.finish_write(same_outlet, result=True)
    assert (
        observation.command_verdict(
            site_id=SITE_ID,
            device_id=DEVICE_ID,
            outlet_index=18,
            now_wall=0.0,
            state=True,
            cycle_enabled=None,
        )
        == "the first write was this outlet"
    )


def test_command_verdict_requires_the_matching_prior_on_write(
    tmp_path: Path,
) -> None:
    """Only a confirmed ON record for the other target unlocks the second."""
    observation = _valid_observation(
        tmp_path,
        command={
            "operation": "on18",
            "expected_epoch": 0,
            "require_prior_write": True,
        },
    )

    def verdict() -> str | None:
        return observation.command_verdict(
            site_id=SITE_ID,
            device_id=DEVICE_ID,
            outlet_index=18,
            now_wall=0.0,
            state=True,
            cycle_enabled=None,
        )

    off_write = observation.record_write(
        site_id=SITE_ID,
        device_id=DEVICE_ID,
        outlet_index=17,
        state=False,
        cycle_enabled=None,
        sent=[_row(17, relay=False)],
        baseline=[_row(17)],
        required_indexes=[17],
        expected_epoch=0,
        operation="off17",
        deadline_epoch=None,
    )
    observation.finish_write(off_write, result=True)
    assert verdict() == "no confirmed first write"

    wrong_operation = observation.record_write(
        site_id=SITE_ID,
        device_id=DEVICE_ID,
        outlet_index=17,
        state=True,
        cycle_enabled=None,
        sent=[_row(17, relay=True)],
        baseline=[_row(17)],
        required_indexes=[17],
        expected_epoch=0,
        operation="on18",
        deadline_epoch=None,
    )
    observation.finish_write(wrong_operation, result=True)
    assert verdict() == "the first write does not match its ON operation"

    matching = observation.record_write(
        site_id=SITE_ID,
        device_id=DEVICE_ID,
        outlet_index=17,
        state=True,
        cycle_enabled=None,
        sent=[_row(17, relay=True)],
        baseline=[_row(17)],
        required_indexes=[17],
        expected_epoch=0,
        operation="on17",
        deadline_epoch=None,
    )
    observation.finish_write(matching, result=True)
    assert verdict() is None


def test_command_verdict_rechecks_the_prior_outlet_against_new_targets(
    tmp_path: Path,
) -> None:
    """A prior write from a removed target no longer authorises anything."""
    observation = _valid_observation(tmp_path)
    prior = observation.record_write(
        site_id=SITE_ID,
        device_id=DEVICE_ID,
        outlet_index=17,
        state=True,
        cycle_enabled=None,
        sent=[_row(17, relay=True)],
        baseline=[_row(17)],
        required_indexes=[17],
        expected_epoch=0,
        operation="on17",
        deadline_epoch=None,
    )
    observation.finish_write(prior, result=True)
    # The profile changes: outlet 17 leaves the allowlist and only on18 with
    # a first-write requirement remains. The old on17 record must not count.
    observation.set_profile_state(
        load_profile_state(
            _profile_file(
                tmp_path,
                targets=[18],
                command={
                    "operation": "on18",
                    "expected_epoch": 0,
                    "require_prior_write": True,
                },
            )
        )
    )

    assert (
        observation.command_verdict(
            site_id=SITE_ID,
            device_id=DEVICE_ID,
            outlet_index=18,
            now_wall=0.0,
            state=True,
            cycle_enabled=None,
        )
        == "the first write is not an approved outlet"
    )


def test_command_verdict_requires_a_first_write_timestamp(tmp_path: Path) -> None:
    """A confirmed write without an HA timestamp cannot authorise the second."""
    observation = _valid_observation(
        tmp_path,
        command={
            "operation": "on18",
            "expected_epoch": 0,
            "require_prior_write": True,
        },
    )
    record = observation.record_write(
        site_id=SITE_ID,
        device_id=DEVICE_ID,
        outlet_index=17,
        state=True,
        cycle_enabled=None,
        sent=[_row(17, relay=True)],
        baseline=[_row(17)],
        required_indexes=[17],
        expected_epoch=0,
        operation="on17",
        deadline_epoch=None,
    )
    observation.finish_write(record, result=True)
    assert record is not None
    del record["written_wall"]

    assert (
        observation.command_verdict(
            site_id=SITE_ID,
            device_id=DEVICE_ID,
            outlet_index=18,
            now_wall=0.0,
            state=True,
            cycle_enabled=None,
        )
        == "the first write has no timestamp"
    )


def test_record_write_is_refused_outside_the_allowlist(tmp_path: Path) -> None:
    """No record and no trace for any other outlet."""
    observation = _valid_observation(tmp_path)

    assert (
        observation.record_write(
            site_id=SITE_ID,
            device_id=DEVICE_ID,
            outlet_index=20,
            state=True,
            cycle_enabled=None,
            sent=[_row(20, relay=True)],
            baseline=[_row(20)],
            required_indexes=[20],
            expected_epoch=0,
            operation="on20",
            deadline_epoch=None,
        )
        is None
    )
    snapshot = observation.snapshot()
    assert snapshot is not None
    assert snapshot["write_count"] == 0


def test_record_write_compares_non_target_rows_against_the_baseline(
    tmp_path: Path,
) -> None:
    """The record shows the exact body, its coverage and any sibling change."""
    observation = _valid_observation(tmp_path)
    baseline = [_row(17), _row(18), _row(19, cycle=True)]
    sent = [_row(17, relay=True), _row(18), _row(19, cycle=True)]

    record = observation.record_write(
        site_id=SITE_ID,
        device_id=DEVICE_ID,
        outlet_index=17,
        state=True,
        cycle_enabled=None,
        sent=sent,
        baseline=baseline,
        required_indexes=[17, 18, 19],
        expected_epoch=0,
        operation="on17",
        deadline_epoch=None,
    )

    assert record is not None
    assert record["outlet"] == 17
    assert record["epoch"] == 0
    assert record["expected_epoch"] == 0
    assert record["operation"] == "on17"
    assert record["deadline_epoch"] is None
    assert record["indexes"] == [17, 18, 19]
    assert record["required_indexes"] == [17, 18, 19]
    assert record["covers_required"] is True
    assert record["non_target"] == {
        "baseline": True,
        "missing": [],
        "changed": [],
        "malformed": 0,
        "rows": 2,
    }
    assert 17 not in record["non_target_rows"]
    assert record["non_target_rows"][18]["relay_state"] is False
    assert record["result"] is None
    assert NAME_CANARY not in json.dumps(record)
    assert len(record["body_sha"]) == 16


def test_record_write_reports_a_changed_sibling(tmp_path: Path) -> None:
    """A sibling whose writable value moves is reported before transport."""
    observation = _valid_observation(tmp_path)

    record = observation.record_write(
        site_id=SITE_ID,
        device_id=DEVICE_ID,
        outlet_index=17,
        state=True,
        cycle_enabled=None,
        sent=[_row(17, relay=True), _row(18, relay=True)],
        baseline=[_row(17), _row(18)],
        required_indexes=[17, 18],
        expected_epoch=0,
        operation="on17",
        deadline_epoch=None,
    )

    assert record is not None
    assert record["non_target"]["changed"] == [18]


def test_record_write_without_a_baseline_says_so(tmp_path: Path) -> None:
    """A seeded payload has no baseline array and is marked as such."""
    observation = _valid_observation(tmp_path)

    record = observation.record_write(
        site_id=SITE_ID,
        device_id=DEVICE_ID,
        outlet_index=17,
        state=True,
        cycle_enabled=None,
        sent=[_row(17, relay=True)],
        baseline=None,
        required_indexes=[17],
        expected_epoch=0,
        operation="on17",
        deadline_epoch=None,
    )

    assert record is not None
    assert record["non_target"] == {
        "baseline": False,
        "missing": [],
        "changed": [],
        "malformed": 0,
        "rows": 0,
    }


def test_finish_write_attaches_the_outcome_and_tolerates_no_record(
    tmp_path: Path,
) -> None:
    """The outcome lands on the pre-transport record; None is a no-op."""
    observation = _valid_observation(tmp_path)
    record = observation.record_write(
        site_id=SITE_ID,
        device_id=DEVICE_ID,
        outlet_index=17,
        state=True,
        cycle_enabled=None,
        sent=[_row(17, relay=True)],
        baseline=[_row(17)],
        required_indexes=[17],
        expected_epoch=0,
        operation="on17",
        deadline_epoch=None,
    )

    observation.finish_write(record, result=True)
    observation.finish_write(None, result=True)

    assert record is not None
    assert record["result"] is True
    assert "at_done" in record
    assert isinstance(record["written_wall"], float)
