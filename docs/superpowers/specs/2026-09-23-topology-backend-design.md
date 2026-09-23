# Topology backend (upstream #165) — design

- **Date:** 2026-09-23
- **Upstream issues:** ruaan-deysel/ha-unifi-insights#165 (this spec), #166 (card — separate design cycle, builds on this contract)
- **Status:** approved in brainstorming; pending written-spec review
- **Branch policy:** this spec lives on local-only branch `design/topology`; it is never pushed upstream.

## 1. Goal

Expose a per-site network topology graph (gateway → switches/APs → clients) from data the
integration already polls, through an authenticated WebSocket API whose contract is designed
up front for the #166 Lovelace card. Works identically in `local` and `remote` connection
modes (stored data shape is mode-independent).

**Non-goals:** throughput/latency/DPI/speed tests, firmware/uptime/signal in the graph, new
API clients, a card (that is #166), graph in entity attributes, graph in diagnostics.

## 2. Ground truth — live probe (2026-09-23, VM113, remote mode, UDM Pro SE + 7 devices, 58 clients)

The issue assumes the official v1 API returns `uplink.deviceId`. **It does not on real hardware.**

| Relationship | v1 coordinator data | Actual source |
|---|---|---|
| device → parent device | `uplink` null 8/8; `type` null 8/8 | legacy `/stat/device` `uplink` {`uplink_mac`, `uplink_remote_port`, `type` wire/wireless, `speed`} — already fetched every 30 s (`coordinators/device.py` `get_legacy_site_devices`) and discarded |
| device kind | `type` null; UDM Pro SE reports only `features: ["switching"]` | legacy `type` (`udm`/`uxg`/`ugw`/`usw`/`uap`) |
| device uplink port (child side) | legacy-normalised `ports[].is_uplink` ✔ | — |
| client → AP/switch | `uplinkDeviceId` resolves 58/58 ✔ | — |
| client switch port / VLAN | `swPort`/`swMac`/`apMac`/`vlan`/`networkId` null 58/58 | legacy `/stat/sta` — already fetched every 5 min (`coordinators/config.py` `get_active_legacy`) only for SSID counts |
| VLAN names | never fetched | `networks.get_all(site_id)` (exists, unused) |

v1 device ids are UUIDs and differ from legacy `_id` → parent resolution joins **by normalised MAC**.
Client ids are UUIDs (58/58).

## 3. Delivery shape

Two stacked PRs, prepared locally, posted together:

- **PR 1 — `feat/topology-graph`** (off `upstream/main`): legacy uplink merge, pure builder, WebSocket API.
- **PR 2 — `feat/topology-client-links`** (stacked on PR 1): client port/VLAN + network names. Fills
  optional contract fields only — no contract change.

Upstream accepts only `main` as base, so PR 2's diff includes PR 1's commits; its body states
"stacked on #X — review after". Both bodies follow the house PR format.

## 4. Data contract — `TOPOLOGY_SCHEMA_VERSION = 1`

One snapshot per site:

```
{
  schema_version: 1,
  entry_id: str, site_id: str, site_name: str,
  revision: str,          # sha256 of canonical JSON of everything below
  status: "ok" | "partial" | "unavailable",
  issues: [{code: str, severity: "info" | "warning" | "error"}],
  nodes: [Node], edges: [Edge], unresolved: [Unresolved],
  truncation: {clients_total: int, clients_included: int} | null
}
```

**Node**
- `id` — opaque: `dev:<v1 uuid>` / `cli:<v1 uuid>`; a MAC-keyed device id becomes
  `dev:h<sha256(entry_id + mac)[:16]>` (never a raw MAC).
- `kind` — `gateway | switch | access_point | client | other`.
- `name` — str; `model` — str | absent (devices only).
- `state` — `online | offline | unknown`.
- `ha_device_id` — str | absent (infrastructure devices, via device registry).
- `connection` — `wired | wireless` (clients only).
- PR 2 adds optional `vlan_id: int`, `network_name: str`.

**Edge** — always child → parent.
- `source`, `target` (node ids), `medium` — `wired | wireless | unknown`.
- optional `speed_mbps`, `parent_port`, `child_port`, `poe_power_w` (watts drawn at the parent port).
- PR 2 fills `parent_port` for wired client edges.

**Unresolved** — `{node_id, reason}`, reason ∈ `parent_not_found | no_uplink_data | mac_keyed_parent`.
Invariant: **every edge endpoint exists in `nodes`.** A node with no parent reference and legacy
kind `gateway` is a root, not unresolved.

**Allowlist:** the builder emits only the fields above. MACs, IPs, hostnames, firmware, SSIDs,
byte counters never appear.

**Client cap:** server hard cap 500 clients/site; request `max_clients` may lower it (min 0).
Ordering when capped: wired first, then by name, then id. Over cap → `truncation` populated.

**Accepted trade-off:** `poe_power_w` changes most polls, so an active subscription receives a
snapshot roughly every 30 s. Revision dedupe still suppresses identical snapshots.

## 5. Coordinator changes

### PR 1 — `coordinators/device.py`
- New `_merge_legacy_uplink_data(device, legacy_devices_by_mac)` called beside
  `_merge_legacy_port_data` / `_merge_legacy_wan_data`. Writes one namespaced block:
  `device["topology"] = {uplink_mac, uplink_remote_port, uplink_type, uplink_speed, legacy_type}`
  (keys present only when the legacy source has them; MAC normalised lower-case).
- Legacy-only path (`_legacy_device_to_v1_dict`, v1 5xx) produces the identical block.
- No new API calls. Existing `ports`/`uplink` consumers unchanged.
- Diagnostics: existing recursive MAC placeholdering covers `uplink_mac`; add a test from a real
  legacy dict proving it.

### PR 2 — `coordinators/config.py`
- Lift the `/stat/sta` fetch out of the Wi-Fi enrichment `try` (today it runs only when Wi-Fi
  models loaded) into its own guarded per-site fetch; the same response still feeds `_enrich_wifi`
  (no extra call).
- Store `client_links[site_id][normalised mac] = {sw_mac, sw_port, ap_mac, vlan, network_id}`.
- New `networks[site_id][network_id] = {name, vlan_id, purpose}` from `networks.get_all(site_id)`
  — the only new API call (one per site per 5 min). Per-site failure logs and skips, following the
  Wi-Fi pattern; never fails the refresh.
- Facade exposes both. Diagnostics: redact subnet / gateway IP keys; VLAN ids and network names
  stay readable; tests from real model dumps.
- **Accepted trade-off:** client port/VLAN may lag the 30 s client edge by up to 5 min.

## 6. Builder — `custom_components/unifi_insights/topology.py`

Pure module: no Home Assistant imports, no I/O. Contract `TypedDict`s + `TOPOLOGY_SCHEMA_VERSION` live here.

```
build_site_topology(
    data: dict[str, Any],            # facade data
    entry_id: str,
    site_id: str,
    *,
    ha_device_ids: Mapping[str, str],  # v1 device id -> HA device registry id
    max_clients: int = 500,
) -> SiteTopology
```

Steps:
1. Device nodes. `kind`: legacy `type` (`udm|uxg|ugw|udr|ucg` → gateway, `usw` → switch,
   `uap` → access_point) → v1 `type` → `features` (`accessPoint` → access_point) → `other`.
2. Per-site MAC index: normalised `macAddress` → node id.
3. Device edges from `topology.uplink_mac` via the MAC index. `child_port` = the child's
   `is_uplink` port index; `parent_port` = `uplink_remote_port`; `speed_mbps` = `uplink_speed`;
   `medium` from `uplink_type` (`wire` → wired, `wireless` → wireless); `poe_power_w` from the
   parent's port entry at `parent_port` when PoE data is present. Self-edges skipped. Unmatched →
   `unresolved`.
4. Client nodes + edges from `uplinkDeviceId` / `uplink_device_id` matched against device ids.
   (PR 2: fall back to `client_links` `sw_mac`/`ap_mac` through the MAC index; enrich port/VLAN;
   VLAN name via `networks`.)
5. Client cap + `truncation`.
6. Status/issues (table below), deterministic sort (nodes by kind then id; edges by source then
   target), `revision` = sha256 of canonical JSON (`sort_keys=True`, compact separators) of the
   snapshot minus `revision`.

All field reads use `get_field()` (camelCase/snake_case tolerant). Module docstring documents that
the coordinator holds only clients the API currently returns — offline clients are not in the graph.

| Condition | status | issue (severity) |
|---|---|---|
| device coordinator unavailable / no device data for site | `unavailable` | `devices_unavailable` (error) |
| devices present but none carries a `topology` block | `partial` | `legacy_uplink_missing` (warning) |
| ≥1 unresolved parent | `partial` | `parents_unresolved` (warning) |
| client cap applied | `partial` | `clients_truncated` (info) |
| otherwise | `ok` | — |

## 7. WebSocket API — `custom_components/unifi_insights/websocket_api.py`

Registered once from `async_setup` in `__init__.py`, beside `async_setup_services`. Default
authenticated access (no `require_admin`) — any logged-in user; privacy comes from the allowlist.

| Command | Params | Result |
|---|---|---|
| `unifi_insights/topology/sources` | — | `[{entry_id, title, sites: [{id, name}]}]` for loaded entries |
| `unifi_insights/topology/get` | `entry_id`, `site_id`, `max_clients?` | one snapshot |
| `unifi_insights/topology/subscribe` | same as `get` | initial snapshot, then pushed snapshots |

- Scoping: entry must exist, belong to `DOMAIN`, be loaded (guard `runtime_data` like
  `services.py`); `site_id` must be in `config_coordinator.get_site_ids()`.
- Error codes: `entry_not_found`, `entry_not_loaded`, `site_not_selected`.
- `ha_device_ids` resolved from the device registry using the existing identifier
  `(DOMAIN, f"{site_id}_{device_id}")`.
- Subscribe: `facade.async_add_listener` → rebuild → send only when `revision` changed. Unsub
  stored in `connection.subscriptions[msg_id]` (removed on unsubscribe / connection close) and
  registered with `entry.async_on_unload`. Facade does not poll → zero added API load.
- `manifest.json`: add `websocket_api` to `dependencies`; hassfest confirms.

## 8. Testing

Environment: `.local/ha-test-venv-ci` (HA 2026.9.3, matches CI). Ruff via repo config only (never
`--config`). Coverage gate ≥ 90%.

- `tests/test_topology.py` — real `Device`/`Client` model dumps + real-shaped legacy dicts:
  tree edges; gateway root; MAC-keyed device; missing parent → `unresolved`; self-edge skipped;
  kind fallbacks; port/PoE enrichment; client edges; cap/`truncation` ordering; multi-site
  isolation; deterministic ordering; revision stable on identical input and changed on change;
  **every edge endpoint in `nodes`**; allowlist denylist check (no MAC/IP/hostname anywhere in the
  serialised output, reusing diagnostics redaction keys).
- Sanitised fixture mirroring the live layout with fictitious MACs/names: gateway → 24-port
  switch (parent port 11, 10 G) → six children on parent ports 6, 8, 10, 12, 17, 20 (one AP at
  2.5 G, one PDU at 100 M).
- `tests/test_websocket_api.py` (`hass_ws_client`): all three commands; non-admin user succeeds;
  each error code incl. not-loaded entry; push on a graph-changing coordinator update; no push on
  an unchanged update; listener cleanup on unsubscribe and on unload.
- `tests/test_coordinators.py`: uplink block on v1+legacy merge and legacy-only paths.
- `tests/test_diagnostics.py`: `uplink_mac` placeholdered.
- PR 2: `client_links`/`networks` fetch success, per-site failure isolation, non-selected sites not
  fetched, diagnostics redaction, builder port/VLAN enrichment + `sw_mac`/`ap_mac` fallback.

## 9. Live verification (VM113)

1. `ha-hacs-branch-deploy.py snapshot` → deploy PR 2 branch via fork HACS repo `1330343416`
   with a manifest fingerprint → full restart → settle.
2. `ha-ws-client.py` → `topology/sources`, `topology/get`.
3. **Pass:** 7 device edges exactly matching `unifi_list_devices` legacy uplinks (6 children →
   24-port switch on ports 6/8/10/12/17/20; switch → gateway port 11); ~58 client edges;
   `status: ok`; `unresolved` empty; no MAC/IP in payload; `subscribe` pushes after a poll;
   PR 2: VLAN + port on wired clients.
4. Roll back to upstream HACS repo `917968755`.

## 10. Upstream communication

Draft (not posted without Justin's OK) a comment on #165 reporting the live finding — v1
`uplink`/`type` null on real hardware; legacy `/stat/device` uplink is the real source — so the
maintainer and CodeRabbit plan from facts.

## 11. Risks

- Legacy endpoint unavailable (some consoles/permissions) → `legacy_uplink_missing`, graph still
  renders clients-to-device; no crash.
- Legacy uplink shape varies by firmware (e.g. wireless mesh uplinks carry `uplink_mac` of the
  parent AP) → normaliser tolerates missing keys; mesh verified by unit fixture only (no mesh on
  VM113 — labelled unverified live).
- PoE churn → ~30 s pushes while subscribed (accepted).
