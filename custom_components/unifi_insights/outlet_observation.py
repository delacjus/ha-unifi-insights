# Copyright 2026 UniFi Insights contributors
"""
Bounded, allowlisted PDU outlet observation for the #376 hardware test.

This is test-branch instrumentation, not a shipped feature. It exists so a
hardware run can prove what the coordinator actually polled and what it was
about to send, without a proxy, a patched aiohttp session or a second raw
controller read (a standalone GET cannot show that a coordinator poll happened
and received stale data).

Off by default: nothing is recorded, and no write is restricted, unless the
operator places a profile file in the Home Assistant config directory
(``OBSERVATION_FILENAME``). The profile names one site, one device, the outlet
indexes the run may command and, optionally, the command context the run
expects:

    {"schema": 2, "enabled": true, "site_id": "...", "device_id": "...",
     "targets": [17, 18],
     "command": {"operation": "on17", "expected_epoch": 7,
                 "deadline_epoch": 1761..., "require_prior_write": false}}

While a **valid** profile is installed:

- every successfully published device poll appends one record for the named
  device (raw controller rows from *both* arrays, the payload-provenance
  verdict, the published outlet values and the fields still held by pending
  writes), stamped with the committed publication epoch;
- every outlet command appends one record of the array it is about to hand to
  the pinned client, compared field-by-field against the array it was built
  from, with a whole-body hash;
- an outlet command for any other index, site or device is refused before
  transport, and a command context is enforced inside the command seam (the
  committed poll epoch, its deadline and the first-write requirement).

A profile file that exists but cannot be validated is **invalid**, not absent:
reads keep working, every outlet write is refused, and the refusal is reported
once in the log and in diagnostics. Deleting the file is the only way back to
the unrestricted default. The file is read in the executor and re-read per
operation, so enabling, replacing or removing it needs no reload.

Records hold only outlet indexes, booleans, short status tokens, digests and
the run's own identifiers. Outlet names, MAC addresses, credentials and whole
device records are never copied, and the buffers are read back through the
existing diagnostics endpoint (see ``diagnostics.py``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import time
from collections import deque
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Final, Literal, NamedTuple

if TYPE_CHECKING:
    from pathlib import Path

_LOGGER = logging.getLogger(__name__)

OBSERVATION_FILENAME: Final = ".unifi_insights_hw_observe.json"
OBSERVATION_SCHEMA: Final = 2
# Bounded on purpose: the buffers are exposed in diagnostics, so an unbounded
# run would grow every report.
MAX_OBSERVED_EVENTS: Final = 32
# The run's second write must land inside the 60 s outlet-write guard. The
# coordinator checks the same constant against its own wall clock.
SECOND_WRITE_GAP_SECONDS: Final = 55.0
_DIGEST_LENGTH: Final = 16
# A controller status word (for example GETTING_READY). Anything else - a
# name, an address, free text - is dropped rather than recorded.
_STATUS_TOKEN = re.compile(r"[A-Z][A-Z_]{0,31}")
# The exact sensed keys that change every poll on a healthy device. Anything
# else - including a writable configuration key such as ``power_on_state`` -
# stays in the config digest, so an unknown field can never hide a change.
SENSED_TELEMETRY_KEYS: Final = frozenset(
    {"outlet_power", "outlet_current", "outlet_voltage", "outlet_power_factor"}
)
_INDEX_KEYS: Final = ("index", "outlet_idx", "outletIdx")
_ABSENT: Final = object()
_OPERATION_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,32}")
# A command operation must name exactly one relay write: ``on<index>`` or
# ``off<index>``. Anything else is refused inside the seam.
_OPERATION_PATTERN = re.compile(r"(on|off)([0-9]+)\Z")
_COMMAND_INVALID: Final = "invalid command context"

ProfileStatus = Literal["absent", "valid", "invalid"]


class ObservationCommand(NamedTuple):
    """The command context a run expects the coordinator to enforce."""

    operation: str
    expected_epoch: int | None
    deadline_epoch: float | None
    require_prior_write: bool


class ObservationProfile(NamedTuple):
    """The single site/device/index set a hardware run may command."""

    site_id: str
    device_id: str
    targets: frozenset[int]
    command: ObservationCommand | None

    def allows(self, *, site_id: str, device_id: str, outlet_index: int) -> bool:
        """Return True only for the exact site, device and allowlisted index."""
        return (
            self.site_id == site_id
            and self.device_id == device_id
            and outlet_index in self.targets
        )


class ObservationProfileState(NamedTuple):
    """Whether a profile is absent, valid, or present but unusable."""

    status: ProfileStatus
    profile: ObservationProfile | None
    reason: str | None


def _status_token(value: Any) -> str | None:
    """Return a short upper-case status word, or None for anything else."""
    if isinstance(value, str) and _STATUS_TOKEN.fullmatch(value):
        return value
    return None


def _relay_value(row: dict[str, Any]) -> bool | str | None:
    """Return an outlet row's relay value, keeping an unexpected status word."""
    value = row.get("relay_state")
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    return _status_token(value)


def row_index(row: Any) -> int | None:
    """Return a raw row's outlet index, tolerating the controller's aliases."""
    if not isinstance(row, dict):
        return None
    for key in _INDEX_KEYS:
        raw = row.get(key)
        if raw is None:
            continue
        if isinstance(raw, bool):
            continue
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str):
            try:
                return int(raw)
            except ValueError:
                return None
    return None


def _finite_power(value: Any) -> float | None:
    """
    Return a raw ``outlet_power`` reading as a finite float, or None.

    The controller may deliver the measurement as a numeric string; booleans,
    ``None``, non-numeric text and non-finite values are never coerced to a
    number, and every numeric value (including a non-zero one) is preserved
    exactly - an absent or invalid reading must never look like 0 W. A
    non-zero decimal string whose float conversion would underflow to zero
    (for example ``"1e-999"``) is invalid too; only a string whose exact
    decimal value is zero reads as 0 W.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        try:
            parsed = float(value)
        except OverflowError:
            return None
    elif isinstance(value, float):
        parsed = value
    elif isinstance(value, str):
        try:
            exact = Decimal(value)
        except InvalidOperation:
            return None
        try:
            parsed = float(exact)
        except ValueError, OverflowError:
            return None
        if not exact.is_zero() and parsed == 0.0:
            # A non-zero measurement underflowed to zero: keep the non-zero
            # guarantee instead of inventing a 0 W reading.
            return None
    else:
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _raw_target_power(
    rows: Any, targets: frozenset[int]
) -> dict[str, float | None] | None:
    """
    Project only the targets' raw ``outlet_power`` scalars for one poll.

    Nothing else leaves the raw rows: no names, no addresses, no other keys.
    A missing or duplicated target row, or a table that is not a list, drops
    the whole projection; an invalid reading only drops that target's value,
    so the run refuses instead of being handed a number the controller never
    reported.
    """
    if not isinstance(rows, list):
        return None
    values: dict[int, float | None] = {}
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        index = row_index(row)
        if index is None or index not in targets:
            continue
        if index in seen:
            return None
        seen.add(index)
        values[index] = _finite_power(row.get("outlet_power"))
    if set(targets) - set(values):
        return None
    return {str(index): values[index] for index in sorted(targets)}


def config_fields(row: dict[str, Any]) -> list[str]:
    """Return a row's non-telemetry field names (values are never reported)."""
    return sorted(
        key for key in row if isinstance(key, str) and key not in SENSED_TELEMETRY_KEYS
    )


def row_digest(row: dict[str, Any]) -> str:
    """Return a digest of a row's writable configuration, never the row."""
    payload = json.dumps(
        {key: row[key] for key in config_fields(row)},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:_DIGEST_LENGTH]


def row_digest_norelay(row: dict[str, Any]) -> str:
    """
    Return a digest of the writable configuration except ``relay_state``.

    ``row_digest`` deliberately includes the relay value, so a relay change
    moves it. A hardware run commands exactly the relay on its targets, so
    the observation must also expose a digest that is stable across a relay
    write but still covers every other writable field (name, cycle_enabled,
    power_on_state, ...): that is the digest the run compares before it
    authorises anything else.
    """
    payload = json.dumps(
        {key: row[key] for key in config_fields(row) if key != "relay_state"},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:_DIGEST_LENGTH]


def row_projection(row: dict[str, Any]) -> dict[str, Any]:
    """Project one outlet row to writable values, field names and a digest."""
    return {
        "relay_state": _relay_value(row),
        "cycle_enabled": (
            row["cycle_enabled"] if isinstance(row.get("cycle_enabled"), bool) else None
        ),
        "config_sha": row_digest(row),
        "config_norel_sha": row_digest_norelay(row),
        "config_fields": config_fields(row),
    }


def project_rows(rows: Any) -> dict[str, Any]:
    """Project a raw outlet array to indexed allowlisted rows."""
    projected: dict[str, Any] = {
        "present": rows is not _ABSENT,
        "is_list": isinstance(rows, list),
        "count": 0,
        "indexes": [],
        "rows": {},
        "malformed": 0,
        "duplicates": [],
    }
    if not isinstance(rows, list):
        return projected
    projected["count"] = len(rows)
    indexes: set[int] = set()
    duplicates: set[int] = set()
    for row in rows:
        index = row_index(row)
        if index is None:
            projected["malformed"] += 1
            continue
        if index in indexes:
            duplicates.add(index)
            continue
        indexes.add(index)
        projected["rows"][index] = row_projection(row)
    projected["indexes"] = sorted(indexes)
    projected["duplicates"] = sorted(duplicates)
    return projected


def _same_value(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """Compare two projected rows field by field, ignoring added fields."""
    return all(key in after and after[key] == value for key, value in before.items())


def compare_rows(
    baseline: dict[int, dict[str, Any]], sent: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    """Compare a sent array against the array it was built from."""
    missing = sorted(set(baseline) - set(sent))
    changed = sorted(
        index
        for index in set(baseline) & set(sent)
        if not _same_value(baseline[index], sent[index])
    )
    return {"missing": missing, "changed": changed}


def _command(raw: Any) -> ObservationCommand | None:
    """Return the profile's command context, or raise ``ValueError``."""
    if raw is None:
        return None
    try:
        return _parse_command(raw)
    except TypeError, ValueError:
        raise ValueError(_COMMAND_INVALID) from None


def _parse_command(raw: Any) -> ObservationCommand:
    """Validate one command context, raising on any unexpected value."""
    if not isinstance(raw, dict):
        raise TypeError(_COMMAND_INVALID)
    operation = raw.get("operation")
    if not isinstance(operation, str) or not _OPERATION_TOKEN.fullmatch(operation):
        raise ValueError(_COMMAND_INVALID)
    expected = raw.get("expected_epoch")
    if expected is not None and (
        isinstance(expected, bool) or not isinstance(expected, int) or expected < 0
    ):
        raise ValueError(_COMMAND_INVALID)
    deadline = raw.get("deadline_epoch")
    if deadline is not None and (
        isinstance(deadline, bool) or not isinstance(deadline, (int, float))
    ):
        raise ValueError(_COMMAND_INVALID)
    prior = raw.get("require_prior_write", False)
    if not isinstance(prior, bool):
        raise TypeError(_COMMAND_INVALID)
    return ObservationCommand(
        operation=operation,
        expected_epoch=expected,
        deadline_epoch=None if deadline is None else float(deadline),
        require_prior_write=prior,
    )


def load_profile_state(path: Path | None) -> ObservationProfileState:
    """
    Read and validate the observation profile.

    Pure and blocking: callers run it in Home Assistant's executor. Absent means
    the file is not there (the unrestricted default). A file that exists but is
    unreadable, malformed, of another schema, disabled, or carries a command
    context that cannot be validated is invalid and fails writes closed.
    """
    if path is None:
        return ObservationProfileState("absent", None, None)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ObservationProfileState("absent", None, None)
    except OSError:
        return ObservationProfileState("invalid", None, "unreadable")
    try:
        document = json.loads(raw)
    except ValueError:
        return ObservationProfileState("invalid", None, "unreadable")
    if not isinstance(document, dict):
        return ObservationProfileState("invalid", None, "shape")
    if document.get("schema") != OBSERVATION_SCHEMA:
        return ObservationProfileState("invalid", None, "schema")
    if document.get("enabled") is not True:
        return ObservationProfileState("invalid", None, "disabled")
    site_id, device_id = document.get("site_id"), document.get("device_id")
    if not isinstance(site_id, str) or not site_id:
        return ObservationProfileState("invalid", None, "site")
    if not isinstance(device_id, str) or not device_id:
        return ObservationProfileState("invalid", None, "device")
    targets = document.get("targets")
    if not isinstance(targets, list) or not targets:
        return ObservationProfileState("invalid", None, "targets")
    indexes: list[int] = []
    for item in targets:
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            return ObservationProfileState("invalid", None, "targets")
        indexes.append(item)
    if len(set(indexes)) != len(indexes):
        return ObservationProfileState("invalid", None, "targets")
    try:
        command = _command(document.get("command"))
    except ValueError:
        return ObservationProfileState("invalid", None, "command")
    return ObservationProfileState(
        "valid",
        ObservationProfile(
            site_id=site_id,
            device_id=device_id,
            targets=frozenset(indexes),
            command=command,
        ),
        None,
    )


def _utc_now() -> str:
    """Return the current UTC time as a second-precision ISO string."""
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class OutletObservation:
    """
    In-memory observation state for one coordinator.

    Pure bookkeeping: it never touches the filesystem, the controller or the
    transport. The coordinator installs a profile state it read in the
    executor; polls are staged and become committed records only when the poll
    that produced them was published as a new data root.
    """

    def __init__(self) -> None:
        """Initialise an empty, disabled observation."""
        self._state = ObservationProfileState("absent", None, None)
        self._epoch = 0
        self._polls: deque[dict[str, Any]] = deque(maxlen=MAX_OBSERVED_EVENTS)
        self._writes: deque[dict[str, Any]] = deque(maxlen=MAX_OBSERVED_EVENTS)
        self._staged: list[dict[str, Any]] = []
        self._write_seq = 0
        self._last_write: dict[str, Any] | None = None

    # -- profile state ---------------------------------------------------
    def set_profile_state(self, state: ObservationProfileState) -> None:
        """Install a validated profile state read by the caller."""
        previous = self._state
        self._state = state
        if state.status == "invalid" and previous.status != "invalid":
            _LOGGER.warning(
                "Device coordinator: the hardware-test observation profile is "
                "invalid (%s); every outlet command stays refused until it is "
                "replaced or removed",
                state.reason,
            )
        elif state.status != "invalid" and previous.status == "invalid":
            _LOGGER.info(
                "Device coordinator: the hardware-test observation profile is "
                "no longer invalid"
            )

    @property
    def profile_state(self) -> ObservationProfileState:
        """Return the installed profile state."""
        return self._state

    @property
    def profile(self) -> ObservationProfile | None:
        """Return the valid profile, or None."""
        return self._state.profile

    @property
    def epoch(self) -> int:
        """Return the number of committed poll publications."""
        return self._epoch

    def allows(self, *, site_id: str, device_id: str, outlet_index: int) -> bool:
        """Return True only for a valid profile's exact allowlisted outlet."""
        profile = self._state.profile
        return profile is not None and profile.allows(
            site_id=site_id, device_id=device_id, outlet_index=outlet_index
        )

    # -- poll staging ----------------------------------------------------
    def begin_refresh(self) -> None:
        """Drop anything staged by an earlier, unfinished refresh."""
        self._staged.clear()

    def stage_poll(
        self,
        *,
        site_id: str,
        device_id: str,
        source: str,
        raw: dict[str, Any],
        published: dict[str, Any],
        trusted: bool | None,
        required_indexes: list[int],
        required_row_fields: list[tuple[int, str]],
        pending: dict[int, dict[str, bool]],
    ) -> dict[str, Any] | None:
        """Stage one poll record; it counts only once a refresh is committed."""
        profile = self._state.profile
        if profile is None:
            return None
        if profile.site_id != site_id or profile.device_id != device_id:
            return None
        record: dict[str, Any] = {
            "kind": "poll",
            "epoch": None,
            "at": _utc_now(),
            "wall": round(time.time(), 3),
            "mono": round(time.monotonic(), 3),
            "site": site_id,
            "device": device_id,
            "source": source,
            "state_token": _status_token(
                published.get("state") if isinstance(published, dict) else None
            ),
            "raw_target_power": _raw_target_power(
                raw.get("outlet_table", _ABSENT), profile.targets
            ),
            "raw": {
                key: project_rows(raw.get(key, _ABSENT))
                for key in ("outlet_table", "outlet_overrides")
            },
            "provenance": {
                "trusted": trusted,
                "required_indexes": sorted(required_indexes),
                "required_row_fields": sorted(
                    f"{index}:{field}" for index, field in required_row_fields
                ),
            },
            "published": project_rows(
                published.get("outlet_table") if isinstance(published, dict) else None
            ),
            "pending": {
                index: dict(fields) for index, fields in sorted(pending.items())
            },
        }
        self._staged.append(record)
        return record

    def commit_refresh(self, published_at: Any) -> int:
        """
        Commit staged poll records after a successful root publication.

        Returns the committed epoch. Nothing is committed (and the epoch does
        not move) when the refresh staged no record for the profiled device or
        failed before publication.
        """
        if not self._staged:
            return self._epoch
        self._epoch += 1
        stamp = str(published_at or _utc_now())
        for record in self._staged:
            record["epoch"] = self._epoch
            record["published_at"] = stamp
            self._polls.append(record)
        self._staged.clear()
        return self._epoch

    # -- writes ----------------------------------------------------------
    def command_verdict(
        self,
        *,
        site_id: str,
        device_id: str,
        outlet_index: int,
        now_wall: float,
        state: bool | None,
        cycle_enabled: bool | None,
    ) -> str | None:
        """
        Return why this command may not proceed, or None when it may.

        The caller runs it inside the coordinator's command seam, once against
        the executor-loaded profile and again, synchronously, immediately
        before transport, so a poll committed meanwhile is rejected rather than
        raced.

        A command context binds the operation to the actual write: ``on17``
        only authorises relay ON on outlet 17 with no cycle change. The
        committed epoch, the deadline and the specifically matching first ON
        write (for ``require_prior_write``) are enforced in the same seam.
        """
        profile_state = self._state
        if profile_state.status == "invalid":
            return "observation profile is invalid"
        profile = profile_state.profile
        if profile is None:
            return None
        if not profile.allows(
            site_id=site_id, device_id=device_id, outlet_index=outlet_index
        ):
            return "outlet is not in the observation allowlist"
        command = profile.command
        if command is None:
            return None
        if command.expected_epoch is not None and command.expected_epoch != self._epoch:
            return "the committed poll epoch changed"
        operation = _OPERATION_PATTERN.fullmatch(command.operation)
        if operation is None:
            return "the command operation is not an on/off outlet operation"
        verb, raw_index = operation.groups()
        if int(raw_index) != outlet_index:
            return "the command operation names a different outlet"
        if (verb == "on") != bool(state):
            return "the command operation does not match the requested state"
        if cycle_enabled is not None:
            return "the command operation is relay-only"
        if command.deadline_epoch is not None and now_wall > command.deadline_epoch:
            return "the command deadline expired"
        if command.require_prior_write:
            last = self._last_write
            if last is None or last.get("result") is not True:
                return "no confirmed first write"
            if last.get("state") is not True:
                return "no confirmed first write"
            prior_outlet = last.get("outlet")
            if prior_outlet == outlet_index:
                return "the first write was this outlet"
            if prior_outlet not in profile.targets:
                return "the first write is not an approved outlet"
            if last.get("operation") != f"on{prior_outlet}":
                return "the first write does not match its ON operation"
            written = last.get("written_wall")
            if not isinstance(written, (int, float)):
                return "the first write has no timestamp"
            if now_wall - float(written) > SECOND_WRITE_GAP_SECONDS:
                return "the first write is outside the guard window"
        return None

    def record_write(
        self,
        *,
        site_id: str,
        device_id: str,
        outlet_index: int,
        state: bool,
        cycle_enabled: bool | None,
        sent: list[dict[str, Any]],
        baseline: Any,
        required_indexes: list[int],
        expected_epoch: int | None,
        operation: str | None,
        deadline_epoch: float | None,
    ) -> dict[str, Any] | None:
        """Record the exact array about to be handed to the client, or None."""
        profile = self._state.profile
        if profile is None or not profile.allows(
            site_id=site_id, device_id=device_id, outlet_index=outlet_index
        ):
            return None
        sent_rows = project_rows(sent)
        baseline_rows = project_rows(baseline) if isinstance(baseline, list) else None
        non_target = {
            index: projection
            for index, projection in sent_rows["rows"].items()
            if index != outlet_index
        }
        if baseline_rows is None:
            comparison: dict[str, Any] = {
                "baseline": False,
                "missing": [],
                "changed": [],
                "malformed": 0,
            }
        else:
            comparison = {
                "baseline": True,
                **compare_rows(
                    {
                        index: projection
                        for index, projection in baseline_rows["rows"].items()
                        if index != outlet_index
                    },
                    non_target,
                ),
                "malformed": baseline_rows["malformed"],
            }
        body = json.dumps(
            {"outlet_overrides": sent},
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
        self._write_seq += 1
        record: dict[str, Any] = {
            "kind": "write",
            "seq": self._write_seq,
            "epoch": self._epoch,
            "expected_epoch": expected_epoch,
            "operation": operation,
            "deadline_epoch": deadline_epoch,
            "at": _utc_now(),
            "wall": round(time.time(), 3),
            "mono": round(time.monotonic(), 3),
            "site": site_id,
            "device": device_id,
            "outlet": outlet_index,
            "state": state,
            "cycle_enabled": cycle_enabled,
            "indexes": sent_rows["indexes"],
            "required_indexes": sorted(required_indexes),
            "covers_required": sorted(sent_rows["indexes"]) == sorted(required_indexes),
            "non_target": {**comparison, "rows": len(non_target)},
            "non_target_rows": non_target,
            "body_sha": hashlib.sha256(body.encode()).hexdigest()[:_DIGEST_LENGTH],
            "result": None,
        }
        self._writes.append(record)
        self._last_write = record
        return record

    def finish_write(self, record: dict[str, Any] | None, *, result: Any) -> None:
        """Attach the transport outcome to a record made before the call."""
        if record is None:
            return
        record["result"] = result
        record["at_done"] = _utc_now()
        record["mono_done"] = round(time.monotonic(), 3)
        record["written_wall"] = round(time.time(), 3)

    # -- evidence --------------------------------------------------------
    def snapshot(self) -> dict[str, Any] | None:
        """Return the buffers and profile state, or None when no profile exists."""
        state = self._state
        if state.status == "absent":
            return None
        section: dict[str, Any] = {
            "schema": OBSERVATION_SCHEMA,
            "status": state.status,
            "reason": state.reason,
            "epoch": self._epoch,
            "poll_count": self._epoch,
            "write_count": self._write_seq,
            "polls": list(self._polls),
            "writes": list(self._writes),
        }
        if state.profile is not None:
            profile = state.profile
            section["profile"] = {
                "site_id": profile.site_id,
                "device_id": profile.device_id,
                "targets": sorted(profile.targets),
                "command": (
                    None
                    if profile.command is None
                    else {
                        "operation": profile.command.operation,
                        "expected_epoch": profile.command.expected_epoch,
                        "deadline_epoch": profile.command.deadline_epoch,
                        "require_prior_write": profile.command.require_prior_write,
                    }
                ),
            }
        return section
