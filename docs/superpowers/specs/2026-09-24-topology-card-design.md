# Topology Lovelace card (#166) — design spec

- **Issue:** ruaan-deysel/ha-unifi-insights#166 (depends on #165, delivered by #167 + #168, merged)
- **Date:** 2026-09-24
- **Status:** approved in brainstorming; pending written-spec review
- **Scope:** the whole of #166 in one PR — MVP card *and* interactive pan/zoom graph (Justin, 2026-09-24)
- **Backend contract:** `topology_contract.py` schema 1, WebSocket `unifi_insights/topology/{sources,get,subscribe}` (upstream `main`)

## 1. Goal and success criteria

Ship a Lovelace card, installed with the integration itself, that renders the per-site topology
graph from the #165 contract: interactive graph + accessible list, per-card site binding, clear
loading/empty/degraded/error states, HA-theme-native, keyboard- and touch-usable, typed and tested
in CI.

Success = every row of the traceability matrix (§10) is met, CI is green (Python + new frontend
job), the card works live on VM113 against the Crestwood console, and the maintainer merges it.

### Decisions (brainstorming, 2026-09-24)

| # | Decision | Chosen | Rejected |
|---|---|---|---|
| D1 | Scope | Full #166 in one PR, layered commits | MVP-then-graph split |
| D2 | Packaging | Integration serves the bundle (static path + `add_extra_js_url`), built file committed | Separate HACS plugin repo (two installs, version skew); plain untyped JS (fails "typed + CI") |
| D3 | Multi-site | Per-card binding in editor + optional in-card site selector; auto-pick when one source | Selector-only; all sites in one canvas |
| D4 | Clients | Grouped per parent device by default, expandable; `collapsed \| expanded \| hidden` | Always individual nodes; never in graph |
| D5 | Views | Graph view + list (ARIA tree) view, toggle in card | Graph only; separate list card |
| D6 | Renderer | Lit + SVG + `d3-hierarchy` (layout) + `d3-zoom` (pan/zoom) | Cytoscape.js (≈400 KB canvas, poor a11y/theming); hand-rolled layout + gestures |

The Gemini prototype (`unifi-insights-topology-card.js` v1.1.0, VM113 `/network-topology`) is a
**behavioural reference only** — not ported. Its hardening lessons are carried as requirements
(XSS-free rendering, focus-safe search, single-subscription guard, `entry_unloaded` resubscribe,
live flag set inside the callback, orphan roots, BFS depth, no dead fields).

## 2. Architecture and packaging

### Repo layout

```
frontend/                          # TypeScript source — dev only, not loaded by HA
  package.json, package-lock.json, tsconfig.json, vite.config.ts, eslint.config.js, .nvmrc (22)
  src/
    index.ts                       # defines elements (guarded), pushes window.customCards
    topology-card.ts               # <unifi-insights-topology-card>
    topology-card-editor.ts        # <unifi-insights-topology-card-editor>
    contract.ts                    # TS mirror of topology_contract.py schema 1 — ONLY wire-format file
    ha-types.ts                    # minimal local HomeAssistant/Connection types (no custom-card-helpers)
    config.ts                      # card config type, defaults, setConfig validation
    data/subscription.ts           # sources/subscribe lifecycle, backoff, revision gate
    data/state.ts                  # card state machine (§5)
    model/graph-model.ts           # contract → view model (pure)
    views/graph-view.ts            # SVG + d3-hierarchy + d3-zoom
    views/list-view.ts             # ARIA tree
    views/detail-panel.ts
    icons.ts, styles.ts, localize.ts
  test/                            # Vitest + happy-dom; fixtures/ shared with Python (§8)
custom_components/unifi_insights/
  frontend/topology-card.js        # built ES module bundle — committed
  frontend.py                      # new: static path + extra-JS registration
```

Runtime dependencies: `lit`, `d3-hierarchy`, `d3-zoom` (+ its `d3-selection`/`d3-transition`
peers), `@mdi/js`. Dev: `typescript` (strict), `vite` (library mode, single ES file, minified),
`vitest`, `happy-dom`, `eslint` + `typescript-eslint`, `axe-core`, `@types/d3-*`.
`custom-card-helpers` is **not** used (unmaintained); the few HA types needed live in `ha-types.ts`.

**Bundle budget:** ≤ 150 KB minified, asserted in CI.

### Backend wiring (the only Python change)

- `frontend.py::async_register_frontend(hass)` called from `async_setup` (once per HA instance,
  like the WS commands — `__init__.py` `async_setup`), guarded by a `hass.data` flag so a second
  call is a no-op.
- `await hass.http.async_register_static_paths([StaticPathConfig("/unifi_insights/topology-card.js",
  <path>, cache_headers=True)])` (`homeassistant.components.http.StaticPathConfig`).
- `frontend.add_extra_js_url(hass, "/unifi_insights/topology-card.js?v=<manifest version>")` —
  version query busts browser cache on each release.
- `manifest.json` `dependencies` += `http`, `frontend` (both core).
- No unregister on last-entry unload (static paths cannot be removed); the card renders
  `no_sources` instead.

### Element registration

- Tag names `unifi-insights-topology-card` / `unifi-insights-topology-card-editor`; every
  `customElements.define` guarded by `customElements.get(...)`. (The VM113 prototype registers the
  same card tag — live testing removes its resource first, §8.)
- `window.customCards.push({type, name: "UniFi Insights Topology", description, preview: true,
  documentationURL})`, de-duplicated.
- `static getConfigElement()` → editor; `static getStubConfig(hass)` → first source's
  `entry_id`/`site_id` (async `sources` call) so the picker preview shows real data.

### Coupling boundary

`contract.ts` is the only module aware of the wire format. It exports the schema-1 types, the
literal unions (`NodeKind = gateway|switch|access_point|client|other`, `NodeState`, `LinkMedium`,
`ClientConnection`, `TopologyStatus`, `IssueSeverity`, `UnresolvedReason`), `MAX_CLIENTS_PER_SITE
= 500`, and `parseSnapshot(raw)` which rejects `schema_version !== 1` (→ `incompatible` state).
Doc comments on every field state its source and semantics — this is the "contract documentation in
code" the issue asks for.

**Edge direction (load-bearing):** `edge.source` = **child**, `edge.target` = **parent**
(`topology.py` `_client_edge`/`_device_edge`). `subscribe` pushes a **full snapshot** whenever
`revision` changes — incremental behaviour is the card's job (§4).

### CI

New `frontend` job in `.github/workflows/test.yml` (Node from `frontend/.nvmrc`):
`npm ci` → `npm run lint` → `npm run typecheck` → `npm test -- --coverage` (threshold §8) →
`npm run build` → bundle-size check → `git diff --exit-code custom_components/unifi_insights/frontend/`
(committed bundle must equal a fresh build). `dependabot.yml` gains an `npm` ecosystem entry for
`/frontend`. No Node hooks in `pre-commit` (Python-only contributors unaffected). `AGENTS.md`
validation section gains the four `npm run` commands.

## 3. Card config and editor

```yaml
type: custom:unifi-insights-topology-card
entry_id: 01J…          # with site_id; auto-picked when exactly one source/site exists
site_id: default
title: Network          # default: payload site_name
view: graph             # graph | list
show_site_selector: false
clients: collapsed      # collapsed | expanded | hidden
kinds: [gateway, switch, access_point, client, other]   # initial filter
density: comfortable    # comfortable | compact
orientation: vertical   # vertical (gateway top) | horizontal (gateway left)
show_labels: true
max_clients: 500        # 1..500, passed to subscribe
```

- All keys except `type` optional. `setConfig` validates types/enums/ranges and throws a
  descriptive `Error` (HA renders its standard error card).
- Runtime UI changes (filter chips, zoom, expanded groups, view toggle, in-card site switch) are
  **session state only** — never written back to config.
- **Editor** — `ha-form` schema: site (`select` from `sources`, label `"<entry title> — <site
  name>"`, sets both ids), `view`/`clients`/`density`/`orientation` (select), `kinds`
  (multi-select), `show_site_selector`/`show_labels` (boolean), `title` (text), `max_clients`
  (number). Before first render the editor calls `window.loadCardHelpers()` and instantiates a
  built-in card's config element once so `ha-form` is registered (lazy-load workaround).
- **Sizing** — `getGridOptions()` → `{columns: 12, rows: 8, min_columns: 6, min_rows: 4}`;
  `getCardSize()` → 8; panel view: `:host` flex fills 100% height; list view scrolls internally.
- **Localization** — `localize.ts` string table, English bundled, keyed off
  `hass.locale.language`, English fallback. (Integration `translations/` is backend-only.)

## 4. Data model and graph view

```
subscription ──SiteTopology (new revision)──► buildModel(snapshot, uiState) ──► GraphModel
                                                     ▲                              │
                                uiState: kinds, clients mode, expanded groups       ▼
                                                              graph-view / list-view / detail-panel
```

### `model/graph-model.ts` (pure, no DOM)

- Index nodes by `id`; `parentOf[edge.source] = edge.target`.
- **Roots** = nodes without a parent (gateway + orphan devices). Parentless clients go under one
  synthetic "Unconnected clients" group node, not separate roots.
- **Cycle guard** — walking up from a node, a revisit cuts the closing edge; that node becomes a root.
- **Kind filter** — hidden nodes are removed; their children re-attach to the nearest visible
  ancestor via a `viaHidden: true` link (rendered dashed, detail text "via hidden <kind>").
- **Client grouping** — `collapsed`: per parent device one `ClientGroup` (`count`, `wired`,
  `wireless`, `offline`); expanding swaps in individual client nodes. `hidden`: no client nodes;
  counts still on the parent. `expanded`: all groups start expanded.
- Output `{roots, nodesById, childrenOf, linkOf, groups, stats}`; memoized on
  `(revision, uiState)`.

### `views/graph-view.ts`

- **Layout** — `d3.tree().nodeSize(density)` over a synthetic super-root (forest → one tree);
  horizontal orientation swaps axes.
- **Render** — SVG `<g>` per node keyed by id (Lit `repeat`) inside a zoom `<g>`; curved link
  paths; link label `p<parent_port> · <speed>` (e.g. `p11 · 10G`) + PoE marker when
  `poe_power_w` present; wireless links dotted; `viaHidden` dashed.
- **Incremental update** — nodes still present tween old→new position (~250 ms), enters fade in,
  exits fade out; zoom transform and selection preserved; no auto re-fit after the first render.
- **Throttle** — snapshots/UI changes coalesced to one layout per `requestAnimationFrame`.
- **Culling** — above 300 visible nodes, only nodes/links intersecting viewport + margin are in
  the DOM, recomputed on zoom *end*.
- **Zoom** — `d3-zoom` scale `[0.2, 4]`; toolbar fit / + / − / reset; auto-fit on first render.
  In dashboard grids wheel-zoom requires Ctrl/⌘ (hint overlay "Use Ctrl + scroll to zoom"); in
  panel view plain wheel zooms. Touch pan/pinch always.
- **Selection** — click/tap/Enter selects; selected node ring + highlighted path to root; detail
  panel opens (side panel ≥ 600 px card width, bottom sheet below). Esc closes panel, then clears
  selection.

### `views/detail-panel.ts`

- Device: name, kind, model, state; uplink (parent name, `parent_port`→`child_port`, speed,
  medium, PoE W); client counts; **Open device** → `/config/devices/device/<ha_device_id>` when
  present.
- Client: connection, VLAN, network name, parent + port.
- Group: searchable member list; selecting a member selects that client (expanding the group).

### `views/list-view.ts`

Same `GraphModel`. Indented WAI-ARIA `tree`, expand/collapse, search filters to matches plus
ancestors. Static shell; only the tree body re-renders on search (focus preserved). Row
selection opens the same detail panel.

## 5. Subscription lifecycle, states, errors, privacy

### `data/subscription.ts` (one per card)

- Start in `connectedCallback`, stop in `disconnectedCallback` (unsubscribe, cancel pending
  retry). Single in-flight guard + generation token: concurrent `set hass`/`connectedCallback`
  can never open two subscriptions; a stale generation's callbacks are ignored.
- Resubscribe only when `(entry_id, site_id, max_clients)` or the `hass.connection` object
  changes — not on every `hass` assignment.
- `hass.connection.subscribeMessage(cb, {type: "unifi_insights/topology/subscribe", …})`.
  Socket reconnects are handled by home-assistant-js-websocket's own resubscribe; the card's
  retry covers only server-ended streams.
- **Server-ended stream** (`entry_unloaded` final event — `websocket_api.py`
  `_async_entry_unloaded`, subscription already removed server-side): state `reloading`, resubscribe
  with backoff 2 s → 4 s → 8 s … cap 60 s, ±20 % jitter; `entry_not_loaded` errors keep retrying;
  backoff resets on first snapshot.
- "Live" flag set **inside** the event callback (HA can coalesce the subscribe result and the
  first event in one frame).
- Drop snapshots whose `revision` equals the last applied one.

### `data/state.ts` → UI

| State | Trigger | UI |
|---|---|---|
| `loading` | before first snapshot | skeleton + spinner; live region "Loading network topology" |
| `no_sources` | `sources` → `[]` | "No UniFi Insights integration is loaded." + button → `/config/integrations/integration/unifi_insights` |
| `unconfigured` | >1 source and no binding | "Choose a site" + "Edit card" |
| `empty` | `status: ok`, 0 nodes | "No devices reported for {site}." |
| `ok` | `status: ok` | graph/list |
| `partial` | `status: partial` | graph + warning banner, one line per issue |
| `unavailable` | `status: unavailable` | last good graph greyed + "stale" badge + reason; message only if none |
| `reloading` | issue `entry_unloaded` | as `unavailable` + "Reconnecting…" |
| `error` | WS error result | per-code message + action |
| `incompatible` | `schema_version !== 1` | "Card and integration versions don't match — refresh the browser (clear cache) after updating." |

| Code | Message | Action |
|---|---|---|
| `site_unavailable` | Site data temporarily unavailable; will recover automatically. | — |
| `devices_unavailable` | Device data unavailable; showing clients only. | Integration |
| `legacy_uplink_missing` (info) | Uplink details unavailable; device links may be missing. | — |
| `parents_unresolved` | {n} devices couldn't be placed; shown as separate roots. | — |
| `clients_truncated` | Showing {included} of {total} clients (limit {max}). | — |
| `entry_not_found`, `site_not_selected` | The configured site no longer exists or is disabled. | Edit card |
| `entry_not_loaded` | Integration isn't loaded (retrying). | Integration |
| unknown | generic text including the raw code | — |

### Privacy

- Card renders only allowlisted contract fields; no other API calls, no entity-attribute reads, no
  export/copy-all. Node ids are already HMAC'd server-side.
- Diagnostics and #139 redaction untouched — no new export path.
- Console output limited to schema-mismatch and unexpected-error warnings, never payload data.
- All text rendered through Lit template bindings (auto-escaped) — no `innerHTML`, no
  `unsafeHTML`, no inline event-handler strings.

## 6. Accessibility, responsiveness, theming

### Icons (`@mdi/js` paths, tree-shaken)

gateway `mdiRouterNetwork`, switch `mdiSwitch`, access_point `mdiAccessPoint`, other `mdiDevices`,
wired client `mdiLanConnect`, wireless client `mdiWifi`, client group `mdiDevices` + count badge.
State encoded three ways: status dot + text ("Offline") + reduced opacity for offline — **never
colour alone**.

### Theming

HA variables only: `--card-background-color`, `--primary-text-color`, `--secondary-text-color`,
`--divider-color`, `--primary-color` (selection/focus), `--success-color` / `--warning-color` /
`--error-color` / `--disabled-text-color` (states), `ha-card` frame. No hard-coded hex beyond
`var(--x, fallback)` defaults. `forced-colors: active` → `CanvasText`/`Highlight`.

### Keyboard

- Graph: one tab stop (roving tabindex); arrows follow structure — parent (↑ vertical / ←
  horizontal), first child (↓ / →), siblings (← → / ↑ ↓); Enter/Space select or expand group; Esc
  close panel then clear selection; `+` `-` `0` zoom in/out/fit; focused node auto-panned into view.
- Toolbar (view toggle, filter chips, zoom buttons, site selector): ordinary tab stops using HA
  components (`ha-button`, `ha-icon-button`, `ha-select`).
- List: full WAI-ARIA tree pattern (↑ ↓, → expand/child, ← collapse/parent, Home/End, type-ahead).
- `:focus-visible` ring, 2 px `--primary-color`, never suppressed.

### Screen readers

- Graph `role="application"`, `aria-roledescription="network topology"`,
  `aria-label="{site} topology, {n} devices, {m} clients"`.
- Node `role="button"` + label e.g. "Switch Pro Max 24, online, 12 clients, uplink port 11 at 10
  gigabit"; groups carry `aria-expanded`.
- Graph and list are peer views; the README recommends list view for screen-reader users.
- Polite `aria-live` region for state changes, throttled to one message per 5 s.

### Motion, responsiveness

- `prefers-reduced-motion: reduce` → 0 ms tweens, instant zoom/fit, no skeleton shimmer.
- Container queries on card width (not viewport). < 600 px: bottom-sheet detail panel, toolbar
  collapses into an overflow menu, compact density unless configured.
- Tap targets ≥ 44 × 44 px (invisible hit circles on small nodes/labels); `touch-action: none` on
  the graph canvas only.

## 7. HA frontend API compatibility

Card uses: `window.customCards`, `getConfigElement`/`getStubConfig`, `getGridOptions`,
`getCardSize`, `window.loadCardHelpers`, `ha-form` (select/boolean/number/text selectors),
`ha-card`, `ha-button`, `ha-icon-button`, `ha-select`, `hass.connection.subscribeMessage`,
`hass.callWS`, `hass.locale`, `hass.themes.darkMode`. Implementation Task 0 records the HA version
that introduced each and confirms all are ≤ the `hacs.json` minimum (2026.6.0); any that are not
get a feature-detected fallback. Backend: `StaticPathConfig` / `async_register_static_paths`
(`homeassistant/components/http/server.py`) and `add_extra_js_url`
(`homeassistant/components/frontend/__init__.py`) — present in HA 2026.9.3 (verified).

## 8. Testing and verification

### Frontend (Vitest + happy-dom)

- **graph-model** — reversed edge direction; forest roots; orphans; cycle cut; "Unconnected
  clients"; kind filter re-attachment + `viaHidden`; three client modes; group counts; memoization.
- **subscription** — no double subscribe under `set hass`/connect race; resubscribe only on key or
  connection change; `entry_unloaded` → backoff sequence → reset; revision dedupe; live flag in
  callback; teardown cancels retry and unsubscribes.
- **state** — every state-table row, every issue/error code, unknown code, schema mismatch.
- **interaction** (mounted card, mock `hass`) — keyboard traversal graph + list; select, Esc,
  group expand; filter chips; search keeps focus; view toggle; site selector; reduced motion
  (`matchMedia` mock); bottom sheet < 600 px.
- **editor** — options from `sources`; site pick sets both ids; `setConfig` rejects invalid
  values; `getStubConfig`.
- **a11y** — `axe-core` on rendered card in `ok`, `partial`, `error`, list view; aria-label text
  assertions.
- **benchmark** — 500 clients / 20 devices: model build + layout within a budget; DOM node count
  bounded with culling. Generous CI budget (reported, not flaky).
- Coverage threshold: 90 % lines on `src/`.

### Contract drift guard (both sides)

- Python test runs `build_site_topology` on existing test fixtures and compares with committed
  `frontend/test/fixtures/site-topology.json`; `UPDATE_TOPOLOGY_FIXTURE=1` regenerates.
- TS test imports the same JSON typed as `SiteTopology` (type-checked) and runs the model on it.
- `sources` fixture with 2 entries / 3 sites for multi-site.

### Python

`tests/test_frontend.py`: static path + extra JS URL registered exactly once across multiple
entries; URL carries manifest version; repeat `async_register_frontend` is a no-op. Full existing
suite, `mypy`, `bandit`, ruff (zero new findings) as usual.

### Live (VM113, before ready-for-review)

1. Remove the prototype dashboard resource/`/network-topology` dashboard; deploy branch via
   `~/ai-tools/scripts/ha-hacs-branch-deploy.py`.
2. Add card from picker, configure via editor (Crestwood).
3. `~/ai-tools/scripts/ha-dashboard-screenshot.py` dark + light: graph, list, detail panel,
   partial banner, mobile width.
4. Checks: 7 device edges match the controller uplink table; integration reload → `reloading` →
   auto-recovery; keyboard walkthrough; Playwright pinch/zoom at mobile width; no new log lines.
5. Roll back: `ha-hacs-branch-deploy.py deploy --repo 917968755 --version <current release>`.

## 9. PR shape

One PR, `Closes #166`, layered commits:

1. `feat(frontend): serve topology card bundle from the integration` (Python + tests)
2. `build(frontend): TypeScript/Lit/Vite toolchain and CI job`
3. `feat(frontend): topology contract types, subscription and state machine`
4. `feat(frontend): topology graph model`
5. `feat(frontend): list view and detail panel`
6. `feat(frontend): interactive graph view`
7. `feat(frontend): card editor and picker registration`
8. `feat(frontend): accessibility, responsive and theming polish`
9. `test(frontend): performance benchmark and contract fixture guard`
10. `docs: README card section + CHANGELOG [Unreleased]`

Body follows `.github/pull_request_template.md` in the shape of merged #167, with the §10 matrix as
the acceptance checklist. Drafted locally first (`.local/pr-bodies/topology-card-166.md`).

## 10. #166 traceability matrix

| #166 requirement | Spec § |
|---|---|
| Card registration + discovery in dashboard UI | 2 (customCards, auto-loaded bundle) |
| Configurable from UI (AC) | 3 (editor) |
| Pan/zoom | 4 (d3-zoom, toolbar, touch) |
| Node selection with detail panel | 4 |
| Optional filters gateway/switch/AP/client | 3 (`kinds`), 4 (chips, re-attachment) |
| Loading / empty / degraded / error with actionable message | 5 |
| Multi-site in one card instance | 3 (binding + selector), 8 (multi-site fixture) |
| Appearance + density for large networks | 3 (`density`, `orientation`, `show_labels`, `clients`, `max_clients`) |
| No full re-render per refresh | 4 (keyed repeat, revision gate) |
| Incremental graph updates | 4 (position-preserving tween) |
| Virtualization / throttled layout | 4 (rAF coalescing, culling > 300) |
| Upper bound + graceful degradation for large client sets | 4 (grouping), 5 (`clients_truncated`) |
| Keyboard navigation | 6 |
| Screen-reader labels | 6 |
| Contrast-safe + reduced motion | 6 |
| Mobile-first touch + tap targets | 6 |
| Panel mode + dashboard grids | 3 (sizing) |
| HA theme variables, dark/light, no hard-coded colours | 6 |
| Consistent iconography + state semantics | 6 |
| No sensitive attributes in frontend payloads | 5 (privacy) |
| Diagnostics/export redaction preserved | 5 (privacy) |
| Typed frontend code | 2 (strict TS) |
| Frontend lint/test in CI (AC) | 2 (CI job) |
| Contract documented in code comments/tests | 2 (`contract.ts`), 8 (drift guard) |
| Minimal backend/renderer coupling | 2 (coupling boundary) |
| Performance profiling | 8 (benchmark) |
| Unit + interaction tests | 8 |
| Compatibility with current HA versions | 7 |
| Single-site and multi-site render (AC) | 8 |
| Smooth desktop + mobile on larger graphs (AC) | 4, 6, 8 (benchmark + live mobile check) |
