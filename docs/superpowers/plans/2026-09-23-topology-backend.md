# Topology Backend (#165) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build two stacked, locally-prepared PRs for ruaan-deysel/ha-unifi-insights#165 that expose a per-site network topology graph (gateway → switches/APs → clients) over an authenticated WebSocket API designed for the future #166 card.

**Architecture:** The device coordinator stops discarding the legacy `/stat/device` `uplink` block and stores it as `device["topology"]`. A pure module `topology.py` turns facade data into an allowlisted, versioned snapshot. `websocket_api.py` exposes `sources` / `get` / `subscribe` commands; subscribe listens to the facade coordinator and pushes only when the snapshot revision changes. PR 2 adds per-client switch port, VLAN and network name from the `/stat/sta` response the config coordinator already fetches.

**Tech Stack:** Python 3.14, Home Assistant 2026.9.x custom integration, `homeassistant.components.websocket_api`, pytest + pytest-homeassistant-custom-component, ruff 0.16.7, mypy.

**Spec:** `/home/tacoriffic/ha-unifi-insights-topology/docs/superpowers/specs/2026-09-23-topology-backend-design.md` (branch `design/topology`, local only). Read it before starting.

## Global Constraints

- **Nothing is posted or pushed upstream.** PR bodies and the #165 comment are drafted as local files only. Pushing a `deploy/*` branch to the `origin` fork for the HACS live test (Task 10) requires Justin's explicit OK at that moment.
- Implementation worktree: `/home/tacoriffic/ha-unifi-insights-topo-impl` (created in Task 0). The design worktree `/home/tacoriffic/ha-unifi-insights-topology` stays on `design/topology` and holds this plan + the spec. Never touch `/home/tacoriffic/ha-unifi-insights` (Justin's `feat/wan-link-vpn-status` checkout, PR #164).
- PR 1 branch `feat/topology-graph` off `upstream/main`; PR 2 branch `feat/topology-client-links` off `feat/topology-graph`.
- Python for tests/mypy: `PY=/home/tacoriffic/ha-unifi-insights/.local/ha-test-venv-ci/bin/python` (HA 2026.9.3, matches CI). The older `.local/ha-test-venv` is stale — never use it.
- Test subsets: `$PY -m pytest <paths> -q --no-cov` (without `--no-cov` the 90% gate fails on subsets). Full suite: `$PY -m pytest --cov --cov-branch -q` — must stay ≥ 90%.
- Lint: `uvx ruff@0.16.7 check <files>` and `uvx ruff@0.16.7 format --check <files>`. **Never pass `--config`** (`.ruff.toml` with `select = ALL` wins by discovery). New-findings gate across every changed file: `~/ai-tools/scripts/ruff-new-findings.sh upstream/main 0.16.7`.
- Types: `$PY -m mypy custom_components/unifi_insights`. Two pre-existing errors in `entity.py` (`DeviceInfo | ChildDeviceInfo`) are not ours; no new errors allowed.
- Ruff style rules that bite: exception messages go in a `msg` variable first (EM101/EM102); a broad `except Exception` must mirror existing repo patterns or carry a justified `# noqa: BLE001`; docstrings on every public function/class.
- `topology.py` must not import from the package (`.entity`, `.coordinators`, …): `coordinators/config.py` imports `normalize_mac` from it in PR 2, and `.entity` imports `.coordinators`, which would create an import cycle. It keeps its own 5-line `_field()` helper with `get_field()` semantics (first non-None key wins).
- Contract constants (verbatim from spec): `TOPOLOGY_SCHEMA_VERSION = 1`, client hard cap `MAX_CLIENTS_PER_SITE = 500`, node id prefixes `dev:` / `cli:`, MAC-shaped ids → `<prefix>:h<sha256(f"{entry_id}:{mac}")[:16]>`.
- Allowlist: snapshots never contain MAC addresses, IP addresses, hostnames, firmware versions, SSIDs or byte counters.
- Commit messages: conventional (`feat:`, `test:`, `fix:`, `docs:`), body explains *why*.

## Review Focus

1. **A builder bug inside a coordinator listener.** `DataUpdateCoordinator.async_update_listeners()` calls listeners in a loop; an exception from the subscribe callback would abort it and freeze every entity on that entry. Expected: the callback logs once and keeps entities updating. → Task 5 test `test_subscribe_builder_error_does_not_break_listeners`.
2. **Double unsubscribe.** HA's remove-listener callback raises `KeyError` on a second call (`update_coordinator.py` pops the id). Connection close after entry unload (or the reverse) calls both paths. Expected: no exception, in either order. → Task 5 tests `test_subscribe_unload_then_close_is_safe` and `test_subscribe_close_then_unload_is_safe`.
3. **Legacy endpoint unavailable** (permissions, console type): no `topology` blocks at all. Expected: devices + clients still render, `status: partial`, issue `legacy_uplink_missing`, no crash. → Task 3 test `test_legacy_missing_is_partial_not_crash`.
4. **MAC-keyed devices** (id is the MAC, no UUID): Expected: opaque `dev:h…` id, still resolves as a parent, raw MAC never in payload. → Task 3 test `test_mac_keyed_device_resolves_and_is_opaque`.
5. **Client name that is a MAC or blank** (unnamed devices show their MAC as name on some firmware). Expected: rendered as `Unknown client`, MAC never emitted. → Task 3 test `test_client_name_mac_shaped_is_replaced`.

---

## File Structure

| File | PR | Responsibility |
|---|---|---|
| `custom_components/unifi_insights/coordinators/device.py` (modify) | 1 | Copy legacy uplink/type into `device["topology"]` on the merge and legacy-only paths |
| `custom_components/unifi_insights/topology.py` (create) | 1, 2 | Contract types, pure helpers, `build_site_topology`, `build_unavailable_topology` |
| `custom_components/unifi_insights/websocket_api.py` (create) | 1 | `unifi_insights/topology/{sources,get,subscribe}` |
| `custom_components/unifi_insights/__init__.py` (modify) | 1 | Register WS commands in `async_setup` |
| `custom_components/unifi_insights/manifest.json` (modify) | 1 | Add `websocket_api` dependency |
| `custom_components/unifi_insights/coordinators/config.py` (modify) | 2 | Standalone `/stat/sta` fetch → `client_links` |
| `custom_components/unifi_insights/coordinators/facade.py` (modify) | 2 | Expose `client_links` |
| `tests/test_topology.py` (create) | 1, 2 | Builder + helper unit tests, sanitised live-layout fixture |
| `tests/test_websocket_api.py` (create) | 1 | WS command tests |
| `tests/test_coordinators.py` (modify) | 1, 2 | Uplink block merge; `client_links` fetch |
| `tests/test_diagnostics.py` (modify) | 1, 2 | MAC placeholdering of new data |

---

### Task 0: Implementation worktree

**Files:** none (git only)

- [ ] **Step 1: Create the worktree and PR 1 branch**

```bash
cd /home/tacoriffic/ha-unifi-insights
git fetch upstream
git worktree add -b feat/topology-graph ../ha-unifi-insights-topo-impl upstream/main
cd ../ha-unifi-insights-topo-impl && git log -1 --oneline
```
Expected: HEAD is `upstream/main` (`9ef4580` or newer).

- [ ] **Step 2: Prove the test harness works from this worktree**

```bash
cd /home/tacoriffic/ha-unifi-insights-topo-impl
PY=/home/tacoriffic/ha-unifi-insights/.local/ha-test-venv-ci/bin/python
$PY -m pytest tests/test_diagnostics.py -q --no-cov
```
Expected: all pass. If imports resolve to the other checkout, stop and report — do not continue.

---

### Task 1: Legacy uplink block on devices (PR 1)

**Files:**
- Modify: `custom_components/unifi_insights/coordinators/device.py` (add two classmethods after `_merge_legacy_port_data`; call site in `_process_site` loop `if legacy_devices_by_mac and not legacy_as_primary:`; `_legacy_device_to_v1_dict` before `return mapped`)
- Test: `tests/test_coordinators.py` (inside `class TestUnifiDeviceCoordinator`), `tests/test_diagnostics.py`

**Interfaces:**
- Produces: every device dict may carry `device["topology"]: dict[str, Any]` with optional keys `legacy_type: str` (lower-case), `uplink_mac: str` (lower-case), `uplink_remote_port: int`, `uplink_port_idx: int`, `uplink_type: str` (lower-case, e.g. `wire`/`wireless`), `uplink_speed: int`. Absent entirely when the legacy record has none of them.
- Produces: `UnifiDeviceCoordinator._legacy_topology_block(legacy: dict[str, Any]) -> dict[str, Any]` and `UnifiDeviceCoordinator._merge_legacy_uplink_data(device_dict, legacy_devices_by_mac) -> None` (both classmethods).

- [ ] **Step 1: Write the failing tests** — append to `class TestUnifiDeviceCoordinator` in `tests/test_coordinators.py`:

```python
    def test_legacy_topology_block_reads_uplink(self):
        """The parent link and legacy type are copied from /stat/device."""
        block = UnifiDeviceCoordinator._legacy_topology_block(
            {
                "mac": "58:d6:1f:00:00:02",
                "type": "USW",
                "uplink": {
                    "uplink_mac": "28:70:4E:00:00:01",
                    "uplink_remote_port": 6,
                    "port_idx": 8,
                    "type": "wire",
                    "speed": 1000,
                    "ip": "10.1.0.105",
                    "mac": "58:d6:1f:00:00:02",
                },
            }
        )

        assert block == {
            "legacy_type": "usw",
            "uplink_mac": "28:70:4e:00:00:01",
            "uplink_remote_port": 6,
            "uplink_port_idx": 8,
            "uplink_type": "wire",
            "uplink_speed": 1000,
        }

    def test_legacy_topology_block_falls_back_to_last_uplink(self):
        """An offline device keeps its parent through last_uplink."""
        block = UnifiDeviceCoordinator._legacy_topology_block(
            {
                "type": "uap",
                "uplink": {"type": "wire"},
                "last_uplink": {
                    "uplink_mac": "28:70:4e:00:00:01",
                    "uplink_remote_port": 20,
                    "port_idx": 1,
                    "type": "wire",
                },
            }
        )

        assert block["uplink_mac"] == "28:70:4e:00:00:01"
        assert block["uplink_remote_port"] == 20
        assert block["uplink_port_idx"] == 1

    def test_legacy_topology_block_gateway_and_garbage(self):
        """A gateway has a type but no parent; malformed values are dropped."""
        assert UnifiDeviceCoordinator._legacy_topology_block(
            {"type": "udm", "uplink": {"type": "wire", "speed": 2500}}
        ) == {"legacy_type": "udm", "uplink_type": "wire", "uplink_speed": 2500}
        assert (
            UnifiDeviceCoordinator._legacy_topology_block(
                {
                    "type": "",
                    "uplink": {
                        "uplink_mac": 5,
                        "uplink_remote_port": True,
                        "speed": "fast",
                    },
                }
            )
            == {}
        )

    def test_merge_legacy_uplink_data_matches_by_mac(self):
        """The block lands on the v1 device whose MAC matches, case-insensitively."""
        device = {"id": "uuid-child", "macAddress": "58:D6:1F:00:00:02", "uplink": None}
        legacy = {
            "mac": "58:d6:1f:00:00:02",
            "type": "usw",
            "uplink": {"uplink_mac": "28:70:4e:00:00:01", "uplink_remote_port": 6},
        }

        UnifiDeviceCoordinator._merge_legacy_uplink_data(
            device, {"58:d6:1f:00:00:02": legacy}
        )

        assert device["topology"]["uplink_mac"] == "28:70:4e:00:00:01"
        # The v1 field is left alone.
        assert device["uplink"] is None

    def test_merge_legacy_uplink_data_without_match_is_noop(self):
        """No legacy record, or an empty block, adds nothing."""
        device = {"id": "uuid-x", "macAddress": "aa:bb:cc:dd:ee:ff"}
        UnifiDeviceCoordinator._merge_legacy_uplink_data(device, {})
        UnifiDeviceCoordinator._merge_legacy_uplink_data(
            device, {"aa:bb:cc:dd:ee:ff": {"mac": "aa:bb:cc:dd:ee:ff"}}
        )
        assert "topology" not in device

    def test_legacy_device_to_v1_dict_carries_topology(
        self, coordinator: UnifiDeviceCoordinator
    ):
        """The legacy-only fallback produces the same block as the merge path."""
        mapped = coordinator._legacy_device_to_v1_dict(
            {
                "_id": "60a1b2c3d4e5f67890123456",
                "mac": "58:d6:1f:00:00:02",
                "type": "usw",
                "uplink": {"uplink_mac": "28:70:4e:00:00:01", "port_idx": 8},
            }
        )

        assert mapped["topology"] == {
            "legacy_type": "usw",
            "uplink_mac": "28:70:4e:00:00:01",
            "uplink_port_idx": 8,
        }

    @pytest.mark.asyncio
    async def test_process_site_merges_legacy_uplink(
        self, coordinator: UnifiDeviceCoordinator
    ):
        """The real refresh path attaches the block to v1 devices."""
        coordinator.network_client.devices.get_all = AsyncMock(
            return_value=[
                {
                    "id": "uuid-child",
                    "name": "Ultra",
                    "model": "USW Ultra",
                    "macAddress": "58:d6:1f:00:00:02",
                    "state": "ONLINE",
                    "uplink": None,
                }
            ]
        )
        coordinator.network_client.devices.get_legacy_site_devices = AsyncMock(
            return_value=[
                {
                    "_id": "legacy-child",
                    "mac": "58:d6:1f:00:00:02",
                    "type": "usw",
                    "uplink": {
                        "uplink_mac": "28:70:4e:00:00:01",
                        "uplink_remote_port": 6,
                    },
                }
            ]
        )

        devices_dict, _stats, _clients = await coordinator._process_site(
            "default", legacy_site_name="default"
        )

        assert devices_dict["uuid-child"]["topology"] == {
            "legacy_type": "usw",
            "uplink_mac": "28:70:4e:00:00:01",
            "uplink_remote_port": 6,
        }
```

Append to `tests/test_diagnostics.py`:

```python
async def test_diagnostics_placeholders_topology_uplink_mac(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    enable_custom_integrations,
) -> None:
    """The copied legacy parent MAC is placeholdered like every other MAC."""
    coordinator = init_integration.runtime_data.coordinator
    coordinator.data["devices"] = {
        "site-1": {
            "uuid-child": {
                "name": "Ultra",
                "macAddress": "58:d6:1f:00:00:02",
                "topology": {
                    "legacy_type": "usw",
                    "uplink_mac": "28:70:4e:00:00:01",
                    "uplink_remote_port": 6,
                },
            },
            "uuid-parent": {"name": "Core", "macAddress": "28:70:4e:00:00:01"},
        }
    }

    diagnostics = await async_get_config_entry_diagnostics(hass, init_integration)
    devices = diagnostics["data"]["devices"]["site-1"]
    uplink_mac = devices["uuid-child"]["topology"]["uplink_mac"]

    assert uplink_mac.startswith("**REDACTED-MAC-")
    # Same MAC, same placeholder: the parent link stays traceable.
    assert uplink_mac == devices["uuid-parent"]["macAddress"]
    assert devices["uuid-child"]["topology"]["uplink_remote_port"] == 6
    assert "28:70:4e:00:00:01" not in _strings(diagnostics)
```

Note: if `diagnostics["data"]["devices"]` is keyed by redacted ids (the `id` key is redacted, but dict keys are not unless MAC-shaped), the UUID keys above stay as-is. If the assertion on key names fails, print the structure once and adjust the lookup — do not change production code for it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PY -m pytest tests/test_coordinators.py -k "topology or legacy_uplink" tests/test_diagnostics.py::test_diagnostics_placeholders_topology_uplink_mac -q --no-cov`
Expected: FAIL — `AttributeError: type object 'UnifiDeviceCoordinator' has no attribute '_legacy_topology_block'` (the diagnostics test already passes because placeholdering is recursive — that is expected; it pins the behaviour).

- [ ] **Step 3: Implement** — in `coordinators/device.py`, add after `_merge_legacy_port_data`:

```python
    @staticmethod
    def _strict_int(value: Any) -> int | None:
        """Return value when it is a real int (not a bool), else None."""
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value

    @classmethod
    def _legacy_topology_block(cls, legacy: dict[str, Any]) -> dict[str, Any]:
        """
        Extract the parent-link fields topology needs from a legacy device.

        The v1 API leaves ``uplink`` and ``type`` null on current firmware, so
        the classic ``/stat/device`` record is the only source of which device
        (and port) this one hangs off. ``last_uplink`` keeps the same keys when
        the device is offline and ``uplink`` has been emptied.
        """
        block: dict[str, Any] = {}

        legacy_type = legacy.get("type")
        if isinstance(legacy_type, str) and legacy_type:
            block["legacy_type"] = legacy_type.lower()

        uplink = legacy.get("uplink")
        link = uplink if isinstance(uplink, dict) else {}
        if cls._normalize_mac(link.get("uplink_mac")) is None:
            last_uplink = legacy.get("last_uplink")
            if isinstance(last_uplink, dict) and cls._normalize_mac(
                last_uplink.get("uplink_mac")
            ):
                link = {**link, **last_uplink}

        uplink_mac = cls._normalize_mac(link.get("uplink_mac"))
        if uplink_mac is not None:
            block["uplink_mac"] = uplink_mac
        for source_key, block_key in (
            ("uplink_remote_port", "uplink_remote_port"),
            ("port_idx", "uplink_port_idx"),
            ("speed", "uplink_speed"),
        ):
            value = cls._strict_int(link.get(source_key))
            if value is not None:
                block[block_key] = value
        uplink_type = link.get("type")
        if isinstance(uplink_type, str) and uplink_type:
            block["uplink_type"] = uplink_type.lower()

        return block

    @classmethod
    def _merge_legacy_uplink_data(
        cls,
        device_dict: dict[str, Any],
        legacy_devices_by_mac: dict[str, dict[str, Any]],
    ) -> None:
        """Attach the legacy parent link to a v1 device as ``topology``."""
        legacy_device = cls._legacy_device_for(device_dict, legacy_devices_by_mac)
        if legacy_device is None:
            return
        block = cls._legacy_topology_block(legacy_device)
        if block:
            device_dict["topology"] = block
```

`_normalize_mac` returns `None` for non-strings and empty strings, so `uplink_mac: 5` is dropped. `_legacy_device_for` already exists (reads `mac`/`macAddress` and normalises).

Call site — in `_process_site`, extend the merge loop:

```python
        if legacy_devices_by_mac and not legacy_as_primary:
            for device in devices:
                self._merge_legacy_temperature_data(device, legacy_devices_by_mac)
                self._merge_legacy_port_data(device, legacy_devices_by_mac)
                self._merge_legacy_outlet_data(device, legacy_devices_by_mac)
                self._merge_legacy_uplink_data(device, legacy_devices_by_mac)
```

In `_legacy_device_to_v1_dict`, immediately before `return mapped`:

```python
        # Same parent-link block the merge path produces, so topology reads
        # one shape whichever endpoint served the device list.
        topology = cls._legacy_topology_block(legacy)
        if topology:
            mapped["topology"] = topology
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PY -m pytest tests/test_coordinators.py tests/test_diagnostics.py -q --no-cov`
Expected: PASS (whole files — nothing else regressed).

- [ ] **Step 5: Lint + commit**

```bash
uvx ruff@0.16.7 check custom_components/unifi_insights/coordinators/device.py tests/test_coordinators.py tests/test_diagnostics.py
uvx ruff@0.16.7 format --check custom_components/unifi_insights/coordinators/device.py tests/test_coordinators.py tests/test_diagnostics.py
git add custom_components/unifi_insights/coordinators/device.py tests/test_coordinators.py tests/test_diagnostics.py
git commit -m "feat(coordinator): keep the legacy uplink as a topology block

The v1 devices endpoint returns uplink=null and type=null on current
firmware, so the only record of which device and port a switch or AP hangs
off is the classic /stat/device uplink - already fetched every poll and
then discarded. Keep the parent MAC, ports, medium, speed and legacy type
under one namespaced key for the topology builder."
```

---

### Task 2: Topology contract and pure helpers (PR 1)

**Files:**
- Create: `custom_components/unifi_insights/topology.py`
- Test: `tests/test_topology.py`

**Interfaces:**
- Produces (all in `custom_components.unifi_insights.topology`):
  - constants `TOPOLOGY_SCHEMA_VERSION: Final = 1`, `MAX_CLIENTS_PER_SITE: Final = 500`
  - TypedDicts `TopologyNode`, `TopologyEdge`, `TopologyIssue`, `TopologyUnresolved`, `TopologyTruncation`, `SiteTopology` (fields exactly as below)
  - `normalize_mac(value: Any) -> str | None`
  - `opaque_node_id(prefix: str, entry_id: str, raw_id: str) -> str`
  - `device_kind(device: Mapping[str, Any]) -> NodeKind`
  - `device_state(device: Mapping[str, Any]) -> NodeState`
  - `site_display_name(data: Mapping[str, Any], site_id: str) -> str`

- [ ] **Step 1: Write the failing tests** — create `tests/test_topology.py`:

```python
"""Tests for the topology graph builder."""

from __future__ import annotations

import pytest

from custom_components.unifi_insights.topology import (
    device_kind,
    device_state,
    normalize_mac,
    opaque_node_id,
    site_display_name,
)

ENTRY = "entry-1"
SITE = "site-1"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("28:70:4E:C1:A6:13", "28:70:4e:c1:a6:13"),
        ("28-70-4e-c1-a6-13", "28:70:4e:c1:a6:13"),
        ("28704ec1a613", "28:70:4e:c1:a6:13"),
        (" 28:70:4e:c1:a6:13 ", "28:70:4e:c1:a6:13"),
        ("dc4eaf35-9daf-352c-9e34-2e428120ff1a", None),
        ("69d19121c4862038869ff37f", None),
        ("device1", None),
        ("", None),
        (None, None),
        (42, None),
    ],
)
def test_normalize_mac(value, expected) -> None:
    """Only MAC-shaped strings normalise; UUIDs and legacy ids do not."""
    assert normalize_mac(value) == expected


def test_opaque_node_id_keeps_uuid_and_hashes_mac() -> None:
    """UUIDs pass through; MAC-shaped ids never appear in the node id."""
    assert opaque_node_id("dev", ENTRY, "uuid-1") == "dev:uuid-1"
    hashed = opaque_node_id("dev", ENTRY, "AA:BB:CC:DD:EE:FF")
    assert hashed.startswith("dev:h")
    assert len(hashed) == len("dev:h") + 16
    assert "aa:bb" not in hashed.lower()
    # Stable across spellings of the same MAC, scoped per entry.
    assert hashed == opaque_node_id("dev", ENTRY, "aabbccddeeff")
    assert hashed != opaque_node_id("dev", "entry-2", "aabbccddeeff")


@pytest.mark.parametrize(
    ("device", "expected"),
    [
        ({"topology": {"legacy_type": "udm"}, "features": ["switching"]}, "gateway"),
        ({"topology": {"legacy_type": "uxg"}}, "gateway"),
        ({"topology": {"legacy_type": "ugw"}}, "gateway"),
        ({"topology": {"legacy_type": "udr"}}, "gateway"),
        ({"topology": {"legacy_type": "ucg"}}, "gateway"),
        ({"topology": {"legacy_type": "usw"}}, "switch"),
        ({"topology": {"legacy_type": "uap"}}, "access_point"),
        ({"type": "GATEWAY"}, "gateway"),
        ({"type": "switch"}, "switch"),
        ({"type": "accessPoint"}, "access_point"),
        ({"features": ["accessPoint"]}, "access_point"),
        ({"features": ["switching"]}, "switch"),
        ({"topology": {"legacy_type": "uph"}}, "other"),
        ({}, "other"),
    ],
)
def test_device_kind(device, expected) -> None:
    """Legacy type wins, then v1 type, then features, then other."""
    assert device_kind(device) == expected


@pytest.mark.parametrize(
    ("device", "expected"),
    [
        ({"state": "ONLINE"}, "online"),
        ({"state": "connected"}, "online"),
        ({"status": "UP"}, "online"),
        ({"state": "OFFLINE"}, "offline"),
        ({"state": "DISCONNECTED"}, "offline"),
        ({"state": "PENDING_ADOPTION"}, "unknown"),
        ({"state": 1}, "unknown"),
        ({}, "unknown"),
    ],
)
def test_device_state(device, expected) -> None:
    """Device state strings map onto the three contract states."""
    assert device_state(device) == expected


def test_site_display_name() -> None:
    """Site name falls back to description, then to the id."""
    data = {
        "sites": {
            "a": {"name": "Home"},
            "b": {"name": "", "desc": "Office"},
            "c": {},
        }
    }
    assert site_display_name(data, "a") == "Home"
    assert site_display_name(data, "b") == "Office"
    assert site_display_name(data, "c") == "c"
    assert site_display_name(data, "missing") == "missing"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PY -m pytest tests/test_topology.py -q --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'custom_components.unifi_insights.topology'`.

- [ ] **Step 3: Implement** — create `custom_components/unifi_insights/topology.py`:

```python
"""
Per-site network topology graph derived from coordinator data.

This module is pure: it performs no I/O and imports nothing from Home
Assistant or the rest of the integration, so the graph logic is unit-testable
in isolation and cheap enough to run on every coordinator update.
(``coordinators/config.py`` imports ``normalize_mac`` from here, so importing
``.entity`` or ``.coordinators`` would create an import cycle.)

Relationship sources, verified against real hardware:

* Device -> parent device comes from the classic ``/stat/device`` ``uplink``
  block, which the device coordinator copies onto each device as
  ``device["topology"]``. The v1 API leaves ``uplink`` and ``type`` null on
  current firmware, so they are only fallbacks.
* Client -> device comes from the v1 client ``uplinkDeviceId``.

The coordinator only holds clients the controller currently reports, so
offline clients never appear in the graph.

The snapshot is an allowlisted contract for the frontend: MAC addresses, IP
addresses, hostnames, firmware and traffic counters are never emitted, and
MAC-shaped identifiers are replaced by opaque hashes.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Any, Final, Literal, NotRequired, TypedDict

if TYPE_CHECKING:
    from collections.abc import Mapping

TOPOLOGY_SCHEMA_VERSION: Final = 1
# Hard server-side cap on client nodes per site; requests may ask for fewer.
MAX_CLIENTS_PER_SITE: Final = 500

NodeKind = Literal["gateway", "switch", "access_point", "client", "other"]
NodeState = Literal["online", "offline", "unknown"]
LinkMedium = Literal["wired", "wireless", "unknown"]
ClientConnection = Literal["wired", "wireless"]
TopologyStatus = Literal["ok", "partial", "unavailable"]
IssueSeverity = Literal["info", "warning", "error"]
UnresolvedReason = Literal["parent_not_found", "no_uplink_data"]


class TopologyNode(TypedDict):
    """A device or client in the graph."""

    id: str
    kind: NodeKind
    name: str
    state: NodeState
    model: NotRequired[str]
    ha_device_id: NotRequired[str]
    connection: NotRequired[ClientConnection]


class TopologyEdge(TypedDict):
    """A child -> parent link."""

    source: str
    target: str
    medium: LinkMedium
    speed_mbps: NotRequired[int]
    parent_port: NotRequired[int]
    child_port: NotRequired[int]
    poe_power_w: NotRequired[float]


class TopologyIssue(TypedDict):
    """A machine-readable problem with the snapshot."""

    code: str
    severity: IssueSeverity


class TopologyUnresolved(TypedDict):
    """A node whose parent could not be placed in the graph."""

    node_id: str
    reason: UnresolvedReason


class TopologyTruncation(TypedDict):
    """How many clients were left out by the client cap."""

    clients_total: int
    clients_included: int


class SiteTopology(TypedDict):
    """One site's topology snapshot (contract version 1)."""

    schema_version: int
    entry_id: str
    site_id: str
    site_name: str
    revision: str
    status: TopologyStatus
    issues: list[TopologyIssue]
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]
    unresolved: list[TopologyUnresolved]
    truncation: TopologyTruncation | None


_GATEWAY_LEGACY_TYPES: Final = frozenset({"udm", "uxg", "ugw", "udr", "ucg"})
_ONLINE_STATES: Final = frozenset({"ONLINE", "CONNECTED", "UP"})
_OFFLINE_STATES: Final = frozenset({"OFFLINE", "DISCONNECTED", "DOWN"})
_MAC_RE: Final = re.compile(r"[0-9a-f]{2}(?:[:-]?[0-9a-f]{2}){5}")


def _field(data: Mapping[str, Any], *keys: str) -> Any:
    """Return the first non-None value among ``keys`` (get_field semantics)."""
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return None


def normalize_mac(value: Any) -> str | None:
    """Return ``value`` as a lower-case colon MAC, or None if it is not one."""
    if not isinstance(value, str):
        return None
    candidate = value.strip().lower()
    if not _MAC_RE.fullmatch(candidate):
        return None
    digits = candidate.replace(":", "").replace("-", "")
    return ":".join(digits[index : index + 2] for index in range(0, 12, 2))


def opaque_node_id(prefix: str, entry_id: str, raw_id: str) -> str:
    """Return a node id that never exposes a MAC address."""
    mac = normalize_mac(raw_id)
    if mac is None:
        return f"{prefix}:{raw_id}"
    digest = hashlib.sha256(f"{entry_id}:{mac}".encode()).hexdigest()[:16]
    return f"{prefix}:h{digest}"


def device_kind(device: Mapping[str, Any]) -> NodeKind:
    """Classify a device: legacy type, then v1 type, then features."""
    topology = device.get("topology")
    legacy_type = topology.get("legacy_type") if isinstance(topology, dict) else None
    if isinstance(legacy_type, str):
        lowered = legacy_type.lower()
        if lowered in _GATEWAY_LEGACY_TYPES:
            return "gateway"
        if lowered == "usw":
            return "switch"
        if lowered == "uap":
            return "access_point"

    v1_type = device.get("type")
    if isinstance(v1_type, str):
        lowered = v1_type.lower()
        if "gateway" in lowered:
            return "gateway"
        if "switch" in lowered:
            return "switch"
        if "access" in lowered or lowered in {"ap", "uap"}:
            return "access_point"

    features = device.get("features")
    if isinstance(features, list):
        if "accessPoint" in features:
            return "access_point"
        if "switching" in features:
            return "switch"
    return "other"


def device_state(device: Mapping[str, Any]) -> NodeState:
    """Map a device state string onto online/offline/unknown."""
    raw = _field(device, "state", "status")
    if isinstance(raw, str):
        upper = raw.upper()
        if upper in _ONLINE_STATES:
            return "online"
        if upper in _OFFLINE_STATES:
            return "offline"
    return "unknown"


def site_display_name(data: Mapping[str, Any], site_id: str) -> str:
    """Return a site's display name, falling back to its id."""
    sites = data.get("sites")
    site = sites.get(site_id) if isinstance(sites, dict) else None
    if isinstance(site, dict):
        for key in ("name", "desc"):
            value = site.get(key)
            if isinstance(value, str) and value:
                return value
    return site_id
```

(`hashlib`/`json` are used by Task 3 — if ruff flags `json` as unused now, add it in Task 3 instead.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PY -m pytest tests/test_topology.py -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uvx ruff@0.16.7 check custom_components/unifi_insights/topology.py tests/test_topology.py
uvx ruff@0.16.7 format --check custom_components/unifi_insights/topology.py tests/test_topology.py
$PY -m mypy custom_components/unifi_insights
git add custom_components/unifi_insights/topology.py tests/test_topology.py
git commit -m "feat(topology): contract types and pure classification helpers

Versioned (schema 1) TypedDict contract the frontend card will consume, plus
MAC normalisation, opaque node ids that never carry a MAC, and device
kind/state classification that prefers the legacy type because v1 type is
null on real hardware."
```

---

### Task 3: Graph builder (PR 1)

**Files:**
- Modify: `custom_components/unifi_insights/topology.py` (append)
- Test: `tests/test_topology.py` (append)

**Interfaces:**
- Consumes: Task 1 `device["topology"]` keys; Task 2 helpers and types.
- Produces:
  - `build_site_topology(data: Mapping[str, Any], entry_id: str, site_id: str, *, ha_device_ids: Mapping[str, str], max_clients: int = MAX_CLIENTS_PER_SITE, devices_available: bool = True) -> SiteTopology`
  - `build_unavailable_topology(entry_id: str, site_id: str, site_name: str, issue_code: str) -> SiteTopology`
  - Issue codes: `devices_unavailable` (error), `legacy_uplink_missing` (warning), `parents_unresolved` (warning), `clients_truncated` (info). Task 6 adds usage of `entry_unloaded` (error) via `build_unavailable_topology`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_topology.py` (extend the import to `MAX_CLIENTS_PER_SITE, build_site_topology, build_unavailable_topology`, plus `import json` and `import random` at top):

```python
GW_MAC = "02:00:00:00:00:01"
CORE_MAC = "02:00:00:00:00:02"


def _device(
    device_id: str,
    name: str,
    *,
    mac: str,
    legacy_type: str | None = None,
    uplink_mac: str | None = None,
    remote_port: int | None = None,
    port_idx: int | None = None,
    speed: int | None = None,
    model: str = "USW",
    state: str = "ONLINE",
    ports: list[dict] | None = None,
    features: list[str] | None = None,
) -> dict:
    """Return a coordinator-shaped device (keys as seen live on VM113)."""
    device = {
        "id": device_id,
        "name": name,
        "model": model,
        "macAddress": mac,
        "ipAddress": "10.1.0.9",
        "firmwareVersion": "7.4.2.1039",
        "state": state,
        "type": None,
        "uplink": None,
        "features": features if features is not None else ["switching"],
        "ports": ports or [],
    }
    topology: dict = {}
    if legacy_type is not None:
        topology["legacy_type"] = legacy_type
    if uplink_mac is not None:
        topology["uplink_mac"] = uplink_mac
        topology["uplink_type"] = "wire"
    if remote_port is not None:
        topology["uplink_remote_port"] = remote_port
    if port_idx is not None:
        topology["uplink_port_idx"] = port_idx
    if speed is not None:
        topology["uplink_speed"] = speed
    if topology:
        device["topology"] = topology
    return device


def _client(
    client_id: str,
    name: str,
    *,
    uplink: str | None,
    wired: bool = True,
    mac: str = "11:22:33:44:55:66",
) -> dict:
    """Return a coordinator-shaped v1 client."""
    return {
        "id": client_id,
        "name": name,
        "hostname": f"{name.lower()}-host",
        "macAddress": mac,
        "ipAddress": "10.2.0.5",
        "type": "WIRED" if wired else "WIRELESS",
        "connected": True,
        "uplinkDeviceId": uplink,
        "swMac": None,
        "swPort": None,
        "vlan": None,
    }


def _data(devices: dict, clients: dict | None = None) -> dict:
    """Wrap one site's devices/clients in facade-shaped data."""
    return {
        "sites": {SITE: {"id": SITE, "name": "Home"}},
        "devices": {SITE: devices},
        "clients": {SITE: clients or {}},
    }


def _live_layout() -> dict:
    """Sanitised copy of the VM113 layout (fictitious MACs and names)."""
    devices = {
        "uuid-gw": _device(
            "uuid-gw",
            "Gateway",
            mac=GW_MAC,
            legacy_type="udm",
            model="UDM Pro SE",
        ),
        "uuid-core": _device(
            "uuid-core",
            "Core 24",
            mac=CORE_MAC,
            legacy_type="usw",
            uplink_mac=GW_MAC,
            remote_port=11,
            port_idx=26,
            speed=10000,
            model="USW Pro Max 24",
            ports=[
                {"idx": 20, "port_idx": 20, "poe": {"enabled": True, "power": "12.34"}},
                {"idx": 8, "port_idx": 8, "poe": {"enabled": False, "power": "0.00"}},
                {"idx": 26, "port_idx": 26, "is_uplink": True},
            ],
        ),
    }
    children = [
        ("uuid-u1", "Ultra A", "02:00:00:00:00:03", 6, 1000, "usw", ["switching"]),
        ("uuid-pdu", "PDU", "02:00:00:00:00:04", 8, 100, "usw", ["switching"]),
        ("uuid-u2", "Ultra B", "02:00:00:00:00:05", 10, 1000, "usw", ["switching"]),
        ("uuid-lite", "Lite 8", "02:00:00:00:00:06", 12, 1000, "usw", ["switching"]),
        ("uuid-flex", "Flex", "02:00:00:00:00:07", 17, 2500, "usw", ["switching"]),
        ("uuid-ap", "AP", "02:00:00:00:00:08", 20, 2500, "uap", ["accessPoint"]),
    ]
    for device_id, name, mac, port, speed, legacy_type, features in children:
        devices[device_id] = _device(
            device_id,
            name,
            mac=mac,
            legacy_type=legacy_type,
            uplink_mac=CORE_MAC,
            remote_port=port,
            speed=speed,
            features=features,
            ports=[{"idx": 1, "port_idx": 1, "is_uplink": True}],
        )
    clients = {
        "cli-tv": _client("cli-tv", "TV", uplink="uuid-u1", mac="12:00:00:00:00:01"),
        "cli-phone": _client(
            "cli-phone", "Phone", uplink="uuid-ap", wired=False, mac="12:00:00:00:00:02"
        ),
    }
    return _data(devices, clients)


def _build(data: dict, **kwargs):
    kwargs.setdefault("ha_device_ids", {})
    return build_site_topology(data, ENTRY, SITE, **kwargs)


def _edge(snapshot, source: str) -> dict:
    (edge,) = [edge for edge in snapshot["edges"] if edge["source"] == source]
    return edge


def test_live_layout_builds_the_tree() -> None:
    """Every switch/AP hangs off the core; the core hangs off the gateway."""
    snapshot = _build(_live_layout())

    assert snapshot["schema_version"] == 1
    assert snapshot["status"] == "ok"
    assert snapshot["issues"] == []
    assert snapshot["unresolved"] == []
    device_edges = {
        edge["source"]: edge["target"]
        for edge in snapshot["edges"]
        if edge["source"].startswith("dev:")
    }
    assert device_edges == {
        "dev:uuid-core": "dev:uuid-gw",
        "dev:uuid-u1": "dev:uuid-core",
        "dev:uuid-pdu": "dev:uuid-core",
        "dev:uuid-u2": "dev:uuid-core",
        "dev:uuid-lite": "dev:uuid-core",
        "dev:uuid-flex": "dev:uuid-core",
        "dev:uuid-ap": "dev:uuid-core",
    }
    kinds = {node["id"]: node["kind"] for node in snapshot["nodes"]}
    assert kinds["dev:uuid-gw"] == "gateway"
    assert kinds["dev:uuid-ap"] == "access_point"
    assert kinds["dev:uuid-core"] == "switch"


def test_device_edge_enrichment() -> None:
    """Ports, speed, medium and PoE draw ride on the device edge."""
    snapshot = _build(_live_layout())

    assert _edge(snapshot, "dev:uuid-core") == {
        "source": "dev:uuid-core",
        "target": "dev:uuid-gw",
        "medium": "wired",
        "speed_mbps": 10000,
        "parent_port": 11,
        "child_port": 26,
    }
    ap_edge = _edge(snapshot, "dev:uuid-ap")
    assert ap_edge["poe_power_w"] == 12.3
    # Child port falls back to the port flagged is_uplink.
    assert ap_edge["child_port"] == 1
    # PoE disabled on the parent port -> no wattage (not a fake 0.0).
    assert "poe_power_w" not in _edge(snapshot, "dev:uuid-pdu")


def test_client_edges_and_nodes() -> None:
    """Clients attach through uplinkDeviceId with their connection medium."""
    snapshot = _build(_live_layout())

    assert _edge(snapshot, "cli:cli-tv") == {
        "source": "cli:cli-tv",
        "target": "dev:uuid-u1",
        "medium": "wired",
    }
    assert _edge(snapshot, "cli:cli-phone")["medium"] == "wireless"
    phone = next(node for node in snapshot["nodes"] if node["id"] == "cli:cli-phone")
    assert phone == {
        "id": "cli:cli-phone",
        "kind": "client",
        "name": "Phone",
        "state": "online",
        "connection": "wireless",
    }


def test_every_edge_endpoint_exists_in_nodes() -> None:
    """The graph never references a node it did not emit."""
    data = _live_layout()
    data["devices"][SITE]["uuid-orphan"] = _device(
        "uuid-orphan", "Orphan", mac="02:00:00:00:00:99", uplink_mac="02:ff:ff:ff:ff:ff"
    )
    data["clients"][SITE]["cli-lost"] = _client("cli-lost", "Lost", uplink="uuid-nope")
    snapshot = _build(data)

    node_ids = {node["id"] for node in snapshot["nodes"]}
    for edge in snapshot["edges"]:
        assert edge["source"] in node_ids
        assert edge["target"] in node_ids


def test_missing_parent_is_unresolved() -> None:
    """A parent MAC that matches nothing becomes an unresolved entry."""
    data = _live_layout()
    data["devices"][SITE]["uuid-orphan"] = _device(
        "uuid-orphan", "Orphan", mac="02:00:00:00:00:99", uplink_mac="02:ff:ff:ff:ff:ff"
    )
    snapshot = _build(data)

    assert {"node_id": "dev:uuid-orphan", "reason": "parent_not_found"} in snapshot[
        "unresolved"
    ]
    assert not [e for e in snapshot["edges"] if e["source"] == "dev:uuid-orphan"]
    assert snapshot["status"] == "partial"
    assert {"code": "parents_unresolved", "severity": "warning"} in snapshot["issues"]


def test_client_unresolved_reasons() -> None:
    """Unknown uplink -> parent_not_found; missing uplink -> no_uplink_data."""
    data = _data(
        {"uuid-gw": _device("uuid-gw", "Gateway", mac=GW_MAC, legacy_type="udm")},
        {
            "cli-a": _client("cli-a", "A", uplink="uuid-nope"),
            "cli-b": _client("cli-b", "B", uplink=None),
        },
    )
    snapshot = _build(data)

    assert snapshot["unresolved"] == [
        {"node_id": "cli:cli-a", "reason": "parent_not_found"},
        {"node_id": "cli:cli-b", "reason": "no_uplink_data"},
    ]


def test_gateway_without_uplink_is_root() -> None:
    """A lone gateway is a healthy one-node graph, not an unresolved node."""
    snapshot = _build(
        _data({"uuid-gw": _device("uuid-gw", "Gateway", mac=GW_MAC, legacy_type="udm")})
    )

    assert snapshot["status"] == "ok"
    assert snapshot["unresolved"] == []
    assert snapshot["edges"] == []


def test_self_edge_is_skipped() -> None:
    """A device that claims itself as parent gets no edge."""
    snapshot = _build(
        _data(
            {
                "uuid-sw": _device(
                    "uuid-sw", "Loop", mac=CORE_MAC, legacy_type="usw", uplink_mac=CORE_MAC
                )
            }
        )
    )

    assert snapshot["edges"] == []


def test_legacy_missing_is_partial_not_crash() -> None:
    """Without any legacy blocks, devices and clients still render."""
    data = _data(
        {
            "uuid-gw": _device("uuid-gw", "Gateway", mac=GW_MAC, features=["switching"]),
            "uuid-ap": _device(
                "uuid-ap", "AP", mac="02:00:00:00:00:08", features=["accessPoint"]
            ),
        },
        {"cli-a": _client("cli-a", "A", uplink="uuid-ap", wired=False)},
    )
    snapshot = _build(data)

    assert snapshot["status"] == "partial"
    codes = {issue["code"] for issue in snapshot["issues"]}
    assert codes == {"legacy_uplink_missing", "parents_unresolved"}
    assert _edge(snapshot, "cli:cli-a")["target"] == "dev:uuid-ap"
    assert {"node_id": "dev:uuid-ap", "reason": "no_uplink_data"} in snapshot[
        "unresolved"
    ]


def test_mac_keyed_device_resolves_and_is_opaque() -> None:
    """A device keyed by MAC still parents others and never leaks the MAC."""
    parent_mac = "aa:bb:cc:00:00:01"
    data = _data(
        {
            parent_mac: {
                "id": parent_mac,
                "name": "Old Switch",
                "state": "ONLINE",
                "topology": {"legacy_type": "usw", "uplink_mac": GW_MAC},
            },
            "uuid-gw": _device("uuid-gw", "Gateway", mac=GW_MAC, legacy_type="udm"),
            "uuid-ap": _device(
                "uuid-ap",
                "AP",
                mac="02:00:00:00:00:08",
                legacy_type="uap",
                uplink_mac=parent_mac.upper(),
            ),
        }
    )
    snapshot = _build(data)

    parent_node = opaque_node_id("dev", ENTRY, parent_mac)
    assert parent_node.startswith("dev:h")
    assert _edge(snapshot, "dev:uuid-ap")["target"] == parent_node
    assert _edge(snapshot, parent_node)["target"] == "dev:uuid-gw"
    assert "aa:bb:cc" not in json.dumps(snapshot).lower()


def test_client_name_mac_shaped_is_replaced() -> None:
    """A client whose name is its MAC, or blank, is rendered generically."""
    data = _data(
        {"uuid-gw": _device("uuid-gw", "Gateway", mac=GW_MAC, legacy_type="udm")},
        {
            "cli-a": _client("cli-a", "8c:ed:e1:a2:21:17", uplink="uuid-gw"),
            "cli-b": _client("cli-b", "   ", uplink="uuid-gw"),
        },
    )
    snapshot = _build(data)

    names = {n["id"]: n["name"] for n in snapshot["nodes"] if n["kind"] == "client"}
    assert names == {"cli:cli-a": "Unknown client", "cli:cli-b": "Unknown client"}


def test_allowlist_never_emits_sensitive_values() -> None:
    """No MAC, IP, hostname or firmware reaches the payload."""
    snapshot = _build(_live_layout())
    payload = json.dumps(snapshot)

    for forbidden in ("02:00:00", "12:00:00", "10.1.0.", "10.2.0.", "-host", "7.4.2"):
        assert forbidden not in payload
    node_keys = {key for node in snapshot["nodes"] for key in node}
    assert node_keys <= {"id", "kind", "name", "state", "model", "ha_device_id", "connection"}
    edge_keys = {key for edge in snapshot["edges"] for key in edge}
    assert edge_keys <= {
        "source",
        "target",
        "medium",
        "speed_mbps",
        "parent_port",
        "child_port",
        "poe_power_w",
    }


def test_ha_device_ids_are_attached() -> None:
    """Registry ids from the caller land on infrastructure nodes only."""
    snapshot = _build(_live_layout(), ha_device_ids={"uuid-core": "reg-core"})

    core = next(node for node in snapshot["nodes"] if node["id"] == "dev:uuid-core")
    assert core["ha_device_id"] == "reg-core"
    assert not [n for n in snapshot["nodes"] if n["kind"] == "client" and "ha_device_id" in n]


def test_client_cap_prefers_wired_and_reports_truncation() -> None:
    """Over the cap, wired clients are kept first and truncation is reported."""
    data = _data(
        {"uuid-gw": _device("uuid-gw", "Gateway", mac=GW_MAC, legacy_type="udm")},
        {
            "cli-w": _client("cli-w", "Aardvark", uplink="uuid-gw", wired=False),
            "cli-2": _client("cli-2", "Zulu", uplink="uuid-gw"),
            "cli-1": _client("cli-1", "Mike", uplink="uuid-gw"),
        },
    )
    snapshot = _build(data, max_clients=2)

    clients = [n["id"] for n in snapshot["nodes"] if n["kind"] == "client"]
    assert sorted(clients) == ["cli:cli-1", "cli:cli-2"]
    assert snapshot["truncation"] == {"clients_total": 3, "clients_included": 2}
    assert snapshot["status"] == "partial"
    assert {"code": "clients_truncated", "severity": "info"} in snapshot["issues"]

    none = _build(data, max_clients=0)
    assert [n for n in none["nodes"] if n["kind"] == "client"] == []
    assert none["truncation"] == {"clients_total": 3, "clients_included": 0}


def test_client_cap_is_clamped_to_hard_limit() -> None:
    """A request cannot raise the cap above MAX_CLIENTS_PER_SITE."""
    clients = {
        f"cli-{index}": _client(f"cli-{index}", f"C{index:04d}", uplink="uuid-gw")
        for index in range(MAX_CLIENTS_PER_SITE + 1)
    }
    data = _data(
        {"uuid-gw": _device("uuid-gw", "Gateway", mac=GW_MAC, legacy_type="udm")},
        clients,
    )
    snapshot = _build(data, max_clients=10_000)

    assert snapshot["truncation"] == {
        "clients_total": MAX_CLIENTS_PER_SITE + 1,
        "clients_included": MAX_CLIENTS_PER_SITE,
    }


def test_devices_unavailable() -> None:
    """A failed device coordinator or an unknown site reports unavailable."""
    snapshot = _build(_live_layout(), devices_available=False)
    assert snapshot["status"] == "unavailable"
    assert {"code": "devices_unavailable", "severity": "error"} in snapshot["issues"]

    missing = build_site_topology(_live_layout(), ENTRY, "other-site", ha_device_ids={})
    assert missing["status"] == "unavailable"
    assert missing["nodes"] == []


def test_multi_site_isolation() -> None:
    """Each site's graph only contains that site's devices and clients."""
    data = _live_layout()
    data["sites"]["site-2"] = {"id": "site-2", "name": "Cabin"}
    data["devices"]["site-2"] = {
        "uuid-cabin": _device("uuid-cabin", "Cabin GW", mac="06:00:00:00:00:01", legacy_type="udm")
    }
    data["clients"]["site-2"] = {}

    home = _build(data)
    cabin = build_site_topology(data, ENTRY, "site-2", ha_device_ids={})

    assert "dev:uuid-cabin" not in {n["id"] for n in home["nodes"]}
    assert [n["id"] for n in cabin["nodes"]] == ["dev:uuid-cabin"]
    assert cabin["site_name"] == "Cabin"


def test_deterministic_order_and_revision() -> None:
    """Insertion order does not matter; any content change moves the revision."""
    data = _live_layout()
    shuffled = _live_layout()
    items = list(shuffled["devices"][SITE].items())
    random.Random(4).shuffle(items)
    shuffled["devices"][SITE] = dict(items)

    first = _build(data)
    assert first == _build(shuffled)
    assert first["revision"] == _build(data)["revision"]
    assert len(first["revision"]) == 16
    assert [n["kind"] for n in first["nodes"]][0] == "gateway"

    data["devices"][SITE]["uuid-u1"]["name"] = "Renamed"
    assert _build(data)["revision"] != first["revision"]


def test_malformed_entries_are_skipped() -> None:
    """Non-dict devices/clients and non-dict site maps never crash the builder."""
    data = _live_layout()
    data["devices"][SITE]["bad"] = "not-a-dict"
    data["clients"][SITE]["bad"] = None
    snapshot = _build(data)
    assert "dev:bad" not in {n["id"] for n in snapshot["nodes"]}

    weird = {"sites": [], "devices": {SITE: []}, "clients": "x"}
    assert _build(weird)["nodes"] == []


def test_build_unavailable_topology() -> None:
    """The unavailable helper returns a valid, empty snapshot."""
    snapshot = build_unavailable_topology(ENTRY, SITE, "Home", "entry_unloaded")

    assert snapshot["status"] == "unavailable"
    assert snapshot["issues"] == [{"code": "entry_unloaded", "severity": "error"}]
    assert snapshot["nodes"] == snapshot["edges"] == snapshot["unresolved"] == []
    assert snapshot["truncation"] is None
    assert len(snapshot["revision"]) == 16
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PY -m pytest tests/test_topology.py -q --no-cov`
Expected: FAIL — `ImportError: cannot import name 'build_site_topology'`.

- [ ] **Step 3: Implement** — append to `topology.py`:

```python
_KIND_ORDER: Final[dict[str, int]] = {
    "gateway": 0,
    "switch": 1,
    "access_point": 2,
    "other": 3,
    "client": 4,
}
_UNKNOWN_CLIENT: Final = "Unknown client"
_UNKNOWN_DEVICE: Final = "Unknown device"


def _as_int(value: Any) -> int | None:
    """Return value when it is a real int (not a bool), else None."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _site_map(data: Mapping[str, Any], section: str, site_id: str) -> dict[str, Any]:
    """Return ``data[section][site_id]`` when it is a dict, else {}."""
    by_site = data.get(section)
    site_items = by_site.get(site_id) if isinstance(by_site, dict) else None
    return site_items if isinstance(site_items, dict) else {}


def _ports(device: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return a device's port dicts from ``ports`` or ``interfaces.ports``."""
    ports = device.get("ports")
    if not isinstance(ports, list):
        interfaces = device.get("interfaces")
        ports = interfaces.get("ports") if isinstance(interfaces, dict) else None
    if not isinstance(ports, list):
        return []
    return [port for port in ports if isinstance(port, dict)]


def _port_index(port: Mapping[str, Any]) -> int | None:
    """Return a port's index across the v1, interface and legacy shapes."""
    return _as_int(_field(port, "idx", "port_idx", "portIdx"))


def _uplink_port_index(device: Mapping[str, Any]) -> int | None:
    """Return the index of the port flagged as the device's uplink."""
    for port in _ports(device):
        if _field(port, "is_uplink", "isUplink") is True:
            return _port_index(port)
    return None


def _port_poe_watts(device: Mapping[str, Any], port_idx: int) -> float | None:
    """Return the PoE draw on one port, or None when PoE is off or unknown."""
    for port in _ports(device):
        if _port_index(port) != port_idx:
            continue
        poe = port.get("poe")
        if isinstance(poe, dict):
            if poe.get("enabled") is not True:
                return None
            power = poe.get("power")
        else:
            if _field(port, "poeEnabled", "poe_enabled") is False:
                return None
            power = _field(port, "poePower", "poe_power")
        try:
            return round(float(power), 1) if power is not None else None
        except (TypeError, ValueError):
            return None
    return None


def _medium(value: Any) -> LinkMedium:
    """Map a legacy uplink type onto the contract medium."""
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in {"wire", "wired"}:
            return "wired"
        if lowered in {"wireless", "mesh"}:
            return "wireless"
    return "unknown"


def _connection(client: Mapping[str, Any]) -> ClientConnection | None:
    """Return a client's wired/wireless connection, if known."""
    raw = client.get("type")
    if isinstance(raw, str):
        upper = raw.upper()
        if upper == "WIRED":
            return "wired"
        if upper == "WIRELESS":
            return "wireless"
    return None


def _display_name(value: Any, fallback: str) -> str:
    """Return a usable name; blank or MAC-shaped names use the fallback."""
    if isinstance(value, str) and value.strip() and normalize_mac(value) is None:
        return value.strip()
    return fallback


def _device_node(
    device: Mapping[str, Any],
    device_id: str,
    node_id: str,
    ha_device_ids: Mapping[str, str],
) -> TopologyNode:
    """Build the allowlisted node for one infrastructure device."""
    model = device.get("model")
    has_model = isinstance(model, str) and bool(model)
    node: TopologyNode = {
        "id": node_id,
        "kind": device_kind(device),
        "name": _display_name(
            device.get("name"), model if has_model else _UNKNOWN_DEVICE
        ),
        "state": device_state(device),
    }
    if has_model:
        node["model"] = model
    ha_device_id = ha_device_ids.get(device_id)
    if ha_device_id:
        node["ha_device_id"] = ha_device_id
    return node


def _client_node(client: Mapping[str, Any], node_id: str) -> TopologyNode:
    """Build the allowlisted node for one client."""
    node: TopologyNode = {
        "id": node_id,
        "kind": "client",
        "name": _display_name(client.get("name"), _UNKNOWN_CLIENT),
        "state": "offline" if client.get("connected") is False else "online",
    }
    connection = _connection(client)
    if connection is not None:
        node["connection"] = connection
    return node


def _device_edge(
    device: Mapping[str, Any],
    node_id: str,
    mac_index: Mapping[str, str],
    devices_by_node: Mapping[str, Mapping[str, Any]],
) -> TopologyEdge | UnresolvedReason | None:
    """
    Return the device's edge to its parent, an unresolved reason, or None.

    None means "no edge and nothing wrong": a gateway (the root) or a
    self-reference.
    """
    topology = device.get("topology")
    block = topology if isinstance(topology, dict) else {}
    parent_mac = normalize_mac(block.get("uplink_mac"))
    if parent_mac is None:
        return None if device_kind(device) == "gateway" else "no_uplink_data"
    parent_id = mac_index.get(parent_mac)
    if parent_id is None:
        return "parent_not_found"
    if parent_id == node_id:
        return None

    edge: TopologyEdge = {
        "source": node_id,
        "target": parent_id,
        "medium": _medium(block.get("uplink_type")),
    }
    speed = _as_int(block.get("uplink_speed"))
    if speed is not None:
        edge["speed_mbps"] = speed
    parent_port = _as_int(block.get("uplink_remote_port"))
    if parent_port is not None:
        edge["parent_port"] = parent_port
        poe_watts = _port_poe_watts(devices_by_node[parent_id], parent_port)
        if poe_watts is not None:
            edge["poe_power_w"] = poe_watts
    child_port = _as_int(block.get("uplink_port_idx"))
    if child_port is None:
        child_port = _uplink_port_index(device)
    if child_port is not None:
        edge["child_port"] = child_port
    return edge


def _select_clients(
    clients: Mapping[str, Any], max_clients: int
) -> tuple[list[tuple[str, dict[str, Any]]], int]:
    """Apply the client cap: wired first, then by name, then by id."""
    valid = [
        (client_id, client)
        for client_id, client in clients.items()
        if isinstance(client, dict)
    ]
    limit = max(0, min(max_clients, MAX_CLIENTS_PER_SITE))
    valid.sort(
        key=lambda item: (
            _connection(item[1]) != "wired",
            _display_name(item[1].get("name"), _UNKNOWN_CLIENT).casefold(),
            item[0],
        )
    )
    return valid[:limit], len(valid)


def _status(issues: list[TopologyIssue]) -> TopologyStatus:
    """Derive the snapshot status from its issues."""
    if any(issue["severity"] == "error" for issue in issues):
        return "unavailable"
    return "partial" if issues else "ok"


def _finalize(snapshot: SiteTopology) -> SiteTopology:
    """Sort every list deterministically and stamp the content revision."""
    snapshot["nodes"].sort(key=lambda node: (_KIND_ORDER[node["kind"]], node["id"]))
    snapshot["edges"].sort(key=lambda edge: (edge["source"], edge["target"]))
    snapshot["unresolved"].sort(key=lambda entry: entry["node_id"])
    snapshot["issues"].sort(key=lambda issue: issue["code"])
    content = {key: value for key, value in snapshot.items() if key != "revision"}
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    snapshot["revision"] = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    return snapshot


def build_unavailable_topology(
    entry_id: str, site_id: str, site_name: str, issue_code: str
) -> SiteTopology:
    """Return an empty snapshot that reports why no graph is available."""
    return _finalize(
        {
            "schema_version": TOPOLOGY_SCHEMA_VERSION,
            "entry_id": entry_id,
            "site_id": site_id,
            "site_name": site_name,
            "revision": "",
            "status": "unavailable",
            "issues": [{"code": issue_code, "severity": "error"}],
            "nodes": [],
            "edges": [],
            "unresolved": [],
            "truncation": None,
        }
    )


def build_site_topology(  # noqa: PLR0912
    data: Mapping[str, Any],
    entry_id: str,
    site_id: str,
    *,
    ha_device_ids: Mapping[str, str],
    max_clients: int = MAX_CLIENTS_PER_SITE,
    devices_available: bool = True,
) -> SiteTopology:
    """Build the allowlisted topology snapshot for one site."""
    devices = _site_map(data, "devices", site_id)
    clients = _site_map(data, "clients", site_id)
    nodes: list[TopologyNode] = []
    edges: list[TopologyEdge] = []
    unresolved: list[TopologyUnresolved] = []

    device_node_ids: dict[str, str] = {}
    devices_by_node: dict[str, dict[str, Any]] = {}
    mac_index: dict[str, str] = {}
    for device_id, device in devices.items():
        if not isinstance(device, dict):
            continue
        node_id = opaque_node_id("dev", entry_id, device_id)
        device_node_ids[device_id] = node_id
        devices_by_node[node_id] = device
        nodes.append(_device_node(device, device_id, node_id, ha_device_ids))
        mac = normalize_mac(_field(device, "macAddress", "mac")) or normalize_mac(
            device_id
        )
        if mac is not None:
            mac_index[mac] = node_id

    for node_id, device in devices_by_node.items():
        link = _device_edge(device, node_id, mac_index, devices_by_node)
        if isinstance(link, dict):
            edges.append(link)
        elif link is not None:
            unresolved.append({"node_id": node_id, "reason": link})

    included, clients_total = _select_clients(clients, max_clients)
    for client_id, client in included:
        node_id = opaque_node_id("cli", entry_id, client_id)
        nodes.append(_client_node(client, node_id))
        uplink = _field(client, "uplinkDeviceId", "uplink_device_id")
        if not isinstance(uplink, str):
            unresolved.append({"node_id": node_id, "reason": "no_uplink_data"})
            continue
        target = device_node_ids.get(uplink)
        if target is None:
            unresolved.append({"node_id": node_id, "reason": "parent_not_found"})
            continue
        edges.append(
            {"source": node_id, "target": target, "medium": _connection(client) or "unknown"}
        )

    issues: list[TopologyIssue] = []
    by_site = data.get("devices")
    if not devices_available or not isinstance(by_site, dict) or site_id not in by_site:
        issues.append({"code": "devices_unavailable", "severity": "error"})
    if devices_by_node and not any(
        isinstance(device.get("topology"), dict) for device in devices_by_node.values()
    ):
        issues.append({"code": "legacy_uplink_missing", "severity": "warning"})
    if unresolved:
        issues.append({"code": "parents_unresolved", "severity": "warning"})
    truncation: TopologyTruncation | None = None
    if len(included) < clients_total:
        truncation = {"clients_total": clients_total, "clients_included": len(included)}
        issues.append({"code": "clients_truncated", "severity": "info"})

    return _finalize(
        {
            "schema_version": TOPOLOGY_SCHEMA_VERSION,
            "entry_id": entry_id,
            "site_id": site_id,
            "site_name": site_display_name(data, site_id),
            "revision": "",
            "status": _status(issues),
            "issues": issues,
            "nodes": nodes,
            "edges": edges,
            "unresolved": unresolved,
            "truncation": truncation,
        }
    )
```

Notes for the implementer:
- `test_mac_keyed_device_resolves_and_is_opaque`: the parent device has no `macAddress`, so the MAC index falls back to its MAC-shaped id — that is the `or normalize_mac(device_id)` branch.
- Drop the `# noqa: PLR0912` marker unless ruff actually reports it (RUF100 flags unused noqa). If ruff reports a complexity rule (C901/PLR0912/PLR0915), extract the issues block into `_collect_issues(data, site_id, devices_by_node, unresolved, devices_available, truncation) -> list[TopologyIssue]` instead of adding more noqa.
- mypy may reject `_field(...)` returns being assigned into `Literal` fields — all Literal values above come from explicit literals or helper return types, so this should type-check; fix any error by narrowing, not by `# type: ignore`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PY -m pytest tests/test_topology.py -q --no-cov`
Expected: PASS (all Task 2 + Task 3 tests).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uvx ruff@0.16.7 check custom_components/unifi_insights/topology.py tests/test_topology.py
uvx ruff@0.16.7 format custom_components/unifi_insights/topology.py tests/test_topology.py
$PY -m mypy custom_components/unifi_insights
$PY -m pytest tests/test_topology.py -q --no-cov
git add custom_components/unifi_insights/topology.py tests/test_topology.py
git commit -m "feat(topology): build the per-site graph snapshot

Device edges resolve the legacy parent MAC through a per-site MAC index
(v1 UUIDs and legacy _id never match), clients attach via uplinkDeviceId,
and every gap is reported in unresolved instead of a dangling edge. The
snapshot is allowlisted, capped at 500 clients, deterministically ordered
and carries a content revision so subscribers only get real changes."
```

---

### Task 4: WebSocket `sources` and `get` commands (PR 1)

**Files:**
- Create: `custom_components/unifi_insights/websocket_api.py`
- Modify: `custom_components/unifi_insights/__init__.py` (`async_setup`), `custom_components/unifi_insights/manifest.json`
- Test: `tests/test_websocket_api.py`

**Interfaces:**
- Consumes: `build_site_topology`, `site_display_name`, `MAX_CLIENTS_PER_SITE`, `SiteTopology` (Task 3); `entry.runtime_data.coordinator` (facade: `.data`, `.device_available`, `.async_add_listener`), `entry.runtime_data.config_coordinator.get_site_ids()`.
- Produces: `async_register_websocket_commands(hass: HomeAssistant) -> None`; commands `unifi_insights/topology/sources` (result `list[{entry_id, title, sites: [{id, name}]}]`), `unifi_insights/topology/get` (params `entry_id`, `site_id`, optional `max_clients` 0..500; result `SiteTopology`); error codes `entry_not_found`, `entry_not_loaded`, `site_not_selected`. Private helpers `_resolve_entry`, `_build_snapshot`, `_RequestError` reused by Task 5.

- [ ] **Step 1: Write the failing tests** — create `tests/test_websocket_api.py`:

```python
"""Tests for the topology WebSocket API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers import device_registry as dr

from custom_components.unifi_insights.const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry

SITE = "site-1"
GW_MAC = "02:00:00:00:00:01"


def _seed(entry: MockConfigEntry) -> dict[str, Any]:
    """
    Add a two-device site with one client beside the mocked setup's data.

    The mocked "default" site is kept (merged, not replaced) so the entity
    listeners that also run on facade updates still find their own data.
    """
    runtime = entry.runtime_data
    runtime.device_coordinator.last_update_success = True
    site = {SITE: {"id": SITE, "name": "Home"}}
    runtime.config_coordinator.data["sites"] = {
        **runtime.config_coordinator.data.get("sites", {}),
        **site,
    }
    data = runtime.coordinator.data
    data["sites"] = {**data.get("sites", {}), **site}
    data["devices"] = {
        **data.get("devices", {}),
        SITE: {
            "uuid-gw": {
                "id": "uuid-gw",
                "name": "Gateway",
                "model": "UDM Pro SE",
                "macAddress": GW_MAC,
                "state": "ONLINE",
                "topology": {"legacy_type": "udm"},
            },
            "uuid-ap": {
                "id": "uuid-ap",
                "name": "AP",
                "model": "U7 Pro XGS",
                "macAddress": "02:00:00:00:00:08",
                "state": "ONLINE",
                "topology": {
                    "legacy_type": "uap",
                    "uplink_mac": GW_MAC,
                    "uplink_type": "wire",
                },
            },
        }
    }
    data["clients"] = {
        **data.get("clients", {}),
        SITE: {
            "cli-1": {
                "id": "cli-1",
                "name": "Phone",
                "type": "WIRELESS",
                "macAddress": "12:00:00:00:00:02",
                "ipAddress": "10.2.0.9",
                "uplinkDeviceId": "uuid-ap",
            }
        }
    }
    return data


async def test_sources_lists_loaded_entries(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_ws_client
) -> None:
    """Sources returns each loaded entry with its selected sites."""
    _seed(init_integration)
    client = await hass_ws_client(hass)

    await client.send_json({"id": 1, "type": "unifi_insights/topology/sources"})
    msg = await client.receive_json()

    assert msg["success"]
    (source,) = msg["result"]
    assert source["entry_id"] == init_integration.entry_id
    assert source["title"] == init_integration.title
    assert {"id": SITE, "name": "Home"} in source["sites"]


async def test_get_returns_snapshot(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_ws_client
) -> None:
    """Get returns an allowlisted snapshot with registry ids attached."""
    _seed(init_integration)
    registry_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=init_integration.entry_id,
        identifiers={(DOMAIN, f"{SITE}_uuid-ap")},
    )
    client = await hass_ws_client(hass)

    await client.send_json(
        {
            "id": 1,
            "type": "unifi_insights/topology/get",
            "entry_id": init_integration.entry_id,
            "site_id": SITE,
        }
    )
    msg = await client.receive_json()

    assert msg["success"]
    snapshot = msg["result"]
    assert snapshot["status"] == "ok"
    assert snapshot["site_name"] == "Home"
    assert {edge["source"]: edge["target"] for edge in snapshot["edges"]} == {
        "dev:uuid-ap": "dev:uuid-gw",
        "cli:cli-1": "dev:uuid-ap",
    }
    ap = next(node for node in snapshot["nodes"] if node["id"] == "dev:uuid-ap")
    assert ap["ha_device_id"] == registry_device.id
    assert "10.2.0.9" not in str(snapshot)
    assert GW_MAC not in str(snapshot)


async def test_get_non_admin_user_allowed(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client,
    hass_read_only_access_token: str,
) -> None:
    """Dashboards are used by non-admins, so plain authentication suffices."""
    _seed(init_integration)
    client = await hass_ws_client(hass, hass_read_only_access_token)

    await client.send_json(
        {
            "id": 1,
            "type": "unifi_insights/topology/get",
            "entry_id": init_integration.entry_id,
            "site_id": SITE,
        }
    )
    msg = await client.receive_json()

    assert msg["success"]


async def test_get_max_clients(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_ws_client
) -> None:
    """max_clients is honoured and validated against the hard cap."""
    _seed(init_integration)
    client = await hass_ws_client(hass)

    await client.send_json(
        {
            "id": 1,
            "type": "unifi_insights/topology/get",
            "entry_id": init_integration.entry_id,
            "site_id": SITE,
            "max_clients": 0,
        }
    )
    msg = await client.receive_json()
    assert msg["result"]["truncation"] == {"clients_total": 1, "clients_included": 0}

    await client.send_json(
        {
            "id": 2,
            "type": "unifi_insights/topology/get",
            "entry_id": init_integration.entry_id,
            "site_id": SITE,
            "max_clients": 501,
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "invalid_format"


async def test_get_errors(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_ws_client
) -> None:
    """Unknown entry, foreign domain and unselected site are reported by code."""
    _seed(init_integration)
    client = await hass_ws_client(hass)

    async def _get(msg_id: int, entry_id: str, site_id: str) -> dict:
        await client.send_json(
            {
                "id": msg_id,
                "type": "unifi_insights/topology/get",
                "entry_id": entry_id,
                "site_id": site_id,
            }
        )
        return await client.receive_json()

    missing = await _get(1, "nope", SITE)
    assert missing["error"]["code"] == "entry_not_found"

    other_domain = MockConfigEntryForTest(domain="other_domain")
    other_domain.add_to_hass(hass)
    foreign = await _get(2, other_domain.entry_id, SITE)
    assert foreign["error"]["code"] == "entry_not_found"

    unselected = await _get(3, init_integration.entry_id, "site-9")
    assert unselected["error"]["code"] == "site_not_selected"

    await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    unloaded = await _get(4, init_integration.entry_id, SITE)
    assert unloaded["error"]["code"] == "entry_not_loaded"
```

Add `from pytest_homeassistant_custom_component.common import MockConfigEntry as MockConfigEntryForTest` as a **runtime** import at the top (the `TYPE_CHECKING` one is only for annotations).

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PY -m pytest tests/test_websocket_api.py -q --no-cov`
Expected: FAIL — `unknown_command` errors (`msg["success"]` is False).

- [ ] **Step 3: Implement** — create `custom_components/unifi_insights/websocket_api.py`:

```python
"""
WebSocket API exposing the network topology graph to the frontend.

Commands are available to any authenticated user (dashboards are used by
non-admins); privacy comes from the topology builder's field allowlist and
from scoping every request to one loaded entry and one selected site.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .topology import MAX_CLIENTS_PER_SITE, build_site_topology, site_display_name

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import UnifiInsightsConfigEntry
    from .topology import SiteTopology

ERR_ENTRY_NOT_FOUND = "entry_not_found"
ERR_ENTRY_NOT_LOADED = "entry_not_loaded"
ERR_SITE_NOT_SELECTED = "site_not_selected"

_MAX_CLIENTS = vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_CLIENTS_PER_SITE))
_SNAPSHOT_SCHEMA = {
    vol.Required("entry_id"): str,
    vol.Required("site_id"): str,
    vol.Optional("max_clients", default=MAX_CLIENTS_PER_SITE): _MAX_CLIENTS,
}


class _RequestError(Exception):
    """A request that cannot be served, carrying a WebSocket error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@callback
def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register the topology WebSocket commands (once per HA instance)."""
    websocket_api.async_register_command(hass, ws_topology_sources)
    websocket_api.async_register_command(hass, ws_topology_get)


def _resolve_entry(hass: HomeAssistant, entry_id: str) -> UnifiInsightsConfigEntry:
    """Return a loaded UniFi Insights entry or raise _RequestError."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        msg = f"No UniFi Insights config entry {entry_id}"
        raise _RequestError(ERR_ENTRY_NOT_FOUND, msg)
    if (
        entry.state is not ConfigEntryState.LOADED
        or getattr(entry, "runtime_data", None) is None
    ):
        msg = f"UniFi Insights config entry {entry_id} is not loaded"
        raise _RequestError(ERR_ENTRY_NOT_LOADED, msg)
    return entry


def _ha_device_ids(
    hass: HomeAssistant, data: dict[str, Any], site_id: str
) -> dict[str, str]:
    """Map the site's device ids to their Home Assistant device registry ids."""
    registry = dr.async_get(hass)
    devices = data.get("devices", {}).get(site_id, {})
    result: dict[str, str] = {}
    for device_id in devices if isinstance(devices, dict) else ():
        device = registry.async_get_device(identifiers={(DOMAIN, f"{site_id}_{device_id}")})
        if device is not None:
            result[device_id] = device.id
    return result


def _build_snapshot(
    hass: HomeAssistant,
    entry: UnifiInsightsConfigEntry,
    site_id: str,
    max_clients: int,
) -> SiteTopology:
    """Build one site's snapshot, enforcing that the site is selected."""
    runtime = entry.runtime_data
    if site_id not in runtime.config_coordinator.get_site_ids():
        msg = f"Site {site_id} is not enabled for this UniFi Insights entry"
        raise _RequestError(ERR_SITE_NOT_SELECTED, msg)
    facade = runtime.coordinator
    return build_site_topology(
        facade.data,
        entry.entry_id,
        site_id,
        ha_device_ids=_ha_device_ids(hass, facade.data, site_id),
        max_clients=max_clients,
        devices_available=facade.device_available,
    )


@websocket_api.websocket_command({vol.Required("type"): "unifi_insights/topology/sources"})
@callback
def ws_topology_sources(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List loaded entries and their selected sites for the card editor."""
    sources = []
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        runtime = getattr(entry, "runtime_data", None)
        if runtime is None:
            continue
        data = runtime.coordinator.data
        sources.append(
            {
                "entry_id": entry.entry_id,
                "title": entry.title,
                "sites": [
                    {"id": site_id, "name": site_display_name(data, site_id)}
                    for site_id in runtime.config_coordinator.get_site_ids()
                ],
            }
        )
    connection.send_result(msg["id"], sources)


@websocket_api.websocket_command(
    {vol.Required("type"): "unifi_insights/topology/get", **_SNAPSHOT_SCHEMA}
)
@callback
def ws_topology_get(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return one site's topology snapshot."""
    try:
        entry = _resolve_entry(hass, msg["entry_id"])
        snapshot = _build_snapshot(hass, entry, msg["site_id"], msg["max_clients"])
    except _RequestError as err:
        connection.send_error(msg["id"], err.code, str(err))
        return
    connection.send_result(msg["id"], snapshot)
```

In `__init__.py`, add the import next to `from .services import async_setup_services`:

```python
from .websocket_api import async_register_websocket_commands
```

and in `async_setup` after `await async_setup_services(hass)`:

```python
    # The topology WebSocket commands, like service actions, are registered
    # once per Home Assistant instance, not once per config entry.
    async_register_websocket_commands(hass)
```

In `manifest.json`, change `"dependencies": ["ffmpeg", "stream"]` to `"dependencies": ["ffmpeg", "stream", "websocket_api"]`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PY -m pytest tests/test_websocket_api.py tests/test_init.py -q --no-cov`
Expected: PASS. If `hass_read_only_access_token` is not a fixture in this pytest-homeassistant version, check with `$PY -m pytest --fixtures tests/test_websocket_api.py | grep access_token` and use the reported non-admin token fixture.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uvx ruff@0.16.7 check custom_components/unifi_insights/websocket_api.py custom_components/unifi_insights/__init__.py tests/test_websocket_api.py
uvx ruff@0.16.7 format custom_components/unifi_insights/websocket_api.py tests/test_websocket_api.py
$PY -m mypy custom_components/unifi_insights
git add custom_components/unifi_insights/websocket_api.py custom_components/unifi_insights/__init__.py custom_components/unifi_insights/manifest.json tests/test_websocket_api.py
git commit -m "feat(websocket): topology sources and get commands

Any authenticated user can read the graph because dashboards are used by
non-admins; the builder's allowlist keeps MACs and IPs out, and every
request is scoped to one loaded entry and one selected site."
```

---

### Task 5: WebSocket `subscribe` command (PR 1)

**Files:**
- Modify: `custom_components/unifi_insights/websocket_api.py`
- Test: `tests/test_websocket_api.py` (append)

**Interfaces:**
- Consumes: Task 4 `_resolve_entry`, `_build_snapshot`, `_RequestError`, `_SNAPSHOT_SCHEMA`; Task 3 `build_unavailable_topology`.
- Produces: command `unifi_insights/topology/subscribe` (same params as `get`): result ack, then `event` messages each carrying a full `SiteTopology`. Pushes only when `revision` changes. On entry unload: one final event with `status: unavailable`, issue `entry_unloaded`, then stops.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_websocket_api.py` (add `import logging`, `from unittest.mock import patch` and `from homeassistant.config_entries import ConfigEntryState` at the top):

```python
async def _subscribe(client, entry: MockConfigEntry, msg_id: int = 1) -> dict:
    """Subscribe and return the initial snapshot event."""
    await client.send_json(
        {
            "id": msg_id,
            "type": "unifi_insights/topology/subscribe",
            "entry_id": entry.entry_id,
            "site_id": SITE,
        }
    )
    ack = await client.receive_json()
    assert ack["success"], ack
    event = await client.receive_json()
    assert event["type"] == "event"
    return event["event"]


async def _assert_no_event(client, ping_id: int) -> None:
    """Prove nothing was pushed: the next message is the ping's pong."""
    await client.send_json({"id": ping_id, "type": "ping"})
    msg = await client.receive_json()
    assert msg["type"] == "pong", msg


async def test_subscribe_pushes_only_on_change(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_ws_client
) -> None:
    """Initial snapshot, then one push per real change, none for no-ops."""
    data = _seed(init_integration)
    facade = init_integration.runtime_data.coordinator
    client = await hass_ws_client(hass)

    initial = await _subscribe(client, init_integration)
    assert initial["status"] == "ok"

    facade.async_update_listeners()
    await _assert_no_event(client, 50)

    data["devices"][SITE]["uuid-ap"]["name"] = "Hallway AP"
    facade.async_update_listeners()
    pushed = await client.receive_json()
    assert pushed["type"] == "event"
    assert pushed["event"]["revision"] != initial["revision"]
    names = {node["id"]: node["name"] for node in pushed["event"]["nodes"]}
    assert names["dev:uuid-ap"] == "Hallway AP"


async def test_subscribe_errors_use_get_codes(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_ws_client
) -> None:
    """Subscribe rejects the same bad requests as get."""
    _seed(init_integration)
    client = await hass_ws_client(hass)

    await client.send_json(
        {
            "id": 1,
            "type": "unifi_insights/topology/subscribe",
            "entry_id": init_integration.entry_id,
            "site_id": "site-9",
        }
    )
    msg = await client.receive_json()

    assert msg["error"]["code"] == "site_not_selected"


async def test_unsubscribe_stops_pushes(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_ws_client
) -> None:
    """After unsubscribe_events, changes are no longer pushed."""
    data = _seed(init_integration)
    facade = init_integration.runtime_data.coordinator
    client = await hass_ws_client(hass)
    await _subscribe(client, init_integration, msg_id=7)

    await client.send_json({"id": 8, "type": "unsubscribe_events", "subscription": 7})
    assert (await client.receive_json())["success"]

    data["devices"][SITE]["uuid-ap"]["name"] = "Changed"
    facade.async_update_listeners()
    await _assert_no_event(client, 9)


async def test_subscribe_entry_unload_sends_final_snapshot(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_ws_client
) -> None:
    """Unloading the entry pushes an unavailable snapshot and ends the stream."""
    _seed(init_integration)
    client = await hass_ws_client(hass)
    await _subscribe(client, init_integration)

    await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()

    final = await client.receive_json()
    assert final["type"] == "event"
    assert final["event"]["status"] == "unavailable"
    assert final["event"]["issues"] == [{"code": "entry_unloaded", "severity": "error"}]
    assert final["event"]["site_name"] == "Home"


async def test_subscribe_unload_then_close_is_safe(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_ws_client
) -> None:
    """Unload followed by connection close never removes the listener twice."""
    _seed(init_integration)
    client = await hass_ws_client(hass)
    await _subscribe(client, init_integration)

    await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    await client.receive_json()  # final unavailable snapshot

    await client.close()
    await hass.async_block_till_done()  # raises if remove_listener ran twice


async def test_subscribe_close_then_unload_is_safe(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_ws_client
) -> None:
    """Connection close followed by unload never removes the listener twice."""
    _seed(init_integration)
    client = await hass_ws_client(hass)
    await _subscribe(client, init_integration)

    await client.close()
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()

    assert init_integration.state is ConfigEntryState.NOT_LOADED


async def test_subscribe_builder_error_does_not_break_listeners(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client,
    caplog,
) -> None:
    """A builder bug is logged; other coordinator listeners still run."""
    _seed(init_integration)
    facade = init_integration.runtime_data.coordinator
    client = await hass_ws_client(hass)
    await _subscribe(client, init_integration)

    calls: list[str] = []
    facade.async_add_listener(lambda: calls.append("entity"))
    with (
        caplog.at_level(logging.ERROR),
        patch(
            "custom_components.unifi_insights.websocket_api.build_site_topology",
            side_effect=RuntimeError("boom"),
        ),
    ):
        facade.async_update_listeners()

    assert calls == ["entity"]
    assert "topology" in caplog.text.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PY -m pytest tests/test_websocket_api.py -q --no-cov`
Expected: the new tests FAIL with `unknown_command`.

- [ ] **Step 3: Implement** — in `websocket_api.py` add `import logging`, `_LOGGER = logging.getLogger(__name__)`, extend the topology import with `build_unavailable_topology`, register the command in `async_register_websocket_commands`:

```python
    websocket_api.async_register_command(hass, ws_topology_subscribe)
```

and append:

```python
ISSUE_ENTRY_UNLOADED = "entry_unloaded"


@websocket_api.websocket_command(
    {vol.Required("type"): "unifi_insights/topology/subscribe", **_SNAPSHOT_SCHEMA}
)
@callback
def ws_topology_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """
    Stream one site's snapshot, pushing only when its revision changes.

    The listener rides on the facade coordinator, which never polls on its
    own, so a subscription adds no API traffic. It is removed when the client
    unsubscribes, when the connection closes, or when the entry unloads -
    whichever comes first; the removal is idempotent because Home Assistant's
    remove-listener callback raises if called twice.
    """
    msg_id: int = msg["id"]
    site_id: str = msg["site_id"]
    max_clients: int = msg["max_clients"]
    try:
        entry = _resolve_entry(hass, msg["entry_id"])
        snapshot = _build_snapshot(hass, entry, site_id, max_clients)
    except _RequestError as err:
        connection.send_error(msg_id, err.code, str(err))
        return

    last_revision = snapshot["revision"]
    site_name = snapshot["site_name"]
    removed = False

    @callback
    def _async_forward() -> None:
        nonlocal last_revision
        try:
            update = _build_snapshot(hass, entry, site_id, max_clients)
        except _RequestError:
            # The site was deselected; the options change reloads the entry,
            # which ends this subscription through _async_entry_unloaded.
            return
        except Exception:
            # Never let a builder bug escape: this runs inside the
            # coordinator's listener loop, and raising would stop every
            # entity on the entry from updating.
            _LOGGER.exception("Failed to rebuild the topology snapshot for %s", site_id)
            return
        if update["revision"] == last_revision:
            return
        last_revision = update["revision"]
        connection.send_message(websocket_api.event_message(msg_id, update))

    remove_listener = entry.runtime_data.coordinator.async_add_listener(_async_forward)

    @callback
    def _async_unsubscribe() -> None:
        nonlocal removed
        if removed:
            return
        removed = True
        remove_listener()

    @callback
    def _async_entry_unloaded() -> None:
        if removed:
            return
        _async_unsubscribe()
        connection.subscriptions.pop(msg_id, None)
        connection.send_message(
            websocket_api.event_message(
                msg_id,
                build_unavailable_topology(
                    entry.entry_id, site_id, site_name, ISSUE_ENTRY_UNLOADED
                ),
            )
        )

    connection.subscriptions[msg_id] = _async_unsubscribe
    entry.async_on_unload(_async_entry_unloaded)
    connection.send_result(msg_id)
    connection.send_message(websocket_api.event_message(msg_id, snapshot))
```

If ruff reports BLE001 on `except Exception`, add `# noqa: BLE001` with the comment already explaining why (the handler logs via `_LOGGER.exception`, which ruff normally accepts).

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PY -m pytest tests/test_websocket_api.py -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uvx ruff@0.16.7 check custom_components/unifi_insights/websocket_api.py tests/test_websocket_api.py
uvx ruff@0.16.7 format custom_components/unifi_insights/websocket_api.py tests/test_websocket_api.py
$PY -m mypy custom_components/unifi_insights
git add custom_components/unifi_insights/websocket_api.py tests/test_websocket_api.py
git commit -m "feat(websocket): subscribe to topology snapshot changes

Pushes a new snapshot only when its content revision changes, so the card
never polls and the subscription adds no API load. Cleanup is idempotent
across unsubscribe, connection close and entry unload, and a builder error
is logged instead of breaking the coordinator's listener loop."
```

---

### Task 6: PR 1 validation and local PR body

**Files:**
- Create (local only, not committed): `/home/tacoriffic/ha-unifi-insights/.local/pr-bodies/topology-pr1-graph.md`

- [ ] **Step 1: Full suite with coverage**

Run: `$PY -m pytest --cov --cov-branch -q`
Expected: all pass, total coverage ≥ 90%. `topology.py` and `websocket_api.py` each ≥ 95% (check `--cov-report=term-missing` for those two files and add tests for any uncovered branch).

- [ ] **Step 2: Static checks across every changed file**

```bash
$PY -m mypy custom_components/unifi_insights
~/ai-tools/scripts/ruff-new-findings.sh upstream/main 0.16.7
uvx ruff@0.16.7 format --check $(git diff --name-only upstream/main -- '*.py')
```
Expected: mypy shows only the two known `entity.py` errors; ruff-new-findings reports zero new findings; format check clean.

- [ ] **Step 3: Draft the PR 1 body locally**

Read `/home/tacoriffic/.claude/projects/-home-tacoriffic-ha-unifi-insights/memory/pr-body-house-format.md`, the repo's `.github/PULL_REQUEST_TEMPLATE.md` (if present), and one merged delacjus PR body (`gh api repos/ruaan-deysel/ha-unifi-insights/pulls/158 --jq .body`). Write the body in that format to `/home/tacoriffic/ha-unifi-insights/.local/pr-bodies/topology-pr1-graph.md`. Required content:
- `Closes`/`Part of #165` per house style (PR 2 closes it; PR 1 is "Part of #165").
- The live finding (v1 `uplink`/`type` null on real hardware; parent edges come from the legacy `/stat/device` uplink already fetched each poll).
- The contract summary (schema 1, three commands, allowlist, 500 cap, revision-gated pushes).
- Test evidence: suite count + coverage from Step 1, and live evidence placeholder section filled in Task 10.

**Do not run `gh pr create`.**

---

### Task 7: `client_links` from `/stat/sta` (PR 2)

**Files:**
- Modify: `custom_components/unifi_insights/coordinators/config.py` (initial `self.data`; per-site loop Wi-Fi enrichment block; publish block after `self.data["vpn_clients"] = vpn_clients_by_site`; new staticmethod)
- Modify: `custom_components/unifi_insights/coordinators/facade.py` (`_aggregate_data`)
- Test: `tests/test_coordinators.py` (class `TestUnifiConfigCoordinator`, fixture `coordinator`), `tests/test_diagnostics.py`

**Interfaces:**
- Consumes: `normalize_mac` from `custom_components.unifi_insights.topology`.
- Produces: `config_coordinator.data["client_links"]: dict[site_id, dict[normalised client mac, link]]`, `link` keys (each optional): `sw_mac: str`, `ap_mac: str`, `sw_port: int`, `vlan: int`, `network_name: str`. Facade `data["client_links"]` mirrors it. `UnifiConfigCoordinator._client_links(active_clients: list[Any]) -> dict[str, dict[str, Any]]` (staticmethod).

- [ ] **Step 0: Create the PR 2 branch**

```bash
cd /home/tacoriffic/ha-unifi-insights-topo-impl
git checkout -b feat/topology-client-links feat/topology-graph
```

- [ ] **Step 1: Write the failing tests** — append inside `class TestUnifiConfigCoordinator` in `tests/test_coordinators.py`:

```python
    def test_client_links_from_stat_sta(self):
        """Only link fields survive; MACs normalise; untagged has no vlan."""
        links = UnifiConfigCoordinator._client_links(
            [
                {
                    "mac": "8C:ED:E1:00:00:01",
                    "hostname": "cam",
                    "ip": "10.2.0.77",
                    "is_wired": True,
                    "sw_mac": "28:70:4E:00:00:01",
                    "sw_port": 14,
                    "vlan": 3,
                    "network": "Cameras",
                    "network_id": "legacy-net-1",
                },
                {
                    "mac": "12:00:00:00:00:02",
                    "is_wired": False,
                    "ap_mac": "02:00:00:00:00:08",
                    "network": "Default",
                },
                {"mac": "not-a-mac"},
                "garbage",
            ]
        )

        assert links == {
            "8c:ed:e1:00:00:01": {
                "sw_mac": "28:70:4e:00:00:01",
                "sw_port": 14,
                "vlan": 3,
                "network_name": "Cameras",
            },
            "12:00:00:00:00:02": {
                "ap_mac": "02:00:00:00:00:08",
                "network_name": "Default",
            },
        }

    @pytest.mark.asyncio
    async def test_async_update_data_collects_client_links_without_wifi(
        self, coordinator: UnifiConfigCoordinator
    ):
        """Links are built even when the Wi-Fi section is unavailable."""
        client = coordinator.network_client
        client.wifi.get_all = AsyncMock(side_effect=RuntimeError("wifi down"))
        client.clients.get_active_legacy = AsyncMock(
            return_value=[
                {"mac": "8c:ed:e1:00:00:01", "sw_mac": "28:70:4e:00:00:01", "sw_port": 3}
            ]
        )

        result = await coordinator._async_update_data()

        assert result["client_links"]["default"] == {
            "8c:ed:e1:00:00:01": {"sw_mac": "28:70:4e:00:00:01", "sw_port": 3}
        }
        client.clients.get_active_legacy.assert_awaited_once_with("default")

    @pytest.mark.asyncio
    async def test_async_update_data_keeps_client_links_on_failure(
        self, coordinator: UnifiConfigCoordinator
    ):
        """A failed /stat/sta keeps the previous links and does not fail."""
        coordinator.data["client_links"] = {"default": {"aa:aa:aa:aa:aa:aa": {"vlan": 2}}}
        coordinator.network_client.clients.get_active_legacy = AsyncMock(
            side_effect=RuntimeError("sta down")
        )

        result = await coordinator._async_update_data()

        assert result["client_links"]["default"] == {"aa:aa:aa:aa:aa:aa": {"vlan": 2}}

    @pytest.mark.asyncio
    async def test_async_update_data_wifi_enrichment_unchanged(
        self, coordinator: UnifiConfigCoordinator
    ):
        """The single /stat/sta call still feeds per-SSID client counts."""
        client = coordinator.network_client
        client.wifi.get_legacy_configs = AsyncMock(
            return_value=[{"name": "MainWiFi", "security": "wpapsk"}]
        )
        client.clients.get_active_legacy = AsyncMock(
            return_value=[{"essid": "MainWiFi", "mac": "12:00:00:00:00:02"}]
        )

        result = await coordinator._async_update_data()

        assert result["wifi"]["default"]["wifi1"]["num_connected_clients"] == 1
        client.clients.get_active_legacy.assert_awaited_once_with("default")
```

(The `coordinator` fixture's Wi-Fi mock already returns a `wifi1` network — see the existing `test_async_update_data_enriches_wifi_and_collects_sections`.)

Append to `tests/test_diagnostics.py`:

```python
async def test_diagnostics_placeholders_client_links(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    enable_custom_integrations,
) -> None:
    """Client link MACs (keys and values) are placeholdered; VLAN stays."""
    coordinator = init_integration.runtime_data.coordinator
    coordinator.data["client_links"] = {
        "site-1": {
            "8c:ed:e1:00:00:01": {
                "sw_mac": "28:70:4e:00:00:01",
                "sw_port": 14,
                "vlan": 3,
                "network_name": "Cameras",
            }
        }
    }

    diagnostics = await async_get_config_entry_diagnostics(hass, init_integration)
    (link_key,) = diagnostics["data"]["client_links"]["site-1"]
    link = diagnostics["data"]["client_links"]["site-1"][link_key]

    assert link_key.startswith("**REDACTED-MAC-")
    assert link["sw_mac"].startswith("**REDACTED-MAC-")
    assert link["vlan"] == 3
    assert link["network_name"] == "Cameras"
    for raw in ("8c:ed:e1:00:00:01", "28:70:4e:00:00:01"):
        assert raw not in _strings(diagnostics)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PY -m pytest tests/test_coordinators.py -k "client_links or wifi_enrichment_unchanged" tests/test_diagnostics.py::test_diagnostics_placeholders_client_links -q --no-cov`
Expected: FAIL — `AttributeError: ... has no attribute '_client_links'` / `KeyError: 'client_links'`. (The diagnostics test may pass already — placeholdering is generic; it pins the behaviour.)

- [ ] **Step 3: Implement** — in `coordinators/config.py`:

Add the import beside the other package imports:

```python
from ..topology import normalize_mac
```

Add `"client_links": {},` to the initial `self.data` dict (after `"network_info": {},`).

Add the staticmethod next to `_enrich_wifi`:

```python
    @staticmethod
    def _client_links(active_clients: list[Any]) -> dict[str, dict[str, Any]]:
        """
        Extract each active client's switch port, AP, VLAN and network name.

        The v1 clients endpoint leaves swMac/swPort/apMac/vlan/networkId null
        on current firmware; the classic /stat/sta response (already fetched
        for per-SSID counts) carries them. Keyed by normalised client MAC so
        the topology builder can join it to v1 clients.
        """
        links: dict[str, dict[str, Any]] = {}
        for client in active_clients:
            if not isinstance(client, dict):
                continue
            client_mac = normalize_mac(client.get("mac"))
            if client_mac is None:
                continue
            link: dict[str, Any] = {}
            for key in ("sw_mac", "ap_mac"):
                mac = normalize_mac(client.get(key))
                if mac is not None:
                    link[key] = mac
            for key in ("sw_port", "vlan"):
                value = client.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    link[key] = value
            network_name = client.get("network")
            if isinstance(network_name, str) and network_name:
                link["network_name"] = network_name
            links[client_mac] = link
        return links
```

Declare `client_links_by_site: dict[str, dict[str, Any]] = {}` beside `vpn_clients_by_site`.

Replace the existing Wi-Fi enrichment block (from `# Enrich with classic data (secrets, per-SSID counts, QR).` through its `except` log) with:

```python
                # One classic /stat/sta call per site feeds both the topology
                # client links and the per-SSID Wi-Fi counts. It runs even
                # when the Wi-Fi section failed, so topology keeps its links.
                legacy_name = legacy_site_names.get(site_id)
                active_clients: list[Any] | None = None
                if legacy_name:
                    try:
                        active_clients = (
                            await self.network_client.clients.get_active_legacy(
                                legacy_name
                            )
                        )
                    except Exception as err:
                        _LOGGER.debug(
                            "Config coordinator: Unable to fetch active clients "
                            "for site %s: %s",
                            site_id,
                            err,
                        )
                client_links_by_site[site_id] = (
                    self._client_links(active_clients)
                    if active_clients is not None
                    else self.data["client_links"].get(site_id, {})
                )

                # Enrich with classic data (secrets, per-SSID counts, QR).
                if wifi_models is not None and legacy_name and active_clients is not None:
                    try:
                        legacy_configs = (
                            await self.network_client.wifi.get_legacy_configs(
                                legacy_name
                            )
                        )
                        self._enrich_wifi(wifi_dict, legacy_configs, active_clients)
                    except Exception as err:
                        _LOGGER.debug(
                            "Config coordinator: Unable to enrich WiFi data "
                            "for site %s: %s",
                            site_id,
                            err,
                        )
```

(`legacy_name` is repeated in the condition so mypy narrows it to `str`.) Behaviour note for the PR body: when `/stat/sta` fails, Wi-Fi enrichment is skipped exactly as before (never called with an empty list, which would publish fake zero counts).

After `self.data["vpn_clients"] = vpn_clients_by_site`:

```python
            self.data["client_links"] = client_links_by_site
```

In `coordinators/facade.py` `_aggregate_data`, after `"network_info": ...`:

```python
            "client_links": self._config_coordinator.data.get("client_links", {}),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PY -m pytest tests/test_coordinators.py tests/test_diagnostics.py tests/test_wifi_qr_and_offline.py -q --no-cov`
Expected: PASS (whole files — Wi-Fi behaviour unchanged).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uvx ruff@0.16.7 check custom_components/unifi_insights/coordinators/config.py custom_components/unifi_insights/coordinators/facade.py tests/test_coordinators.py tests/test_diagnostics.py
uvx ruff@0.16.7 format custom_components/unifi_insights/coordinators/config.py custom_components/unifi_insights/coordinators/facade.py
$PY -m mypy custom_components/unifi_insights
git add custom_components/unifi_insights/coordinators/config.py custom_components/unifi_insights/coordinators/facade.py tests/test_coordinators.py tests/test_diagnostics.py
git commit -m "feat(coordinator): keep per-client links from /stat/sta

The v1 clients endpoint returns swMac/swPort/apMac/vlan/networkId as null
on real hardware, while the /stat/sta response already fetched for per-SSID
counts carries all of them plus the network name. Keep them keyed by client
MAC, fetched independently of the Wi-Fi section, with no new API call."
```

---

### Task 8: Builder enrichment from client links (PR 2)

**Files:**
- Modify: `custom_components/unifi_insights/topology.py`
- Test: `tests/test_topology.py` (append)

**Interfaces:**
- Consumes: facade `data["client_links"][site_id][client_mac]` (Task 7).
- Produces: `TopologyNode` gains `vlan_id: NotRequired[int]`, `network_name: NotRequired[str]`. Client edges gain `parent_port` when wired and the link's `sw_mac` resolves to the edge target. Client whose `uplinkDeviceId` is missing/unknown falls back to `sw_mac` (wired) / `ap_mac` (wireless) through the MAC index.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_topology.py`:

```python
def _with_links(data: dict, links: dict) -> dict:
    data["client_links"] = {SITE: links}
    return data


def test_client_link_enrichment() -> None:
    """Wired clients get port/VLAN/network; untagged clients get no vlan_id."""
    data = _with_links(
        _live_layout(),
        {
            "12:00:00:00:00:01": {
                "sw_mac": "02:00:00:00:00:03",
                "sw_port": 4,
                "vlan": 3,
                "network_name": "Media",
            },
            "12:00:00:00:00:02": {"ap_mac": "02:00:00:00:00:08", "network_name": "Default"},
        },
    )
    snapshot = _build(data)

    tv = next(n for n in snapshot["nodes"] if n["id"] == "cli:cli-tv")
    assert tv["vlan_id"] == 3
    assert tv["network_name"] == "Media"
    assert _edge(snapshot, "cli:cli-tv")["parent_port"] == 4
    phone = next(n for n in snapshot["nodes"] if n["id"] == "cli:cli-phone")
    assert "vlan_id" not in phone
    assert phone["network_name"] == "Default"
    assert "parent_port" not in _edge(snapshot, "cli:cli-phone")


def test_stale_link_port_not_attached_to_other_parent() -> None:
    """A 5-minute-old sw_mac that disagrees with uplinkDeviceId adds no port."""
    data = _with_links(
        _live_layout(),
        {"12:00:00:00:00:01": {"sw_mac": "02:00:00:00:00:05", "sw_port": 4}},
    )
    snapshot = _build(data)

    tv_edge = _edge(snapshot, "cli:cli-tv")
    assert tv_edge["target"] == "dev:uuid-u1"
    assert "parent_port" not in tv_edge


def test_client_parent_falls_back_to_link_macs() -> None:
    """Without uplinkDeviceId, sw_mac/ap_mac place the client."""
    data = _live_layout()
    data["clients"][SITE]["cli-tv"]["uplinkDeviceId"] = None
    data["clients"][SITE]["cli-phone"]["uplinkDeviceId"] = "uuid-gone"
    _with_links(
        data,
        {
            "12:00:00:00:00:01": {"sw_mac": "02:00:00:00:00:03", "sw_port": 4},
            "12:00:00:00:00:02": {"ap_mac": "02:00:00:00:00:08"},
        },
    )
    snapshot = _build(data)

    assert _edge(snapshot, "cli:cli-tv")["target"] == "dev:uuid-u1"
    assert _edge(snapshot, "cli:cli-tv")["parent_port"] == 4
    assert _edge(snapshot, "cli:cli-phone")["target"] == "dev:uuid-ap"
    assert snapshot["unresolved"] == []


def test_links_never_leak_macs() -> None:
    """Link MACs are used for joins only, never emitted."""
    data = _with_links(
        _live_layout(),
        {"12:00:00:00:00:01": {"sw_mac": "02:00:00:00:00:03", "sw_port": 4, "vlan": 3}},
    )
    payload = json.dumps(_build(data))

    assert "02:00:00" not in payload
    assert "12:00:00" not in payload
```

Also update `test_allowlist_never_emits_sensitive_values`'s node-key set to include `"vlan_id", "network_name"`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PY -m pytest tests/test_topology.py -q --no-cov`
Expected: FAIL — `KeyError: 'vlan_id'` / wrong unresolved list.

- [ ] **Step 3: Implement** — in `topology.py`:

Extend `TopologyNode`:

```python
    vlan_id: NotRequired[int]
    network_name: NotRequired[str]
```

Replace `_client_node` with:

```python
def _client_node(
    client: Mapping[str, Any], node_id: str, link: Mapping[str, Any]
) -> TopologyNode:
    """Build the allowlisted node for one client."""
    node: TopologyNode = {
        "id": node_id,
        "kind": "client",
        "name": _display_name(client.get("name"), _UNKNOWN_CLIENT),
        "state": "offline" if client.get("connected") is False else "online",
    }
    connection = _connection(client)
    if connection is not None:
        node["connection"] = connection
    vlan = _as_int(link.get("vlan"))
    if vlan is not None:
        node["vlan_id"] = vlan
    network_name = link.get("network_name")
    if isinstance(network_name, str) and network_name:
        node["network_name"] = network_name
    return node
```

Add:

```python
def _client_edge(
    client: Mapping[str, Any],
    node_id: str,
    link: Mapping[str, Any],
    device_node_ids: Mapping[str, str],
    mac_index: Mapping[str, str],
) -> TopologyEdge | UnresolvedReason:
    """Return a client's edge to its AP/switch, or why it has none."""
    connection = _connection(client)
    link_parent_keys = ("ap_mac", "sw_mac") if connection == "wireless" else ("sw_mac", "ap_mac")
    link_parent: str | None = None
    link_macs = [normalize_mac(link.get(key)) for key in link_parent_keys]
    for mac in link_macs:
        if mac is not None and mac in mac_index:
            link_parent = mac_index[mac]
            break
    uplink = _field(client, "uplinkDeviceId", "uplink_device_id")
    target = device_node_ids.get(uplink) if isinstance(uplink, str) else None
    if target is None:
        target = link_parent
    if target is None:
        has_reference = isinstance(uplink, str) or any(link_macs)
        return "parent_not_found" if has_reference else "no_uplink_data"

    edge: TopologyEdge = {
        "source": node_id,
        "target": target,
        "medium": connection or "unknown",
    }
    # /stat/sta is up to five minutes older than uplinkDeviceId, so its port
    # is only trusted when it names the same switch the edge points at.
    sw_parent = mac_index.get(normalize_mac(link.get("sw_mac")) or "")
    sw_port = _as_int(link.get("sw_port"))
    if connection == "wired" and sw_port is not None and sw_parent == target:
        edge["parent_port"] = sw_port
    return edge
```

In `build_site_topology`, before the client loop:

```python
    links = _site_map(data, "client_links", site_id)
```

and replace the client loop body with:

```python
    for client_id, client in included:
        node_id = opaque_node_id("cli", entry_id, client_id)
        client_mac = normalize_mac(_field(client, "macAddress", "mac"))
        raw_link = links.get(client_mac) if client_mac is not None else None
        link = raw_link if isinstance(raw_link, dict) else {}
        nodes.append(_client_node(client, node_id, link))
        client_link = _client_edge(client, node_id, link, device_node_ids, mac_index)
        if isinstance(client_link, dict):
            edges.append(client_link)
        else:
            unresolved.append({"node_id": node_id, "reason": client_link})
```

Check `test_client_unresolved_reasons` (Task 3) still passes: `cli-a` has an unknown uplink → `parent_not_found`; `cli-b` has neither uplink nor link → `no_uplink_data`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PY -m pytest tests/test_topology.py tests/test_websocket_api.py -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uvx ruff@0.16.7 check custom_components/unifi_insights/topology.py tests/test_topology.py
uvx ruff@0.16.7 format custom_components/unifi_insights/topology.py tests/test_topology.py
$PY -m mypy custom_components/unifi_insights
git add custom_components/unifi_insights/topology.py tests/test_topology.py
git commit -m "feat(topology): enrich clients with switch port, VLAN and network

Join /stat/sta links by client MAC: VLAN and network name on the node, the
switch port on the wired edge (only when the link names the same switch
uplinkDeviceId does, since /stat/sta can be five minutes older), and
sw_mac/ap_mac as a parent fallback when uplinkDeviceId is missing."
```

---

### Task 9: PR 2 validation and local PR body

**Files:**
- Create (local only): `/home/tacoriffic/ha-unifi-insights/.local/pr-bodies/topology-pr2-client-links.md`

- [ ] **Step 1: Full suite, coverage, static checks**

```bash
$PY -m pytest --cov --cov-branch -q
$PY -m mypy custom_components/unifi_insights
~/ai-tools/scripts/ruff-new-findings.sh upstream/main 0.16.7
```
Expected: all pass, ≥ 90% coverage, only the two known mypy errors, zero new ruff findings.

- [ ] **Step 2: Draft the PR 2 body locally** in house format: "Stacked on #<PR1> — please review that first; this PR's diff includes its commits until it merges." Summarise: no new API calls; `/stat/sta` decoupled from Wi-Fi; live coverage numbers (42/42 wired port, 16/16 AP, 54/54 VLAN, 58/58 network name); `Closes #165`. **Do not run `gh pr create`.**

---

### Task 10: Live verification on VM113 (needs Justin's OK to push a deploy branch to the fork)

**Files:** manifest version fingerprint on a throwaway `deploy/topology-live` branch only (never on the PR branches).

- [ ] **Step 1: Ask Justin** before pushing anything: "OK to push `deploy/topology-live` to the delacjus fork and HACS-deploy it to VM113 (rollback to upstream afterwards)?" Stop here without an explicit yes.

- [ ] **Step 2: Snapshot, build the deploy branch, deploy**

```bash
cd /home/tacoriffic/ha-unifi-insights-topo-impl
git checkout -b deploy/topology-live feat/topology-client-links
# fingerprint: "version": "2026.9.6" -> "2026.9.6+topo" in custom_components/unifi_insights/manifest.json
git commit -am "chore: deploy fingerprint for VM113 live test"
git push origin deploy/topology-live
TOKEN=$(~/ai-tools/scripts/secret-get.sh home-assistant-token)
export TOKEN
~/ai-tools/scripts/ha-hacs-branch-deploy.py snapshot --domain unifi_insights --out ~/.cache/ha-deploy/topology-probe/before.json
~/ai-tools/scripts/ha-hacs-branch-deploy.py deploy --repo 1330343416 --version deploy/topology-live
~/ai-tools/scripts/ha-hacs-branch-deploy.py snapshot --domain unifi_insights --settle 120 --out ~/.cache/ha-deploy/topology-probe/after.json
~/ai-tools/scripts/ha-hacs-branch-deploy.py diff ~/.cache/ha-deploy/topology-probe/before.json ~/.cache/ha-deploy/topology-probe/after.json
```
Expected: `manifest/get` reports `2026.9.6+topo`; Crestwood entry (`01KZQ22568FQ1TZZTK25QR4QH6`) `loaded`; no new error patterns. Use the actual current upstream manifest version if it is no longer `2026.9.6`.

- [ ] **Step 3: Exercise the API**

```bash
~/ai-tools/scripts/ha-ws-client.py '{"type":"unifi_insights/topology/sources"}' > ~/.cache/ha-deploy/topology-probe/sources.json
# take site id from sources.json, then:
~/ai-tools/scripts/ha-ws-client.py '{"type":"unifi_insights/topology/get","entry_id":"01KZQ22568FQ1TZZTK25QR4QH6","site_id":"<site id>"}' > ~/.cache/ha-deploy/topology-probe/get.json
```
Analyse `get.json` with a short Python script (do not print the raw payload into the conversation). **Pass criteria:**
- `status == "ok"`, `unresolved == []`
- exactly 7 device edges: six children → the Pro Max 24 node with `parent_port` ∈ {6, 8, 10, 12, 17, 20}, and Pro Max 24 → gateway with `parent_port == 11`, `speed_mbps == 10000`
- client edges ≈ current client count; wired clients carry `parent_port`; ≥ 50 clients carry `vlan_id`; all clients carry `network_name`
- no MAC-shaped or IP-shaped string anywhere in the payload (regex check)
- `ha_device_id` present on all 8 device nodes

- [ ] **Step 4: Subscribe push check** — `ha-ws-client.py` returns after the first result, so verify pushes by calling `get` twice ≥ 35 s apart and confirming `revision` changes only when PoE or state changed. (Pushes themselves are covered by Task 5 tests.)

- [ ] **Step 5: Roll back to upstream and record**

```bash
~/ai-tools/scripts/ha-hacs-branch-deploy.py deploy --repo 917968755 --version <latest upstream tag from before.json "hacs" block>
~/ai-tools/scripts/ha-hacs-branch-deploy.py snapshot --domain unifi_insights --settle 120 --out ~/.cache/ha-deploy/topology-probe/rolled-back.json
git push origin --delete deploy/topology-live
git checkout feat/topology-client-links && git branch -D deploy/topology-live
```
Expected: upstream manifest version back; both entries loaded. Fill the live-evidence sections of both local PR bodies with the Step 3 numbers.

---

### Task 11: Draft the #165 comment and record knowledge

**Files:**
- Create (local only): `/home/tacoriffic/ha-unifi-insights/.local/pr-bodies/issue-165-comment.md`
- Modify: `/home/tacoriffic/.claude/projects/-home-tacoriffic-ha-unifi-insights/memory/topology-165-166-live-data-shapes.md` (+ KB supersede)

- [ ] **Step 1: Draft the issue comment** (not posted): the live finding table from spec §2 (v1 `uplink`/`type` null 8/8; legacy uplink resolves the full tree; client link fields null in v1 but present in `/stat/sta`), the chosen contract (non-admin + allowlist, three commands, revision-gated push), and that two stacked PRs are ready. Plain, factual, no speculation beyond what was measured.

- [ ] **Step 2: Update memory + KB** — add to the memory file: `/stat/sta` coverage numbers, `last_uplink` fallback, raw uplink keys, branch names, local PR body paths, live-verification result. Then `knowledge_write` with `supersedes=9447a1be-dedc-5988-89c9-ab61916a1515` and the same content.

- [ ] **Step 3: Report to Justin** — branch names + HEAD SHAs, test/coverage numbers, live pass/fail per criterion, and the three local draft paths. Posting waits for his go-ahead.
