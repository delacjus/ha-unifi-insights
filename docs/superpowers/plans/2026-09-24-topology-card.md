# Topology Lovelace Card (#166) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Lovelace card, served by the `unifi_insights` integration itself, that renders each site's network topology from the #165 WebSocket contract as an interactive graph and an accessible list, covering every requirement in ruaan-deysel/ha-unifi-insights#166.

**Architecture:** TypeScript/Lit source in a new top-level `frontend/` folder, built by Vite into one committed ES module at `custom_components/unifi_insights/frontend/topology-card.js`. A new `frontend.py` serves that file and registers it with `add_extra_js_url` from `async_setup`. Inside the card: `contract.ts` (only wire-format module) → `data/` (subscription lifecycle + state machine) → `model/` (pure graph model, layout, navigation) → `views/` (graph, list, detail panel) → `topology-card.ts` shell + `topology-card-editor.ts`.

**Tech Stack:** Lit 3.3.3, d3-hierarchy 3.1.2, d3-zoom 3.0.0 (+ d3-selection 3.0.0, d3-transition 3.0.1), @mdi/js 7.4.47, TypeScript 6.0.3 (strict), Vite 8.3.1, Vitest 5.0.1 + jsdom 30.1.1, ESLint 10.11.0 + typescript-eslint 8.70.1, axe-core 4.13.0, Node 22. Python side: Home Assistant 2026.9.x test venv.

**Spec:** `docs/superpowers/specs/2026-09-24-topology-card-design.md` (branch `design/topology`, commit d6fa11a). Read §5 (state table) and §10 (traceability matrix) before starting any task.

## Global Constraints

- Implementation worktree: `~/ha-unifi-insights-card`, branch `feat/topology-card`, created from `upstream/main` (Task 0). All paths below are relative to it.
- Python tools: `VENV=~/ha-unifi-insights/.local/ha-test-venv-ci/bin` (HA 2026.9.3, matches CI). Never use `.local/ha-test-venv` (stale). Never pass `--config` to ruff; `.ruff.toml` wins over `pyproject.toml`.
- Node 22 (`frontend/.nvmrc` = `22`; local is v22.23.2). Exact dependency versions as listed in Tech Stack. TypeScript must stay `<6.1` (typescript-eslint peer range).
- HA minimum: `hacs.json` `"homeassistant": "2026.6.0"`. Every frontend API used must exist at that version (Task 0 records the proof).
- Tag names: card `unifi-insights-topology-card`, editor `unifi-insights-topology-card-editor`, internal views `uit-graph-view`, `uit-list-view`, `uit-detail-panel`. Every `customElements.define` goes through `defineOnce`.
- Bundle: URL `/unifi_insights/topology-card.js`, file `custom_components/unifi_insights/frontend/topology-card.js`, committed, ≤ 150 KB minified. Every task that changes `frontend/src/` rebuilds and commits the bundle in the same commit.
- **Edge direction:** `edge.source` = CHILD, `edge.target` = PARENT.
- `revision` is `""` on every `unavailable` snapshot built for `entry_unloaded`/`site_unavailable`; never dedupe on an empty revision.
- Rendering: Lit bindings only. No `innerHTML`, no `unsafeHTML`, no `unsafeSVG`, no inline handler strings.
- Colours: HA CSS variables only (`--primary-text-color`, `--secondary-text-color`, `--card-background-color`, `--divider-color`, `--primary-color`, `--success-color`, `--warning-color`, `--error-color`, `--disabled-text-color`). A hex value may appear only as the `var(--x, <HA default>)` fallback.
- Tap targets ≥ 44 × 44 px. Focus ring 2 px `--primary-color` on `:focus-visible`, never suppressed.
- Frontend coverage ≥ 90 % lines on `frontend/src/`. Python coverage stays ≥ 90 % and ruff has zero new findings vs `upstream/main`.
- Commit messages: Conventional Commits, body explains *why*, trailer `Co-Authored-By: Claude <noreply@anthropic.com>`. Do not push or open a PR — Justin posts PRs (the body is drafted locally in Task 12).

### Spec amendments (found while planning; Task 0 writes them into the spec)

- **A1** `manifest.json` gets `"after_dependencies": ["http", "frontend"]`, **not** `dependencies`. Declaring `frontend` as a dependency makes every config-entry test set up `frontend`, which imports `hass_frontend` — not installed in the test venv or CI. `frontend.py` skips registration unless both `http` and `frontend` are in `hass.config.components`.
- **A2** Toolbar controls are native `<button>`/`<select>` styled with HA variables, not `ha-button`/`ha-icon-button`/`ha-select` (those are lazy-loaded and not guaranteed to be defined inside a custom card). `ha-card` stays. The editor still uses `ha-form` after `ensureHaForm()`.
- **A3** Test environment is jsdom (axe-core needs it), not happy-dom. `test/setup.ts` stubs `ResizeObserver` and `matchMedia`.
- **A4** Notice severity always comes from the payload (`legacy_uplink_missing` is `warning`, `clients_truncated` is `info`). `devices_unavailable` text is "Device data unavailable; showing last known layout." (the contract keeps last-known nodes for that issue).
- **A5** Subscription dedupe skips `revision === ""`.
- **A6** An expanded client group keeps its group node (collapsible header); its clients render as the group's children.
- **A7** Clients whose every ancestor is filtered out go into one root-level group `group:root` ("Clients"); clients with no parent at all go into `group:unconnected` ("Unconnected clients"), always the last root.
- **A8** On `entry_unloaded` the card calls its now-dead unsubscribe function (errors swallowed) so home-assistant-js-websocket does not resubscribe it after a socket reconnect, then retries with backoff.
- **A9** Panel detection uses the `layout` property `hui-card` sets on cards (`layout === "panel"`). "Edit card" navigates to `<current path>?edit=1`.
- **A10** TypeScript is pinned to 6.0.3 (typescript-eslint 8.70.1 supports `<6.1`).
- **A11** JSON imports widen string literals, so the TS side validates the shared fixture field-by-field at runtime against specs tied to the TS interfaces with `satisfies Record<keyof X, FieldSpec>` (unknown or missing fields fail), rather than a compile-time type-check.
- **A12** No explicit `requestAnimationFrame` coalescing: Lit already batches every property change within a task into one render, and snapshots arrive at most every few seconds. Pan/zoom never re-renders (the viewport transform is written directly); culling recomputes on zoom end.
- **A13** Escape clears the selection, which closes the detail panel in one step (the panel is bound to the selection).

## Review Focus

1. **Two unavailable snapshots in a row** (`site_unavailable` then `entry_unloaded`, both `revision: ""`) — the second must reach the card and trigger the reconnect path. Test: Task 4 `delivers consecutive unavailable snapshots with empty revisions`.
2. **Node names containing markup, very long names** (`<img src=x onerror=alert(1)>`, 80-character hostnames) — rendered as inert text, truncated with an ellipsis, full name kept in `title`/`aria-label`. Tests: Task 6 `renders hostile and long names as text` (list), Task 7 `renders hostile names as text` (graph).
3. **Card config pointing at a site that no longer exists** (entry deleted, site disabled) — card shows the "no longer exists" error with *Edit card*; the editor shows the stale site as "(unavailable)" and editing other fields keeps the ids. Tests: Task 8 `shows site_not_selected with an edit action`, Task 9 `keeps a stale site binding selectable`.
4. **Card removed and re-added before the subscribe promise resolves** (dashboard edit mode re-renders cards) — exactly one live subscription, the orphaned one unsubscribed. Tests: Task 4 `unsubscribes a subscription that resolves after stop`, Task 8 `resubscribes after being re-attached`.
5. **Malformed graph data** — edges to unknown ids, a device whose parent is a client, duplicate edges for one child, self-edges, parent cycles, no devices at all — no crash; affected nodes become roots or land in `group:unconnected`. Tests: Task 5 `ignores edges it cannot place`, `cuts parent cycles`, `puts clients without devices in the unconnected group`.

---

### Task 0: Worktree, spec amendments, HA API compatibility proof

**Files:**
- Create worktree `~/ha-unifi-insights-card` (branch `feat/topology-card`)
- Modify (design branch): `~/ha-unifi-insights-topology/docs/superpowers/specs/2026-09-24-topology-card-design.md` (§7 table + Amendments section)

**Interfaces:**
- Consumes: nothing.
- Produces: the worktree every later task uses; §7 compatibility table the PR body cites.

- [ ] **Step 1: Create the implementation worktree**

```bash
git -C ~/ha-unifi-insights fetch upstream
git -C ~/ha-unifi-insights worktree add ~/ha-unifi-insights-card -b feat/topology-card upstream/main
git -C ~/ha-unifi-insights-card log --oneline -1
```
Expected: a new worktree whose HEAD is the current `upstream/main` commit.

- [ ] **Step 2: Find the frontend version bundled with HA 2026.6.0**

```bash
gh api 'repos/home-assistant/core/contents/homeassistant/components/frontend/manifest.json?ref=2026.6.0' --jq .content | base64 -d | grep home-assistant-frontend
```
Expected: a line like `"requirements": ["home-assistant-frontend==2026060X.0"]`. Record the version as `FE`.

- [ ] **Step 3: Check every frontend API the card uses at that tag**

```bash
FE=<version from step 2>
check() { gh api "repos/home-assistant/frontend/contents/$1?ref=$FE" --jq .content | base64 -d | grep -c -- "$2"; }
check src/panels/lovelace/types.ts 'getGridOptions'
check src/panels/lovelace/custom-card-helpers.ts 'loadCardHelpers'
check src/panels/lovelace/cards/hui-card.ts 'isPanel'
check src/panels/lovelace/cards/hui-card.ts '_element.layout = this.layout'
check src/panels/lovelace/hui-root.ts 'searchParams.edit === "1"'
check src/components/ha-form/ha-form.ts 'grid'
check src/components/ha-selector/ha-selector-select.ts 'multiple'
check src/components/ha-selector/ha-selector-number.ts 'mode'
```
Expected: every count ≥ 1. If a path 404s, locate the file with `gh api -X GET search/code -f q='<symbol> repo:home-assistant/frontend'` and re-check at `$FE`. If any API is genuinely missing at `$FE`, STOP and report to Justin — the spec requires a feature-detected fallback for it.

- [ ] **Step 4: Write the proof and the amendments into the spec**

In the spec, replace the §7 sentence beginning "Implementation Task 0 records…" with a table `| API | File checked at frontend <FE> (HA 2026.6.0) | Present |` filled from Step 3, plus the two backend rows already verified (`StaticPathConfig`/`async_register_static_paths`, `add_extra_js_url`). Append a new section `## 11. Amendments (planning, 2026-09-24)` containing A1–A13 exactly as listed in this plan's Global Constraints. Also fix §5's message table: `legacy_uplink_missing` severity → warning, `devices_unavailable` text → "Device data unavailable; showing last known layout."

- [ ] **Step 5: Commit on the design branch**

```bash
cd ~/ha-unifi-insights-topology
git add docs/superpowers/specs/2026-09-24-topology-card-design.md
git commit -m "docs(spec): topology card HA API proof + planning amendments

Records the frontend APIs verified at the HA 2026.6.0 minimum and the
eleven amendments found while writing the implementation plan (notably
after_dependencies instead of dependencies, so tests without
hass_frontend keep passing).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 1: Serve the card bundle from the integration (Python)

**Files:**
- Create: `custom_components/unifi_insights/frontend.py`
- Modify: `custom_components/unifi_insights/__init__.py` (import + one call in `async_setup`)
- Modify: `custom_components/unifi_insights/manifest.json` (add `after_dependencies`)
- Test: `tests/test_frontend.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `frontend.CARD_URL = "/unifi_insights/topology-card.js"`, `frontend.CARD_PATH` (Path to the bundle), `async async_register_frontend(hass) -> None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_frontend.py`:
```python
"""Tests for serving the topology card bundle."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.unifi_insights import async_setup, frontend
from custom_components.unifi_insights.frontend import (
    CARD_PATH,
    CARD_URL,
    async_register_frontend,
)

MANIFEST = Path(frontend.__file__).parent / "manifest.json"


@pytest.fixture
def http(hass):
    """Pretend http and frontend are loaded, with a mock HTTP server."""
    mock = MagicMock()
    mock.async_register_static_paths = AsyncMock()
    hass.http = mock
    hass.config.components.update({"http", "frontend"})
    return mock


async def test_registers_bundle_once(hass, http) -> None:
    """The static path and the module URL are registered exactly once."""
    version = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]
    with patch.object(frontend, "add_extra_js_url") as add_js:
        await async_register_frontend(hass)
        await async_register_frontend(hass)

    http.async_register_static_paths.assert_awaited_once()
    (configs,) = http.async_register_static_paths.await_args.args
    assert [(c.url_path, c.path, c.cache_headers) for c in configs] == [
        (CARD_URL, str(CARD_PATH), True)
    ]
    add_js.assert_called_once_with(hass, f"{CARD_URL}?v={version}")


@pytest.mark.parametrize("missing", ["http", "frontend"])
async def test_skips_when_a_web_component_is_not_loaded(hass, missing) -> None:
    """Headless setups (and the test harness) get no card, and no error."""
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    hass.config.components.update({"http", "frontend"} - {missing})
    with patch.object(frontend, "add_extra_js_url") as add_js:
        await async_register_frontend(hass)

    hass.http.async_register_static_paths.assert_not_awaited()
    add_js.assert_not_called()


async def test_async_setup_registers_the_card(hass) -> None:
    """Component setup registers the card alongside the WebSocket commands."""
    with (
        patch("custom_components.unifi_insights.async_setup_services"),
        patch("custom_components.unifi_insights.async_load_node_keys"),
        patch("custom_components.unifi_insights.async_register_websocket_commands"),
        patch(
            "custom_components.unifi_insights.async_register_frontend"
        ) as register,
    ):
        assert await async_setup(hass, {})

    register.assert_awaited_once_with(hass)


def test_manifest_loads_after_web_components() -> None:
    """http/frontend are ordering hints, not hard dependencies (no hass_frontend in tests)."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert set(manifest["after_dependencies"]) >= {"http", "frontend"}
    assert "frontend" not in manifest["dependencies"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/ha-unifi-insights-card && $VENV/pytest tests/test_frontend.py -q --no-cov`
Expected: FAIL — `ImportError: cannot import name 'frontend'`.

- [ ] **Step 3: Implement `frontend.py`**

`custom_components/unifi_insights/frontend.py`:
```python
"""Serve the topology Lovelace card bundle from the integration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Final

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.loader import async_get_integration
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

CARD_URL: Final = f"/{DOMAIN}/topology-card.js"
CARD_PATH: Final = Path(__file__).parent / "frontend" / "topology-card.js"
_REGISTERED: HassKey[bool] = HassKey(f"{DOMAIN}_frontend_registered")


async def async_register_frontend(hass: HomeAssistant) -> None:
    """
    Serve the card bundle and load it on every dashboard, once per instance.

    Called from async_setup, like the topology WebSocket commands, so it runs
    once per Home Assistant instance rather than once per config entry. The
    URL carries the integration version so each release busts browser caches.
    http and frontend are after_dependencies, not dependencies: a setup
    without them (a headless install, or the test harness, which has no
    hass_frontend package) simply gets no card. Static paths cannot be
    unregistered, so nothing is undone on unload; the card shows its own
    "no integration loaded" state instead.
    """
    if hass.data.get(_REGISTERED):
        return
    if not {"http", "frontend"} <= hass.config.components:
        _LOGGER.debug("http/frontend not loaded; topology card not registered")
        return
    hass.data[_REGISTERED] = True
    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_PATH), cache_headers=True)]
    )
    add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")
```

- [ ] **Step 4: Wire it into `async_setup` and the manifest**

In `custom_components/unifi_insights/__init__.py`, add next to the existing `from .websocket_api import async_register_websocket_commands` import:
```python
from .frontend import async_register_frontend
```
and in `async_setup`, directly after `async_register_websocket_commands(hass)`:
```python
    # The card bundle is served the same way: once per instance.
    await async_register_frontend(hass)
```
In `manifest.json`, add directly after the `"name"` line (hassfest requires `domain`, `name`, then keys in alphabetical order, so `after_dependencies` comes before `bluetooth`):
```json
  "after_dependencies": ["http", "frontend"],
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `$VENV/pytest tests/test_frontend.py -q --no-cov`
Expected: 5 passed. If `test_registers_bundle_once` fails on `async_get_integration` (custom integration not discoverable), add the `enable_custom_integrations` fixture from `tests/conftest.py` as a parameter to that test and re-run.

- [ ] **Step 6: Run the whole Python suite and linters**

```bash
$VENV/pytest -q
$VENV/mypy custom_components/unifi_insights
$VENV/ruff check custom_components tests && $VENV/ruff format --check custom_components tests
```
Expected: all tests pass (existing config-entry tests are unaffected because `frontend` is not loaded in the harness), coverage ≥ 90 %, mypy 0 errors, ruff clean on the changed files. If `ruff format --check` flags unrelated upstream files, format only the files this task touched.

- [ ] **Step 7: Commit**

```bash
git add custom_components/unifi_insights/frontend.py custom_components/unifi_insights/__init__.py custom_components/unifi_insights/manifest.json tests/test_frontend.py
git commit -m "feat(frontend): serve topology card bundle from the integration

The #166 card ships inside the integration so the card and the #165
contract always move together. async_setup serves the bundle as a
static path and registers it with add_extra_js_url, versioned with the
manifest version to bust browser caches. http/frontend are
after_dependencies so installs and tests without hass_frontend keep
working.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Frontend toolchain, CI job and placeholder bundle

**Files:**
- Create: `frontend/.nvmrc`, `frontend/package.json`, `frontend/package-lock.json` (generated), `frontend/tsconfig.json`, `frontend/vite.config.ts`, `frontend/eslint.config.js`, `frontend/scripts/check-size.mjs`, `frontend/src/index.ts`, `frontend/test/setup.ts`, `frontend/test/smoke.test.ts`
- Create (generated): `custom_components/unifi_insights/frontend/topology-card.js`
- Modify: `.github/workflows/test.yml`, `.github/dependabot.yml`, `.gitignore`, `AGENTS.md`
- Test: `tests/test_frontend.py` (one new test)

**Interfaces:**
- Consumes: Task 1's `CARD_PATH`.
- Produces: `npm run lint | typecheck | test | build | size` in `frontend/`; the CI `frontend` job.

- [ ] **Step 1: Write the failing Python test for the shipped bundle**

Append to `tests/test_frontend.py`:
```python
def test_bundle_is_shipped() -> None:
    """HACS installs the repository tree, so the built bundle must be committed."""
    assert CARD_PATH.is_file()
```
Run: `$VENV/pytest tests/test_frontend.py::test_bundle_is_shipped -q --no-cov` → FAIL (file missing).

- [ ] **Step 2: Create the toolchain files**

`frontend/.nvmrc`:
```
22
```

`frontend/package.json`:
```json
{
  "name": "unifi-insights-topology-card",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "description": "Network topology Lovelace card for the UniFi Insights integration (built into custom_components/unifi_insights/frontend/).",
  "scripts": {
    "build": "vite build",
    "typecheck": "tsc --noEmit",
    "lint": "eslint .",
    "test": "vitest run",
    "size": "node scripts/check-size.mjs"
  },
  "dependencies": {
    "@mdi/js": "7.4.47",
    "d3-hierarchy": "3.1.2",
    "d3-selection": "3.0.0",
    "d3-transition": "3.0.1",
    "d3-zoom": "3.0.0",
    "lit": "3.3.3"
  },
  "devDependencies": {
    "@types/d3-hierarchy": "3.1.7",
    "@types/d3-selection": "3.0.12",
    "@types/d3-transition": "3.0.9",
    "@types/d3-zoom": "3.0.8",
    "@vitest/coverage-v8": "5.0.1",
    "axe-core": "4.13.0",
    "eslint": "10.11.0",
    "jsdom": "30.1.1",
    "typescript": "6.0.3",
    "typescript-eslint": "8.70.1",
    "vite": "8.3.1",
    "vitest": "5.0.1"
  }
}
```

`frontend/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "lib": ["ES2023", "DOM", "DOM.Iterable"],
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noImplicitOverride": true,
    "noFallthroughCasesInSwitch": true,
    "useDefineForClassFields": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "skipLibCheck": true,
    "noEmit": true
  },
  "include": ["src", "test", "vite.config.ts"]
}
```

`frontend/vite.config.ts`:
```ts
import { defineConfig } from 'vitest/config';

// One self-contained ES module, written straight into the integration so
// HACS ships it. CI rebuilds and fails if the committed file differs.
export default defineConfig({
  build: {
    lib: { entry: 'src/index.ts', formats: ['es'], fileName: () => 'topology-card.js' },
    outDir: '../custom_components/unifi_insights/frontend',
    emptyOutDir: false,
    target: 'es2022',
    minify: true,
    sourcemap: false,
    reportCompressedSize: false,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['test/setup.ts'],
    include: ['test/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      include: ['src/**/*.ts'],
      exclude: ['src/index.ts'],
      thresholds: { lines: 90 },
      reporter: ['text-summary'],
    },
  },
});
```

`frontend/eslint.config.js`:
```js
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['node_modules/**', 'coverage/**'] },
  ...tseslint.configs.strict,
  {
    rules: {
      // Map lookups right after a has()/set() are clearer with `!` than with dead branches.
      '@typescript-eslint/no-non-null-assertion': 'off',
    },
  },
);
```

`frontend/scripts/check-size.mjs`:
```js
import { statSync } from 'node:fs';

const BUDGET = 150 * 1024;
const bundle = new URL('../../custom_components/unifi_insights/frontend/topology-card.js', import.meta.url);
const size = statSync(bundle).size;
console.log(`topology-card.js: ${(size / 1024).toFixed(1)} KB (budget ${BUDGET / 1024} KB)`);
if (size > BUDGET) {
  console.error('Bundle exceeds its size budget.');
  process.exit(1);
}
```

`frontend/src/index.ts` (placeholder, replaced in Task 8):
```ts
// Entry point for the topology card bundle. Task 8 registers the card here.
export {};
```

`frontend/test/setup.ts`:
```ts
// jsdom lacks these browser APIs; the card only needs them to exist.
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;

if (!window.matchMedia) {
  window.matchMedia = (query: string): MediaQueryList =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    }) as MediaQueryList;
}
```

`frontend/test/smoke.test.ts`:
```ts
import { expect, it } from 'vitest';

it('runs in a DOM environment with the browser stubs', () => {
  expect(typeof document.createElement).toBe('function');
  expect(typeof ResizeObserver).toBe('function');
  expect(window.matchMedia('(prefers-reduced-motion: reduce)').matches).toBe(false);
});
```

- [ ] **Step 3: Install and run every script**

```bash
cd ~/ha-unifi-insights-card/frontend
npm install
npm run lint && npm run typecheck && npm test && npm run build && npm run size
```
Expected: `package-lock.json` created; lint/typecheck clean; 1 test passed; build writes `../custom_components/unifi_insights/frontend/topology-card.js`; size prints well under budget.

- [ ] **Step 4: Prove the build is reproducible**

```bash
sha256sum ../custom_components/unifi_insights/frontend/topology-card.js
rm -rf node_modules && npm ci && npm run build
sha256sum ../custom_components/unifi_insights/frontend/topology-card.js
```
Expected: identical hashes. If not, stop and investigate (the CI diff check depends on it).

- [ ] **Step 5: Ignore frontend artefacts**

Append to `.gitignore`:
```
# ============================================================================
# Frontend (topology card)
# ============================================================================
frontend/node_modules/
frontend/coverage/
```
Run `git status --short frontend` → only source files, `package-lock.json` and `.nvmrc` listed (no `node_modules`).

- [ ] **Step 6: Add the CI job**

Append to `.github/workflows/test.yml` under `jobs:` (same indentation as `test:`):
```yaml
  frontend:
    name: Frontend lint, test & build
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - name: Checkout repository
        uses: actions/checkout@v7

      - name: Set up Node
        uses: actions/setup-node@v7
        with:
          node-version-file: frontend/.nvmrc
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - name: Install dependencies
        run: npm ci

      - name: Lint
        run: npm run lint

      - name: Type-check
        run: npm run typecheck

      - name: Test with coverage
        run: npm test -- --coverage

      - name: Build bundle
        run: npm run build

      - name: Bundle size budget
        run: npm run size

      - name: Committed bundle matches source
        run: git diff --exit-code -- ../custom_components/unifi_insights/frontend/
```

Append to `.github/dependabot.yml` under `updates:` (match the existing entries' indentation and schedule):
```yaml
  - package-ecosystem: npm
    directory: /frontend
    schedule:
      interval: weekly
```

- [ ] **Step 7: Document the commands for contributors and agents**

In `AGENTS.md`, in the `## Validation and Testing` code block that lists `pre-commit run --all-files` / `script/lint` / `pytest`, append:
```
cd frontend && npm ci          # Topology card: install (Node 22)
npm run lint && npm run typecheck && npm test -- --coverage
npm run build                  # Rebuild custom_components/unifi_insights/frontend/topology-card.js — commit it
```

- [ ] **Step 8: Run the Python test and commit**

Run: `$VENV/pytest tests/test_frontend.py -q --no-cov` → 6 passed.
```bash
cd ~/ha-unifi-insights-card
git add frontend .gitignore .github/workflows/test.yml .github/dependabot.yml AGENTS.md custom_components/unifi_insights/frontend/topology-card.js tests/test_frontend.py
git commit -m "build(frontend): TypeScript/Lit/Vite toolchain and CI job

Typed source, lint and tests in CI are #166 requirements. The bundle is
committed because HACS installs the repository tree; the new CI job
rebuilds it and fails when the committed file differs, and enforces a
150 KB budget. Node tooling stays out of pre-commit so Python-only
contributors are unaffected.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---
### Task 3: Contract types, HA types, config, localization, shared fixture

**Files:**
- Create: `frontend/src/contract.ts`, `frontend/src/ha-types.ts`, `frontend/src/config.ts`, `frontend/src/localize.ts`, `frontend/src/define.ts`
- Create (generated by Python): `frontend/test/fixtures/site-topology.json`
- Create: `frontend/test/helpers.ts`, `frontend/test/contract.test.ts`, `frontend/test/config.test.ts`, `frontend/test/localize.test.ts`
- Modify: `tests/test_topology.py` (fixture test + two imports)

**Interfaces:**
- Consumes: Python `build_site_topology` via the existing `_live_layout`, `_with_links`, `_build` helpers in `tests/test_topology.py`.
- Produces (TS, exact names used by later tasks):
  - `contract.ts`: `SCHEMA_VERSION`, `MAX_CLIENTS_PER_SITE`, `NODE_KINDS`, `NODE_STATES`, `LINK_MEDIA`, `CLIENT_CONNECTIONS`, `TOPOLOGY_STATUSES`, `ISSUE_SEVERITIES`, `UNRESOLVED_REASONS`, types `NodeKind NodeState LinkMedium ClientConnection TopologyStatus IssueSeverity UnresolvedReason TopologyNode TopologyEdge TopologyIssue TopologyUnresolved TopologyTruncation SiteTopology TopologySite TopologySource`, `WS_SOURCES`, `WS_SUBSCRIBE`, `ISSUE_ENTRY_UNLOADED ISSUE_SITE_UNAVAILABLE ISSUE_DEVICES_UNAVAILABLE ISSUE_LEGACY_UPLINK_MISSING ISSUE_PARENTS_UNRESOLVED ISSUE_CLIENTS_TRUNCATED`, `ERR_ENTRY_NOT_FOUND ERR_ENTRY_NOT_LOADED ERR_SITE_NOT_SELECTED`, `class IncompatibleSchemaError`, `parseSnapshot(raw: unknown): SiteTopology`.
  - `ha-types.ts`: `MessageBase`, `UnsubscribeFunc`, `Connection`, `HomeAssistant`, `WsError`, `isWsError`, `toWsError`, `fireEvent(node, type, detail?)`, `navigate(path)`, `CardHelpers`, global `Window.customCards` / `Window.loadCardHelpers`.
  - `config.ts`: `CARD_TAG`, `EDITOR_TAG`, `CARD_TYPE`, `VIEWS`, `CLIENT_MODES`, `DENSITIES`, `ORIENTATIONS`, types `ViewMode ClientsMode Density Orientation TopologyCardConfig ResolvedConfig SiteBinding SiteOption`, `validateConfig(raw): TopologyCardConfig`, `resolveConfig(c): ResolvedConfig`, `allSites(sources): SiteOption[]`, `resolveBinding(config, sources): SiteBinding | undefined`, `sameBinding(a?, b?): boolean`.
  - `localize.ts`: `LocalizeKey`, `LocalizeVars`, `LocalizeFunc`, `makeLocalize(language?): LocalizeFunc`.
  - `define.ts`: `defineOnce(tag, ctor)`.
  - `test/helpers.ts`: `fixtureSnapshot(overrides?)`, `unavailableSnapshot(code)`, `SOURCES_ONE`, `SOURCES_MULTI`.

- [ ] **Step 1: Write the Python fixture test (failing — file missing)**

In `tests/test_topology.py` add to the imports:
```python
import os
from pathlib import Path
```
and append:
```python
FRONTEND_FIXTURE = (
    Path(__file__).parent.parent / "frontend" / "test" / "fixtures" / "site-topology.json"
)


def test_frontend_contract_fixture_is_current() -> None:
    """
    The card's contract fixture is exactly what the builder emits today.

    frontend/test/fixtures/site-topology.json is validated field by field and
    rendered by the card's test suite, so a contract change fails here until
    the fixture is regenerated, and then fails the TypeScript tests until the
    card is updated. Regenerate with:
    UPDATE_TOPOLOGY_FIXTURE=1 pytest tests/test_topology.py -k fixture
    """
    data = _with_links(
        _live_layout(),
        {
            "12:00:00:00:00:01": {
                "sw_mac": "02:00:00:00:00:03",
                "sw_port": 4,
                "vlan": 3,
                "network_name": "Media",
            },
            "12:00:00:00:00:02": {
                "ap_mac": "02:00:00:00:00:08",
                "network_name": "Default",
            },
        },
    )
    snapshot = _build(data, ha_device_ids={"uuid-gw": "reg-gw", "uuid-core": "reg-core"})
    rendered = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_TOPOLOGY_FIXTURE"):
        FRONTEND_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FRONTEND_FIXTURE.write_text(rendered, encoding="utf-8")
    assert FRONTEND_FIXTURE.read_text(encoding="utf-8") == rendered
```
Run: `$VENV/pytest tests/test_topology.py -k fixture -q --no-cov` → FAIL (`FileNotFoundError`).

- [ ] **Step 2: Generate the fixture and verify it**

```bash
UPDATE_TOPOLOGY_FIXTURE=1 $VENV/pytest tests/test_topology.py -k fixture -q --no-cov
$VENV/pytest tests/test_topology.py -k fixture -q --no-cov
python3 -c "import json;d=json.load(open('frontend/test/fixtures/site-topology.json'));print(d['status'],len(d['nodes']),len(d['edges']),d['site_name'])"
```
Expected: both runs pass; prints `ok 10 9 Home` (8 devices + 2 clients, 7 device edges + 2 client edges). Also `grep -Ec '([0-9a-f]{2}:){5}' frontend/test/fixtures/site-topology.json` → `0` (no MACs).

- [ ] **Step 3: Write the failing TS tests**

`frontend/test/helpers.ts`:
```ts
import fixture from './fixtures/site-topology.json';
import type { SiteTopology, TopologySource } from '../src/contract';

/** A fresh deep copy of the Python-generated snapshot, with optional overrides. */
export function fixtureSnapshot(overrides: Partial<SiteTopology> = {}): SiteTopology {
  const copy = JSON.parse(JSON.stringify(fixture)) as SiteTopology;
  return { ...copy, ...overrides };
}

/** What the backend pushes for entry_unloaded / site_unavailable. */
export function unavailableSnapshot(code: string): SiteTopology {
  return fixtureSnapshot({
    revision: '',
    status: 'unavailable',
    issues: [{ code, severity: 'error' }],
    nodes: [],
    edges: [],
    unresolved: [],
    truncation: null,
  });
}

export const SOURCES_ONE: TopologySource[] = [
  { entry_id: 'entry-1', title: 'Crestwood', sites: [{ id: 'site-1', name: 'Home' }] },
];

export const SOURCES_MULTI: TopologySource[] = [
  { entry_id: 'entry-1', title: 'Crestwood', sites: [{ id: 'site-1', name: 'Home' }, { id: 'site-2', name: 'Cabin' }] },
  { entry_id: 'entry-2', title: 'Office', sites: [{ id: 'default', name: 'Default' }] },
];
```

`frontend/test/contract.test.ts`:
```ts
import { describe, expect, it } from 'vitest';
import fixture from './fixtures/site-topology.json';
import {
  CLIENT_CONNECTIONS, ISSUE_SEVERITIES, IncompatibleSchemaError, LINK_MEDIA, NODE_KINDS, NODE_STATES,
  SCHEMA_VERSION, TOPOLOGY_STATUSES, UNRESOLVED_REASONS, parseSnapshot,
  type SiteTopology, type TopologyEdge, type TopologyIssue, type TopologyNode, type TopologyTruncation,
  type TopologyUnresolved,
} from '../src/contract';

type FieldSpec =
  | { kind: 'string' | 'number'; optional?: true }
  | { kind: 'enum'; values: readonly string[]; optional?: true };

// `satisfies Record<keyof X, FieldSpec>` makes TypeScript reject a spec that
// misses or invents a field, so these specs cannot drift from contract.ts.
const NODE_SPEC = {
  id: { kind: 'string' },
  kind: { kind: 'enum', values: NODE_KINDS },
  name: { kind: 'string' },
  state: { kind: 'enum', values: NODE_STATES },
  model: { kind: 'string', optional: true },
  ha_device_id: { kind: 'string', optional: true },
  connection: { kind: 'enum', values: CLIENT_CONNECTIONS, optional: true },
  vlan_id: { kind: 'number', optional: true },
  network_name: { kind: 'string', optional: true },
} satisfies Record<keyof TopologyNode, FieldSpec>;

const EDGE_SPEC = {
  source: { kind: 'string' },
  target: { kind: 'string' },
  medium: { kind: 'enum', values: LINK_MEDIA },
  speed_mbps: { kind: 'number', optional: true },
  parent_port: { kind: 'number', optional: true },
  child_port: { kind: 'number', optional: true },
  poe_power_w: { kind: 'number', optional: true },
} satisfies Record<keyof TopologyEdge, FieldSpec>;

const ISSUE_SPEC = {
  code: { kind: 'string' },
  severity: { kind: 'enum', values: ISSUE_SEVERITIES },
} satisfies Record<keyof TopologyIssue, FieldSpec>;

const UNRESOLVED_SPEC = {
  node_id: { kind: 'string' },
  reason: { kind: 'enum', values: UNRESOLVED_REASONS },
} satisfies Record<keyof TopologyUnresolved, FieldSpec>;

const TRUNCATION_SPEC = {
  clients_total: { kind: 'number' },
  clients_included: { kind: 'number' },
} satisfies Record<keyof TopologyTruncation, FieldSpec>;

const LIST_FIELDS = ['nodes', 'edges', 'issues', 'unresolved', 'truncation'] as const;
const SNAPSHOT_SPEC = {
  schema_version: { kind: 'number' },
  entry_id: { kind: 'string' },
  site_id: { kind: 'string' },
  site_name: { kind: 'string' },
  revision: { kind: 'string' },
  status: { kind: 'enum', values: TOPOLOGY_STATUSES },
} satisfies Record<Exclude<keyof SiteTopology, (typeof LIST_FIELDS)[number]>, FieldSpec>;

function checkObject(value: unknown, spec: Record<string, FieldSpec>, where: string, extra: readonly string[] = []): void {
  expect(typeof value, where).toBe('object');
  const record = value as Record<string, unknown>;
  for (const key of Object.keys(record)) {
    expect([...Object.keys(spec), ...extra], `${where}: unexpected field "${key}"`).toContain(key);
  }
  for (const [key, field] of Object.entries(spec)) {
    const v = record[key];
    if (v === undefined) {
      expect(field.optional, `${where}: missing "${key}"`).toBe(true);
    } else if (field.kind === 'enum') {
      expect(field.values, `${where}.${key}`).toContain(v);
    } else {
      expect(typeof v, `${where}.${key}`).toBe(field.kind);
    }
  }
}

function checkSnapshot(raw: unknown): void {
  checkObject(raw, SNAPSHOT_SPEC, 'snapshot', LIST_FIELDS);
  const s = raw as SiteTopology;
  s.nodes.forEach((n, i) => checkObject(n, NODE_SPEC, `nodes[${i}]`));
  s.edges.forEach((e, i) => checkObject(e, EDGE_SPEC, `edges[${i}]`));
  s.issues.forEach((x, i) => checkObject(x, ISSUE_SPEC, `issues[${i}]`));
  s.unresolved.forEach((u, i) => checkObject(u, UNRESOLVED_SPEC, `unresolved[${i}]`));
  if (s.truncation !== null) checkObject(s.truncation, TRUNCATION_SPEC, 'truncation');
}

describe('shared contract fixture (generated by tests/test_topology.py)', () => {
  it('matches contract.ts field for field', () => {
    checkSnapshot(fixture);
  });

  it('parses unchanged and references only known nodes', () => {
    const snapshot = parseSnapshot(fixture);
    expect(snapshot.schema_version).toBe(SCHEMA_VERSION);
    const ids = new Set(snapshot.nodes.map((n) => n.id));
    for (const edge of snapshot.edges) {
      expect(ids.has(edge.source) && ids.has(edge.target)).toBe(true);
    }
    // source is the CHILD: the core switch hangs off the gateway.
    expect(snapshot.edges).toContainEqual(expect.objectContaining({ source: 'dev:uuid-core', target: 'dev:uuid-gw' }));
  });

  it('rejects a field the contract does not define', () => {
    const tampered = JSON.parse(JSON.stringify(fixture)) as { nodes: Record<string, unknown>[] };
    tampered.nodes[0]!.mac = 'aa:bb:cc:dd:ee:ff';
    expect(() => checkSnapshot(tampered)).toThrow(/unexpected field "mac"/);
  });
});

describe('parseSnapshot', () => {
  it('rejects another schema version as incompatible', () => {
    expect(() => parseSnapshot({ ...fixture, schema_version: 2 })).toThrow(IncompatibleSchemaError);
  });

  it.each([null, [], 'x', { ...fixture, nodes: 'no' }, { ...fixture, revision: 5 }])(
    'rejects a malformed payload %#',
    (raw) => {
      expect(() => parseSnapshot(raw)).toThrow(TypeError);
    },
  );
});
```

`frontend/test/config.test.ts`:
```ts
import { describe, expect, it } from 'vitest';
import { NODE_KINDS } from '../src/contract';
import { allSites, resolveBinding, resolveConfig, sameBinding, validateConfig } from '../src/config';
import { SOURCES_MULTI, SOURCES_ONE } from './helpers';

const TYPE = 'custom:unifi-insights-topology-card';

describe('validateConfig', () => {
  it('accepts a full config and ignores keys HA adds', () => {
    const config = {
      type: TYPE, entry_id: 'e', site_id: 's', title: 'Net', view: 'list', show_site_selector: true,
      clients: 'hidden', kinds: ['gateway', 'switch'], density: 'compact', orientation: 'horizontal',
      show_labels: false, max_clients: 120, grid_options: { columns: 12 }, visibility: [],
    };
    expect(validateConfig(config)).toBe(config);
  });

  it.each([
    [null, /must be an object/],
    [{}, /type is required/],
    [{ type: TYPE, entry_id: 'e' }, /set together/],
    [{ type: TYPE, title: '' }, /title must be a non-empty string/],
    [{ type: TYPE, view: 'map' }, /view must be one of/],
    [{ type: TYPE, clients: 'all' }, /clients must be one of/],
    [{ type: TYPE, density: 'tiny' }, /density must be one of/],
    [{ type: TYPE, orientation: 'diagonal' }, /orientation must be one of/],
    [{ type: TYPE, kinds: [] }, /kinds must be a non-empty list/],
    [{ type: TYPE, kinds: ['router'] }, /kinds must be a non-empty list/],
    [{ type: TYPE, show_labels: 'yes' }, /show_labels must be true or false/],
    [{ type: TYPE, max_clients: 0 }, /max_clients must be a whole number from 1 to 500/],
    [{ type: TYPE, max_clients: 501 }, /max_clients/],
    [{ type: TYPE, max_clients: 1.5 }, /max_clients/],
  ])('rejects %j', (raw, message) => {
    expect(() => validateConfig(raw)).toThrow(message);
  });
});

describe('resolveConfig', () => {
  it('fills every default', () => {
    expect(resolveConfig({ type: TYPE })).toEqual({
      entry_id: undefined, site_id: undefined, title: undefined, view: 'graph', show_site_selector: false,
      clients: 'collapsed', kinds: [...NODE_KINDS], density: undefined, orientation: 'vertical',
      show_labels: true, max_clients: 500,
    });
  });
});

describe('site binding', () => {
  it('uses explicit ids even before sources load', () => {
    const config = resolveConfig({ type: TYPE, entry_id: 'e', site_id: 's' });
    expect(resolveBinding(config, undefined)).toEqual({ entry_id: 'e', site_id: 's' });
  });

  it('auto-picks the only site', () => {
    expect(resolveBinding(resolveConfig({ type: TYPE }), SOURCES_ONE)).toEqual({ entry_id: 'entry-1', site_id: 'site-1' });
  });

  it('does not guess between several sites', () => {
    expect(resolveBinding(resolveConfig({ type: TYPE }), SOURCES_MULTI)).toBeUndefined();
    expect(resolveBinding(resolveConfig({ type: TYPE }), undefined)).toBeUndefined();
  });

  it('labels every site with its entry title', () => {
    expect(allSites(SOURCES_MULTI).map((s) => s.label)).toEqual(['Crestwood — Home', 'Crestwood — Cabin', 'Office — Default']);
  });

  it('compares bindings by value', () => {
    expect(sameBinding({ entry_id: 'a', site_id: 'b' }, { entry_id: 'a', site_id: 'b' })).toBe(true);
    expect(sameBinding({ entry_id: 'a', site_id: 'b' }, { entry_id: 'a', site_id: 'c' })).toBe(false);
    expect(sameBinding(undefined, undefined)).toBe(true);
    expect(sameBinding({ entry_id: 'a', site_id: 'b' }, undefined)).toBe(false);
  });
});
```

`frontend/test/localize.test.ts`:
```ts
import { expect, it } from 'vitest';
import { makeLocalize } from '../src/localize';

it('interpolates variables', () => {
  expect(makeLocalize('en')('issue.clients_truncated', { included: 500, total: 612, max: 500 }))
    .toBe('Showing 500 of 612 clients (limit 500).');
});

it('falls back to English for languages without a table', () => {
  expect(makeLocalize('de-DE')('view.graph')).toBe('Graph');
  expect(makeLocalize(undefined)('view.list')).toBe('List');
});
```

Run: `cd frontend && npm test` → FAIL (modules `../src/contract`, `../src/config`, `../src/localize` not found).

- [ ] **Step 4: Implement `contract.ts`**

```ts
/**
 * Wire contract of the `unifi_insights/topology/*` WebSocket commands, schema 1.
 *
 * Mirrors custom_components/unifi_insights/topology_contract.py. This is the
 * only frontend module that knows the payload shape; everything else imports
 * these types. test/fixtures/site-topology.json is generated by the Python
 * builder (tests/test_topology.py) and validated against these interfaces in
 * test/contract.test.ts, so a contract change fails CI on both sides.
 */

export const SCHEMA_VERSION = 1;
/** Server-side hard cap on client nodes per site; `max_clients` may ask for fewer. */
export const MAX_CLIENTS_PER_SITE = 500;

export const NODE_KINDS = ['gateway', 'switch', 'access_point', 'client', 'other'] as const;
export type NodeKind = (typeof NODE_KINDS)[number];
export const NODE_STATES = ['online', 'offline', 'unknown'] as const;
export type NodeState = (typeof NODE_STATES)[number];
export const LINK_MEDIA = ['wired', 'wireless', 'unknown'] as const;
export type LinkMedium = (typeof LINK_MEDIA)[number];
export const CLIENT_CONNECTIONS = ['wired', 'wireless'] as const;
export type ClientConnection = (typeof CLIENT_CONNECTIONS)[number];
export const TOPOLOGY_STATUSES = ['ok', 'partial', 'unavailable'] as const;
export type TopologyStatus = (typeof TOPOLOGY_STATUSES)[number];
export const ISSUE_SEVERITIES = ['info', 'warning', 'error'] as const;
export type IssueSeverity = (typeof ISSUE_SEVERITIES)[number];
export const UNRESOLVED_REASONS = ['parent_not_found', 'no_uplink_data'] as const;
export type UnresolvedReason = (typeof UNRESOLVED_REASONS)[number];

/**
 * A device or client. `id` is opaque: `dev:`/`cli:` plus the v1 UUID, or an
 * HMAC for records keyed only by MAC. Names are never MACs.
 */
export interface TopologyNode {
  id: string;
  kind: NodeKind;
  name: string;
  state: NodeState;
  model?: string;
  /** Home Assistant device registry id; infrastructure nodes only. */
  ha_device_id?: string;
  /** Clients only. */
  connection?: ClientConnection;
  /** Clients on a VLAN-tagged network only. */
  vlan_id?: number;
  network_name?: string;
}

/** One uplink. NOTE: `source` is the CHILD, `target` is the PARENT. */
export interface TopologyEdge {
  source: string;
  target: string;
  medium: LinkMedium;
  speed_mbps?: number;
  /** Port on the parent the child is plugged into. */
  parent_port?: number;
  /** The child's own uplink port. */
  child_port?: number;
  /** PoE draw on the parent port (device edges only). */
  poe_power_w?: number;
}

export interface TopologyIssue {
  code: string;
  severity: IssueSeverity;
}

export interface TopologyUnresolved {
  node_id: string;
  reason: UnresolvedReason;
}

export interface TopologyTruncation {
  clients_total: number;
  clients_included: number;
}

/**
 * One site's snapshot, pushed whole by `subscribe` whenever `revision` changes.
 *
 * `status` is `unavailable` when any issue has severity `error`, `partial`
 * when any other issue is present, else `ok`. With `devices_unavailable` the
 * nodes/edges are the last-known data; with `entry_unloaded` or
 * `site_unavailable` they are empty and `revision` is "" - never dedupe on an
 * empty revision. After `entry_unloaded` the server has ended the subscription.
 */
export interface SiteTopology {
  schema_version: number;
  entry_id: string;
  site_id: string;
  site_name: string;
  /** Opaque change token (16 hex chars), or "" on unavailable snapshots. */
  revision: string;
  status: TopologyStatus;
  issues: TopologyIssue[];
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  unresolved: TopologyUnresolved[];
  truncation: TopologyTruncation | null;
}

export interface TopologySite {
  id: string;
  name: string;
}

/** One loaded config entry, as listed by `topology/sources`. */
export interface TopologySource {
  entry_id: string;
  title: string;
  sites: TopologySite[];
}

export const WS_SOURCES = 'unifi_insights/topology/sources';
export const WS_SUBSCRIBE = 'unifi_insights/topology/subscribe';

export const ISSUE_ENTRY_UNLOADED = 'entry_unloaded';
export const ISSUE_SITE_UNAVAILABLE = 'site_unavailable';
export const ISSUE_DEVICES_UNAVAILABLE = 'devices_unavailable';
export const ISSUE_LEGACY_UPLINK_MISSING = 'legacy_uplink_missing';
export const ISSUE_PARENTS_UNRESOLVED = 'parents_unresolved';
export const ISSUE_CLIENTS_TRUNCATED = 'clients_truncated';

export const ERR_ENTRY_NOT_FOUND = 'entry_not_found';
export const ERR_ENTRY_NOT_LOADED = 'entry_not_loaded';
export const ERR_SITE_NOT_SELECTED = 'site_not_selected';

/** The backend speaks a schema this card was not built for. */
export class IncompatibleSchemaError extends Error {
  readonly received: unknown;

  constructor(received: unknown) {
    super(`Unsupported topology schema_version ${String(received)}`);
    this.name = 'IncompatibleSchemaError';
    this.received = received;
  }
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

/**
 * Validate a pushed payload's envelope. Throws IncompatibleSchemaError for
 * another schema version and TypeError for a malformed payload.
 */
export function parseSnapshot(raw: unknown): SiteTopology {
  if (!isRecord(raw)) throw new TypeError('Topology snapshot is not an object');
  if (raw.schema_version !== SCHEMA_VERSION) throw new IncompatibleSchemaError(raw.schema_version);
  for (const key of ['nodes', 'edges', 'issues', 'unresolved'] as const) {
    if (!Array.isArray(raw[key])) throw new TypeError(`Topology snapshot field ${key} is not a list`);
  }
  for (const key of ['entry_id', 'site_id', 'site_name', 'revision', 'status'] as const) {
    if (typeof raw[key] !== 'string') throw new TypeError(`Topology snapshot field ${key} is not a string`);
  }
  return raw as unknown as SiteTopology;
}
```

- [ ] **Step 5: Implement `ha-types.ts` and `define.ts`**

`frontend/src/ha-types.ts`:
```ts
/**
 * The slice of Home Assistant's frontend API this card uses. Declared locally
 * because custom-card-helpers is unmaintained.
 */

export interface MessageBase {
  type: string;
  [key: string]: unknown;
}

export type UnsubscribeFunc = () => Promise<void>;

export interface Connection {
  subscribeMessage<T>(
    callback: (message: T) => void,
    message: MessageBase,
    options?: { resubscribe?: boolean },
  ): Promise<UnsubscribeFunc>;
}

export interface HomeAssistant {
  connection: Connection;
  callWS<T>(message: MessageBase): Promise<T>;
  language?: string;
  locale?: { language: string };
}

/** Rejection shape of home-assistant-js-websocket commands. */
export interface WsError {
  code: string;
  message: string;
}

export function isWsError(value: unknown): value is WsError {
  return typeof value === 'object' && value !== null && typeof (value as WsError).code === 'string';
}

export function toWsError(value: unknown): WsError {
  if (isWsError(value)) return { code: value.code, message: typeof value.message === 'string' ? value.message : '' };
  return { code: 'unknown_error', message: String(value) };
}

export function fireEvent(node: EventTarget, type: string, detail?: unknown): void {
  node.dispatchEvent(new CustomEvent(type, { detail, bubbles: true, composed: true }));
}

/** Navigate inside the HA frontend without a page load. */
export function navigate(path: string): void {
  history.pushState(null, '', path);
  fireEvent(window, 'location-changed', { replace: false });
}

export interface CardHelpers {
  createCardElement(config: { type: string; [key: string]: unknown }): HTMLElement;
}

declare global {
  interface Window {
    customCards?: { type: string; name: string; description: string; preview?: boolean; documentationURL?: string }[];
    loadCardHelpers?: () => Promise<CardHelpers>;
  }
}
```

`frontend/src/define.ts`:
```ts
/** Define a custom element unless something (an older bundle, a prototype) already did. */
export function defineOnce(tag: string, ctor: CustomElementConstructor): void {
  if (!customElements.get(tag)) customElements.define(tag, ctor);
}
```

- [ ] **Step 6: Implement `config.ts`**

```ts
import { MAX_CLIENTS_PER_SITE, NODE_KINDS, type NodeKind, type TopologySource } from './contract';

export const CARD_TAG = 'unifi-insights-topology-card';
export const EDITOR_TAG = 'unifi-insights-topology-card-editor';
export const CARD_TYPE = `custom:${CARD_TAG}`;

export const VIEWS = ['graph', 'list'] as const;
export type ViewMode = (typeof VIEWS)[number];
export const CLIENT_MODES = ['collapsed', 'expanded', 'hidden'] as const;
export type ClientsMode = (typeof CLIENT_MODES)[number];
export const DENSITIES = ['comfortable', 'compact'] as const;
export type Density = (typeof DENSITIES)[number];
export const ORIENTATIONS = ['vertical', 'horizontal'] as const;
export type Orientation = (typeof ORIENTATIONS)[number];

/** Card YAML. Every key but `type` is optional; unknown keys (grid_options, visibility, ...) are kept. */
export interface TopologyCardConfig {
  type: string;
  entry_id?: string;
  site_id?: string;
  title?: string;
  view?: ViewMode;
  show_site_selector?: boolean;
  clients?: ClientsMode;
  kinds?: NodeKind[];
  density?: Density;
  orientation?: Orientation;
  show_labels?: boolean;
  max_clients?: number;
  [key: string]: unknown;
}

export interface ResolvedConfig {
  entry_id: string | undefined;
  site_id: string | undefined;
  title: string | undefined;
  view: ViewMode;
  show_site_selector: boolean;
  clients: ClientsMode;
  kinds: NodeKind[];
  /** undefined = automatic (compact below 600 px card width). */
  density: Density | undefined;
  orientation: Orientation;
  show_labels: boolean;
  max_clients: number;
}

export interface SiteBinding {
  entry_id: string;
  site_id: string;
}

export interface SiteOption {
  binding: SiteBinding;
  label: string;
}

function checkOneOf(value: unknown, allowed: readonly string[], key: string): void {
  if (value !== undefined && !(typeof value === 'string' && allowed.includes(value))) {
    throw new Error(`${key} must be one of: ${allowed.join(', ')}`);
  }
}

/** Throw a readable Error for an invalid config; HA shows it as the standard error card. */
export function validateConfig(raw: unknown): TopologyCardConfig {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    throw new Error('Card configuration must be an object');
  }
  const c = raw as Record<string, unknown>;
  if (typeof c.type !== 'string') throw new Error('type is required');
  for (const key of ['entry_id', 'site_id', 'title'] as const) {
    const value = c[key];
    if (value !== undefined && (typeof value !== 'string' || value === '')) {
      throw new Error(`${key} must be a non-empty string`);
    }
  }
  if ((c.entry_id === undefined) !== (c.site_id === undefined)) {
    throw new Error('entry_id and site_id must be set together');
  }
  checkOneOf(c.view, VIEWS, 'view');
  checkOneOf(c.clients, CLIENT_MODES, 'clients');
  checkOneOf(c.density, DENSITIES, 'density');
  checkOneOf(c.orientation, ORIENTATIONS, 'orientation');
  for (const key of ['show_site_selector', 'show_labels'] as const) {
    if (c[key] !== undefined && typeof c[key] !== 'boolean') throw new Error(`${key} must be true or false`);
  }
  if (
    c.kinds !== undefined &&
    (!Array.isArray(c.kinds) ||
      c.kinds.length === 0 ||
      !c.kinds.every((k) => (NODE_KINDS as readonly unknown[]).includes(k)))
  ) {
    throw new Error(`kinds must be a non-empty list of: ${NODE_KINDS.join(', ')}`);
  }
  const max = c.max_clients;
  if (max !== undefined && (typeof max !== 'number' || !Number.isInteger(max) || max < 1 || max > MAX_CLIENTS_PER_SITE)) {
    throw new Error(`max_clients must be a whole number from 1 to ${MAX_CLIENTS_PER_SITE}`);
  }
  return c as TopologyCardConfig;
}

export function resolveConfig(c: TopologyCardConfig): ResolvedConfig {
  return {
    entry_id: c.entry_id,
    site_id: c.site_id,
    title: c.title,
    view: c.view ?? 'graph',
    show_site_selector: c.show_site_selector ?? false,
    clients: c.clients ?? 'collapsed',
    kinds: c.kinds ? [...c.kinds] : [...NODE_KINDS],
    density: c.density,
    orientation: c.orientation ?? 'vertical',
    show_labels: c.show_labels ?? true,
    max_clients: c.max_clients ?? MAX_CLIENTS_PER_SITE,
  };
}

export function allSites(sources: readonly TopologySource[]): SiteOption[] {
  return sources.flatMap((source) =>
    source.sites.map((site) => ({
      binding: { entry_id: source.entry_id, site_id: site.id },
      label: `${source.title} — ${site.name}`,
    })),
  );
}

/** The configured site, or the only site when exactly one exists. */
export function resolveBinding(config: ResolvedConfig, sources: readonly TopologySource[] | undefined): SiteBinding | undefined {
  if (config.entry_id !== undefined && config.site_id !== undefined) {
    return { entry_id: config.entry_id, site_id: config.site_id };
  }
  const sites = allSites(sources ?? []);
  return sites.length === 1 ? sites[0]!.binding : undefined;
}

export function sameBinding(a: SiteBinding | undefined, b: SiteBinding | undefined): boolean {
  return a?.entry_id === b?.entry_id && a?.site_id === b?.site_id;
}
```

- [ ] **Step 7: Implement `localize.ts`**

```ts
/**
 * Card UI strings. English ships in the bundle; other languages fall back to
 * it. (The integration's translations/ folder is backend-only.)
 */
const en = {
  'card.name': 'UniFi Insights Topology',
  'card.description': 'Interactive network topology of a UniFi site, from UniFi Insights.',
  'state.loading': 'Loading network topology…',
  'state.no_sources': 'No UniFi Insights integration is loaded.',
  'state.unconfigured': 'Choose a site to show.',
  'state.empty': 'No devices reported for {site}.',
  'state.incompatible': "Card and integration versions don't match. Refresh the browser (clear cache) after updating.",
  'state.stale': 'Stale',
  'state.reconnecting': 'Reconnecting…',
  'state.online': 'Online',
  'state.offline': 'Offline',
  'state.unknown': 'Unknown',
  'issue.site_unavailable': 'Site data temporarily unavailable; will recover automatically.',
  'issue.devices_unavailable': 'Device data unavailable; showing last known layout.',
  'issue.legacy_uplink_missing': 'Uplink details unavailable; device links may be missing.',
  'issue.parents_unresolved': "{count} nodes couldn't be placed under a parent.",
  'issue.clients_truncated': 'Showing {included} of {total} clients (limit {max}).',
  'issue.entry_unloaded': 'Integration is reloading.',
  'issue.unknown': 'Topology problem: {code}.',
  'error.entry_not_found': 'The configured site no longer exists or is disabled.',
  'error.site_not_selected': 'The configured site no longer exists or is disabled.',
  'error.entry_not_loaded': "Integration isn't loaded (retrying).",
  'error.unknown': 'Could not load the topology ({code}).',
  'action.integration': 'Integration',
  'action.edit': 'Edit card',
  'view.graph': 'Graph',
  'view.list': 'List',
  'toolbar.view': 'View',
  'toolbar.filters': 'Show',
  'toolbar.zoom': 'Zoom',
  'toolbar.options': 'Options',
  'toolbar.site': 'Site',
  'zoom.in': 'Zoom in',
  'zoom.out': 'Zoom out',
  'zoom.fit': 'Fit to view',
  'zoom.hint': 'Use Ctrl + scroll to zoom',
  'kind.gateway': 'Gateway',
  'kind.switch': 'Switch',
  'kind.access_point': 'Access point',
  'kind.client': 'Client',
  'kind.other': 'Other',
  'medium.wired': 'Wired',
  'medium.wireless': 'Wireless',
  'medium.unknown': 'Unknown',
  'group.clients': '{count} clients',
  'group.client_one': '1 client',
  'group.unconnected': 'Unconnected clients',
  'group.root': 'Clients',
  'group.summary': '{wireless} wireless, {offline} offline',
  'graph.label': '{site} topology, {devices} devices, {clients} clients',
  'graph.roledescription': 'network topology',
  'node.label': '{kind} {name}, {state}',
  'node.clients': '{count} clients',
  'node.client_one': '1 client',
  'node.uplink': 'uplink port {port}',
  'node.uplink_speed': 'uplink port {port} at {speed}',
  'list.label': '{site} devices and clients',
  'list.search': 'Search',
  'list.no_matches': 'No matches',
  'detail.close': 'Close',
  'detail.kind': 'Type',
  'detail.model': 'Model',
  'detail.state': 'State',
  'detail.parent': 'Connected to',
  'detail.port': 'Port',
  'detail.speed': 'Speed',
  'detail.medium': 'Link',
  'detail.poe': 'PoE',
  'detail.clients': 'Clients',
  'detail.clients_value': '{total} ({wired} wired, {wireless} wireless)',
  'detail.connection': 'Connection',
  'detail.vlan': 'VLAN',
  'detail.network': 'Network',
  'detail.via_hidden': 'Via hidden',
  'detail.open_device': 'Open device',
  'detail.search_members': 'Search clients',
  'announce.updated': 'Topology updated.',
  'announce.offline': '{count} devices offline.',
  'editor.site': 'Site',
  'editor.site_unavailable': '{site} (unavailable)',
  'editor.title': 'Title',
  'editor.view': 'Default view',
  'editor.clients': 'Clients',
  'editor.kinds': 'Show node types',
  'editor.density': 'Density',
  'editor.orientation': 'Orientation',
  'editor.show_site_selector': 'Show site selector',
  'editor.show_labels': 'Show labels',
  'editor.max_clients': 'Maximum clients',
  'clients.collapsed': 'Grouped',
  'clients.expanded': 'Expanded',
  'clients.hidden': 'Hidden',
  'density.auto': 'Automatic',
  'density.comfortable': 'Comfortable',
  'density.compact': 'Compact',
  'orientation.vertical': 'Top to bottom',
  'orientation.horizontal': 'Left to right',
} as const;

export type LocalizeKey = keyof typeof en;
export type LocalizeVars = Record<string, string | number>;
export type LocalizeFunc = (key: LocalizeKey, vars?: LocalizeVars) => string;

const TABLES: Record<string, Partial<Record<LocalizeKey, string>>> = { en };

export function makeLocalize(language: string | undefined): LocalizeFunc {
  const lang = (language ?? 'en').toLowerCase();
  const table = TABLES[lang] ?? TABLES[lang.split('-')[0] ?? 'en'] ?? {};
  return (key, vars) => {
    let text: string = table[key] ?? en[key];
    if (vars) for (const [name, value] of Object.entries(vars)) text = text.replaceAll(`{${name}}`, String(value));
    return text;
  };
}
```

- [ ] **Step 8: Run the tests and checks**

```bash
cd ~/ha-unifi-insights-card/frontend
npm test && npm run typecheck && npm run lint
```
Expected: all tests pass (smoke + contract + config + localize); typecheck and lint clean. If `satisfies` reports a missing/extra key, the spec object — not contract.ts — is wrong unless the Python contract really changed.

- [ ] **Step 9: Rebuild and commit**

```bash
npm run build
cd ~/ha-unifi-insights-card
$VENV/pytest tests/test_topology.py -q --no-cov
git add frontend tests/test_topology.py custom_components/unifi_insights/frontend/topology-card.js
git commit -m "feat(frontend): topology contract types, config and strings

contract.ts is the card's only view of the wire format. A fixture
generated by the Python builder is validated field by field against it,
so a backend contract change fails CI on both sides. Card config
validation ignores keys HA adds (grid_options, visibility).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Subscription lifecycle, card state machine, announcer

**Files:**
- Create: `frontend/src/data/subscription.ts`, `frontend/src/data/state.ts`, `frontend/src/data/announcer.ts`
- Test: `frontend/test/subscription.test.ts`, `frontend/test/state.test.ts`, `frontend/test/announcer.test.ts`

**Interfaces:**
- Consumes: Task 3 `contract.ts`, `ha-types.ts`, `config.ts` (`SiteBinding`), `localize.ts` (`LocalizeKey`, `LocalizeVars`), `test/helpers.ts`.
- Produces:
  - `subscription.ts`: `interface SubscriptionKey { entry_id; site_id; max_clients }`, `interface SubscriptionHandlers { onSnapshot(s: SiteTopology): void; onError(e: WsError): void; onIncompatible(): void }`, `BACKOFF_BASE_MS = 2000`, `BACKOFF_MAX_MS = 60000`, `backoffDelay(attempt, random?)`, `class TopologySubscription { constructor(handlers, random?); get live(): boolean; update(connection?, key?): void; stop(): void }`.
  - `state.ts`: `type CardPhase`, `type NoticeAction = 'integration' | 'edit'`, `interface Notice { code; severity; key; vars?; action? }`, `interface StateInput`, `interface CardState { phase; render?: SiteTopology; stale: boolean; notices: Notice[] }`, `issueNotice(issue, snapshot, maxClients)`, `errorNotice(error)`, `deriveState(input)`.
  - `announcer.ts`: `class Announcer { constructor(emit, intervalMs = 5000); announce(message): void; dispose(): void }`.

- [ ] **Step 1: Write the failing subscription tests**

`frontend/test/subscription.test.ts`:
```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BACKOFF_MAX_MS, TopologySubscription, backoffDelay } from '../src/data/subscription';
import type { Connection, MessageBase } from '../src/ha-types';
import { fixtureSnapshot, unavailableSnapshot } from './helpers';

interface Call { callback: (message: unknown) => void; message: MessageBase; options: unknown; unsubscribe: ReturnType<typeof vi.fn> }

function fakeConnection(opts: { emitOnSubscribe?: unknown } = {}) {
  const calls: Call[] = [];
  let failNext: unknown;
  let hold: ((u: () => Promise<void>) => void)[] | undefined;
  const connection = {
    subscribeMessage: vi.fn((callback: (m: unknown) => void, message: MessageBase, options?: unknown) => {
      if (failNext !== undefined) {
        const err = failNext;
        failNext = undefined;
        return Promise.reject(err);
      }
      const unsubscribe = vi.fn(async () => undefined);
      calls.push({ callback, message, options, unsubscribe });
      // HA can deliver the first event in the same frame as the result.
      if (opts.emitOnSubscribe !== undefined) callback(opts.emitOnSubscribe);
      if (hold) return new Promise<() => Promise<void>>((resolve) => hold!.push(resolve)).then(() => unsubscribe);
      return Promise.resolve(unsubscribe);
    }),
  };
  return {
    connection: connection as unknown as Connection,
    calls,
    failNext: (err: unknown) => { failNext = err; },
    holdResults: () => { hold = []; return () => hold!.splice(0).forEach((r) => r(async () => undefined)); },
  };
}

const KEY = { entry_id: 'entry-1', site_id: 'site-1', max_clients: 500 };
const flush = () => new Promise((r) => setTimeout(r, 0));

function handlers() {
  return { onSnapshot: vi.fn(), onError: vi.fn(), onIncompatible: vi.fn() };
}

describe('TopologySubscription', () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it('subscribes once with the site key and library resubscribe', async () => {
    const fake = fakeConnection();
    const sub = new TopologySubscription(handlers());
    sub.update(fake.connection, KEY);
    sub.update(fake.connection, { ...KEY });
    await vi.runAllTimersAsync();
    expect(fake.calls).toHaveLength(1);
    expect(fake.calls[0]!.message).toEqual({ type: 'unifi_insights/topology/subscribe', ...KEY });
    expect(fake.calls[0]!.options).toEqual({ resubscribe: true });
  });

  it('resubscribes when the key or the connection changes', async () => {
    const fake = fakeConnection();
    const other = fakeConnection();
    const sub = new TopologySubscription(handlers());
    sub.update(fake.connection, KEY);
    await vi.runAllTimersAsync();
    sub.update(fake.connection, { ...KEY, site_id: 'site-2' });
    await vi.runAllTimersAsync();
    expect(fake.calls[0]!.unsubscribe).toHaveBeenCalledOnce();
    expect(fake.calls).toHaveLength(2);
    sub.update(other.connection, { ...KEY, site_id: 'site-2' });
    await vi.runAllTimersAsync();
    expect(fake.calls[1]!.unsubscribe).toHaveBeenCalledOnce();
    expect(other.calls).toHaveLength(1);
  });

  it('marks live inside the event callback, before the result resolves', () => {
    const fake = fakeConnection({ emitOnSubscribe: fixtureSnapshot() });
    const h = handlers();
    const sub = new TopologySubscription(h);
    sub.update(fake.connection, KEY);
    expect(sub.live).toBe(true);
    expect(h.onSnapshot).toHaveBeenCalledOnce();
  });

  it('drops a repeated revision', async () => {
    const fake = fakeConnection();
    const h = handlers();
    const sub = new TopologySubscription(h);
    sub.update(fake.connection, KEY);
    await vi.runAllTimersAsync();
    fake.calls[0]!.callback(fixtureSnapshot());
    fake.calls[0]!.callback(fixtureSnapshot());
    expect(h.onSnapshot).toHaveBeenCalledOnce();
  });

  it('delivers consecutive unavailable snapshots with empty revisions', async () => {
    const fake = fakeConnection();
    const h = handlers();
    const sub = new TopologySubscription(h);
    sub.update(fake.connection, KEY);
    await vi.runAllTimersAsync();
    fake.calls[0]!.callback(unavailableSnapshot('site_unavailable'));
    fake.calls[0]!.callback(unavailableSnapshot('entry_unloaded'));
    expect(h.onSnapshot).toHaveBeenCalledTimes(2);
    expect(h.onSnapshot.mock.calls[1]![0].issues[0].code).toBe('entry_unloaded');
  });

  it('releases a server-ended stream and retries with backoff until it recovers', async () => {
    const fake = fakeConnection();
    const h = handlers();
    const sub = new TopologySubscription(h, () => 0.5); // jitter factor exactly 1.0
    sub.update(fake.connection, KEY);
    await vi.runAllTimersAsync();
    fake.calls[0]!.callback(unavailableSnapshot('entry_unloaded'));
    expect(fake.calls[0]!.unsubscribe).toHaveBeenCalledOnce();
    expect(sub.live).toBe(false);

    fake.failNext({ code: 'entry_not_loaded', message: 'not loaded' });
    await vi.advanceTimersByTimeAsync(1999);
    expect(fake.connection.subscribeMessage).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(fake.connection.subscribeMessage).toHaveBeenCalledTimes(2);
    expect(h.onError).toHaveBeenCalledWith({ code: 'entry_not_loaded', message: 'not loaded' });

    await vi.advanceTimersByTimeAsync(4000); // second retry: 4 s
    expect(fake.calls).toHaveLength(2);
    fake.calls[1]!.callback(fixtureSnapshot());
    expect(sub.live).toBe(true);

    // Backoff reset: the next unload waits 2 s again, not 8 s.
    fake.calls[1]!.callback(unavailableSnapshot('entry_unloaded'));
    await vi.advanceTimersByTimeAsync(2000);
    expect(fake.calls).toHaveLength(3);
  });

  it('does not retry errors a retry cannot fix', async () => {
    const fake = fakeConnection();
    const h = handlers();
    fake.failNext({ code: 'site_not_selected', message: 'no' });
    new TopologySubscription(h).update(fake.connection, KEY);
    await vi.advanceTimersByTimeAsync(BACKOFF_MAX_MS * 2);
    expect(h.onError).toHaveBeenCalledOnce();
    expect(fake.connection.subscribeMessage).toHaveBeenCalledOnce();
  });

  it('stop cancels a pending retry and ignores late events', async () => {
    const fake = fakeConnection();
    const h = handlers();
    const sub = new TopologySubscription(h);
    sub.update(fake.connection, KEY);
    await vi.runAllTimersAsync();
    const stale = fake.calls[0]!.callback;
    stale(unavailableSnapshot('entry_unloaded'));
    sub.stop();
    await vi.advanceTimersByTimeAsync(BACKOFF_MAX_MS * 2);
    expect(fake.connection.subscribeMessage).toHaveBeenCalledOnce();
    stale(fixtureSnapshot());
    expect(h.onSnapshot).toHaveBeenCalledOnce();
  });

  it('unsubscribes a subscription that resolves after stop', async () => {
    vi.useRealTimers();
    const fake = fakeConnection();
    const release = fake.holdResults();
    const sub = new TopologySubscription(handlers());
    sub.update(fake.connection, KEY);
    sub.stop();
    sub.update(fake.connection, KEY); // re-attached before the first result arrived
    release();
    await flush();
    expect(fake.calls).toHaveLength(2);
    expect(fake.calls[0]!.unsubscribe).toHaveBeenCalledOnce();
    expect(fake.calls[1]!.unsubscribe).not.toHaveBeenCalled();
  });

  it('reports an incompatible schema and a malformed payload', async () => {
    const fake = fakeConnection();
    const h = handlers();
    new TopologySubscription(h).update(fake.connection, KEY);
    await vi.runAllTimersAsync();
    fake.calls[0]!.callback({ ...fixtureSnapshot(), schema_version: 2 });
    fake.calls[0]!.callback({ nope: true });
    expect(h.onIncompatible).toHaveBeenCalledOnce();
    expect(h.onError).toHaveBeenCalledWith(expect.objectContaining({ code: 'invalid_payload' }));
  });

  it('does nothing without a connection or a key', () => {
    const fake = fakeConnection();
    const sub = new TopologySubscription(handlers());
    sub.update(undefined, KEY);
    sub.update(fake.connection, undefined);
    expect(fake.connection.subscribeMessage).not.toHaveBeenCalled();
  });
});

describe('backoffDelay', () => {
  it('doubles from 2 s, caps at 60 s and jitters ±20 %', () => {
    expect(backoffDelay(0, () => 0.5)).toBe(2000);
    expect(backoffDelay(1, () => 0.5)).toBe(4000);
    expect(backoffDelay(10, () => 0.5)).toBe(60000);
    expect(backoffDelay(0, () => 0)).toBe(1600);
    expect(backoffDelay(0, () => 1)).toBe(2400);
  });
});
```

Run: `npm test -- subscription` → FAIL (module not found).

- [ ] **Step 2: Implement `data/subscription.ts`**

```ts
import {
  ERR_ENTRY_NOT_LOADED, ISSUE_ENTRY_UNLOADED, IncompatibleSchemaError, WS_SUBSCRIBE, parseSnapshot,
  type SiteTopology,
} from '../contract';
import { toWsError, type Connection, type UnsubscribeFunc, type WsError } from '../ha-types';

export interface SubscriptionKey {
  entry_id: string;
  site_id: string;
  max_clients: number;
}

export interface SubscriptionHandlers {
  onSnapshot(snapshot: SiteTopology): void;
  onError(error: WsError): void;
  onIncompatible(): void;
}

export const BACKOFF_BASE_MS = 2000;
export const BACKOFF_MAX_MS = 60000;

/** 2 s, 4 s, 8 s ... capped at 60 s, with ±20 % jitter. */
export function backoffDelay(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(BACKOFF_BASE_MS * 2 ** attempt, BACKOFF_MAX_MS);
  return Math.round(base * (0.8 + 0.4 * random()));
}

/**
 * One card's `topology/subscribe` stream.
 *
 * Socket reconnects are handled by home-assistant-js-websocket's own
 * resubscribe; this class covers what the server ends: after
 * `entry_unloaded` it releases the dead subscription and retries with
 * backoff (retrying `entry_not_loaded` too). A generation counter makes every
 * callback from a superseded subscription a no-op, so racing
 * `set hass`/connect/disconnect calls can never leave two streams open.
 */
export class TopologySubscription {
  private generation = 0;
  private connection: Connection | undefined;
  private key: SubscriptionKey | undefined;
  private keyId: string | undefined;
  private unsubscribe: UnsubscribeFunc | undefined;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private attempt = 0;
  private lastRevision: string | undefined;
  private isLive = false;
  private readonly handlers: SubscriptionHandlers;
  private readonly random: () => number;

  constructor(handlers: SubscriptionHandlers, random: () => number = Math.random) {
    this.handlers = handlers;
    this.random = random;
  }

  get live(): boolean {
    return this.isLive;
  }

  /** Point the stream at a connection and site; a no-op when neither changed. */
  update(connection: Connection | undefined, key: SubscriptionKey | undefined): void {
    const keyId = key ? JSON.stringify([key.entry_id, key.site_id, key.max_clients]) : undefined;
    if (connection === this.connection && keyId === this.keyId) return;
    this.stop();
    this.connection = connection;
    this.key = key;
    this.keyId = keyId;
    if (connection && key) this.open();
  }

  stop(): void {
    this.generation++;
    if (this.retryTimer !== undefined) clearTimeout(this.retryTimer);
    this.retryTimer = undefined;
    this.attempt = 0;
    this.release();
    this.connection = undefined;
    this.key = undefined;
    this.keyId = undefined;
  }

  private release(): void {
    const unsubscribe = this.unsubscribe;
    this.unsubscribe = undefined;
    this.isLive = false;
    this.lastRevision = undefined;
    // After entry_unloaded the server already dropped it; this call still
    // stops the websocket library from resubscribing it on reconnect.
    if (unsubscribe) unsubscribe().catch(() => undefined);
  }

  private open(): void {
    const generation = ++this.generation;
    const { connection, key } = this;
    if (!connection || !key) return;
    connection
      .subscribeMessage<unknown>(
        (raw) => {
          if (generation === this.generation) this.receive(raw);
        },
        { type: WS_SUBSCRIBE, entry_id: key.entry_id, site_id: key.site_id, max_clients: key.max_clients },
        { resubscribe: true },
      )
      .then(
        (unsubscribe) => {
          if (generation === this.generation) this.unsubscribe = unsubscribe;
          else unsubscribe().catch(() => undefined);
        },
        (err: unknown) => {
          if (generation !== this.generation) return;
          const error = toWsError(err);
          this.handlers.onError(error);
          if (error.code === ERR_ENTRY_NOT_LOADED) this.scheduleRetry();
        },
      );
  }

  private receive(raw: unknown): void {
    let snapshot: SiteTopology;
    try {
      snapshot = parseSnapshot(raw);
    } catch (err) {
      if (err instanceof IncompatibleSchemaError) this.handlers.onIncompatible();
      else this.handlers.onError({ code: 'invalid_payload', message: String(err) });
      return;
    }
    const unloaded = snapshot.issues.some((issue) => issue.code === ISSUE_ENTRY_UNLOADED);
    if (!unloaded) {
      // Set here, not after `await subscribeMessage`: HA can deliver the
      // result and the first event in the same frame.
      this.isLive = true;
      this.attempt = 0;
    }
    // Every unavailable snapshot carries revision "", so only real revisions dedupe.
    if (snapshot.revision !== '' && snapshot.revision === this.lastRevision) return;
    this.lastRevision = snapshot.revision;
    this.handlers.onSnapshot(snapshot);
    if (unloaded) {
      this.generation++;
      this.release();
      this.scheduleRetry();
    }
  }

  private scheduleRetry(): void {
    const generation = this.generation;
    const delay = backoffDelay(this.attempt++, this.random);
    this.retryTimer = setTimeout(() => {
      this.retryTimer = undefined;
      if (generation === this.generation) this.open();
    }, delay);
  }
}
```

Run: `npm test -- subscription` → all pass.

- [ ] **Step 3: Write the failing state and announcer tests**

`frontend/test/state.test.ts`:
```ts
import { describe, expect, it } from 'vitest';
import { deriveState, errorNotice, issueNotice, type StateInput } from '../src/data/state';
import { SOURCES_ONE, fixtureSnapshot, unavailableSnapshot } from './helpers';

const BINDING = { entry_id: 'entry-1', site_id: 'site-1' };
const base: StateInput = { sources: SOURCES_ONE, binding: BINDING, incompatible: false, maxClients: 500 };

describe('deriveState', () => {
  it('reports incompatible above everything else', () => {
    expect(deriveState({ ...base, incompatible: true, error: { code: 'x', message: '' } }).phase).toBe('incompatible');
  });

  it('shows an error over the last good graph', () => {
    const lastGood = fixtureSnapshot();
    const state = deriveState({ ...base, error: { code: 'site_not_selected', message: '' }, lastGood });
    expect(state).toMatchObject({ phase: 'error', render: lastGood, stale: true });
    expect(state.notices[0]).toMatchObject({ key: 'error.site_not_selected', action: 'edit' });
    expect(deriveState({ ...base, error: { code: 'boom', message: '' } })).toMatchObject({ render: undefined, stale: false });
  });

  it('walks loading → no_sources → unconfigured → loading', () => {
    expect(deriveState({ ...base, sources: undefined, binding: undefined }).phase).toBe('loading');
    expect(deriveState({ ...base, sources: [] }).phase).toBe('no_sources');
    expect(deriveState({ ...base, binding: undefined }).phase).toBe('unconfigured');
    expect(deriveState({ ...base }).phase).toBe('loading');
  });

  it('renders ok, empty and partial snapshots', () => {
    expect(deriveState({ ...base, snapshot: fixtureSnapshot() })).toMatchObject({ phase: 'ok', stale: false, notices: [] });
    expect(deriveState({ ...base, snapshot: fixtureSnapshot({ nodes: [], edges: [] }) }).phase).toBe('empty');
    const partial = fixtureSnapshot({
      status: 'partial',
      issues: [{ code: 'parents_unresolved', severity: 'warning' }, { code: 'clients_truncated', severity: 'info' }],
      unresolved: [{ node_id: 'dev:x', reason: 'parent_not_found' }, { node_id: 'cli:y', reason: 'no_uplink_data' }],
      truncation: { clients_total: 612, clients_included: 500 },
    });
    const state = deriveState({ ...base, snapshot: partial });
    expect(state.phase).toBe('partial');
    expect(state.notices).toEqual([
      { code: 'parents_unresolved', severity: 'warning', key: 'issue.parents_unresolved', vars: { count: 2 } },
      { code: 'clients_truncated', severity: 'info', key: 'issue.clients_truncated', vars: { included: 500, total: 612, max: 500 } },
    ]);
  });

  it('keeps the last good graph, greyed, while a site is unavailable', () => {
    const lastGood = fixtureSnapshot();
    const state = deriveState({ ...base, snapshot: unavailableSnapshot('site_unavailable'), lastGood });
    expect(state).toMatchObject({ phase: 'unavailable', render: lastGood, stale: true });
  });

  it('renders last-known devices when devices are unavailable', () => {
    const snapshot = fixtureSnapshot({ status: 'unavailable', issues: [{ code: 'devices_unavailable', severity: 'error' }] });
    const state = deriveState({ ...base, snapshot });
    expect(state).toMatchObject({ phase: 'unavailable', render: snapshot, stale: true });
    expect(state.notices[0]).toMatchObject({ action: 'integration' });
  });

  it('shows reloading after entry_unloaded', () => {
    expect(deriveState({ ...base, snapshot: unavailableSnapshot('entry_unloaded') })).toMatchObject({ phase: 'reloading', render: undefined, stale: false });
  });
});

describe('notices', () => {
  it('falls back to a generic message for unknown codes', () => {
    expect(issueNotice({ code: 'new_thing', severity: 'warning' }, fixtureSnapshot(), 500))
      .toEqual({ code: 'new_thing', severity: 'warning', key: 'issue.unknown', vars: { code: 'new_thing' } });
    expect(errorNotice({ code: 'weird', message: '' }))
      .toEqual({ code: 'weird', severity: 'error', key: 'error.unknown', vars: { code: 'weird' } });
  });

  it('attaches the right action to each error', () => {
    expect(errorNotice({ code: 'entry_not_found', message: '' }).action).toBe('edit');
    expect(errorNotice({ code: 'entry_not_loaded', message: '' }).action).toBe('integration');
  });
});
```

`frontend/test/announcer.test.ts`:
```ts
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Announcer } from '../src/data/announcer';

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

it('announces at most once per interval, keeping the latest message', () => {
  const emit = vi.fn();
  const announcer = new Announcer(emit, 5000);
  announcer.announce('a');
  announcer.announce('b');
  announcer.announce('c');
  expect(emit.mock.calls).toEqual([['a']]);
  vi.advanceTimersByTime(5000);
  expect(emit.mock.calls).toEqual([['a'], ['c']]);
  vi.advanceTimersByTime(5000);
  announcer.announce('d');
  expect(emit.mock.calls).toEqual([['a'], ['c'], ['d']]);
});

it('drops pending messages on dispose', () => {
  const emit = vi.fn();
  const announcer = new Announcer(emit, 5000);
  announcer.announce('a');
  announcer.announce('b');
  announcer.dispose();
  vi.advanceTimersByTime(10000);
  expect(emit.mock.calls).toEqual([['a']]);
});
```

Run: `npm test -- state announcer` → FAIL (modules not found).

- [ ] **Step 4: Implement `data/state.ts` and `data/announcer.ts`**

`frontend/src/data/state.ts`:
```ts
import type { SiteBinding } from '../config';
import {
  ERR_ENTRY_NOT_FOUND, ERR_ENTRY_NOT_LOADED, ERR_SITE_NOT_SELECTED, ISSUE_CLIENTS_TRUNCATED,
  ISSUE_DEVICES_UNAVAILABLE, ISSUE_ENTRY_UNLOADED, ISSUE_LEGACY_UPLINK_MISSING, ISSUE_PARENTS_UNRESOLVED,
  ISSUE_SITE_UNAVAILABLE, type IssueSeverity, type SiteTopology, type TopologyIssue, type TopologySource,
} from '../contract';
import type { WsError } from '../ha-types';
import type { LocalizeKey, LocalizeVars } from '../localize';

export type CardPhase =
  | 'loading' | 'no_sources' | 'unconfigured' | 'empty' | 'ok' | 'partial'
  | 'unavailable' | 'reloading' | 'error' | 'incompatible';

export type NoticeAction = 'integration' | 'edit';

export interface Notice {
  code: string;
  severity: IssueSeverity;
  key: LocalizeKey;
  vars?: LocalizeVars;
  action?: NoticeAction;
}

export interface StateInput {
  sources: TopologySource[] | undefined;
  binding: SiteBinding | undefined;
  snapshot?: SiteTopology | undefined;
  lastGood?: SiteTopology | undefined;
  error?: WsError | undefined;
  incompatible: boolean;
  maxClients: number;
}

export interface CardState {
  phase: CardPhase;
  /** The snapshot to draw (possibly the last good one), if any. */
  render?: SiteTopology | undefined;
  /** `render` is not current data: draw it greyed with a "stale" badge. */
  stale: boolean;
  notices: Notice[];
}

interface NoticeText {
  key: LocalizeKey;
  action?: NoticeAction;
}

const ISSUE_TEXT: Record<string, NoticeText> = {
  [ISSUE_SITE_UNAVAILABLE]: { key: 'issue.site_unavailable' },
  [ISSUE_DEVICES_UNAVAILABLE]: { key: 'issue.devices_unavailable', action: 'integration' },
  [ISSUE_LEGACY_UPLINK_MISSING]: { key: 'issue.legacy_uplink_missing' },
  [ISSUE_PARENTS_UNRESOLVED]: { key: 'issue.parents_unresolved' },
  [ISSUE_CLIENTS_TRUNCATED]: { key: 'issue.clients_truncated' },
  [ISSUE_ENTRY_UNLOADED]: { key: 'issue.entry_unloaded' },
};

const ERROR_TEXT: Record<string, NoticeText> = {
  [ERR_ENTRY_NOT_FOUND]: { key: 'error.entry_not_found', action: 'edit' },
  [ERR_SITE_NOT_SELECTED]: { key: 'error.site_not_selected', action: 'edit' },
  [ERR_ENTRY_NOT_LOADED]: { key: 'error.entry_not_loaded', action: 'integration' },
};

export function issueNotice(issue: TopologyIssue, snapshot: SiteTopology, maxClients: number): Notice {
  const text = ISSUE_TEXT[issue.code];
  if (!text) return { code: issue.code, severity: issue.severity, key: 'issue.unknown', vars: { code: issue.code } };
  const notice: Notice = { code: issue.code, severity: issue.severity, key: text.key };
  if (issue.code === ISSUE_PARENTS_UNRESOLVED) notice.vars = { count: snapshot.unresolved.length };
  if (issue.code === ISSUE_CLIENTS_TRUNCATED && snapshot.truncation) {
    notice.vars = {
      included: snapshot.truncation.clients_included,
      total: snapshot.truncation.clients_total,
      max: maxClients,
    };
  }
  if (text.action) notice.action = text.action;
  return notice;
}

export function errorNotice(error: WsError): Notice {
  const text = ERROR_TEXT[error.code];
  if (!text) return { code: error.code, severity: 'error', key: 'error.unknown', vars: { code: error.code } };
  const notice: Notice = { code: error.code, severity: 'error', key: text.key };
  if (text.action) notice.action = text.action;
  return notice;
}

/** Pure mapping from what the card knows to what it shows (spec §5). */
export function deriveState(input: StateInput): CardState {
  if (input.incompatible) return { phase: 'incompatible', stale: false, notices: [] };
  if (input.error) {
    return { phase: 'error', render: input.lastGood, stale: input.lastGood !== undefined, notices: [errorNotice(input.error)] };
  }
  if (input.sources !== undefined && input.sources.length === 0) return { phase: 'no_sources', stale: false, notices: [] };
  if (input.binding === undefined) {
    return { phase: input.sources === undefined ? 'loading' : 'unconfigured', stale: false, notices: [] };
  }
  const snapshot = input.snapshot;
  if (snapshot === undefined) return { phase: 'loading', stale: false, notices: [] };
  const notices = snapshot.issues.map((issue) => issueNotice(issue, snapshot, input.maxClients));
  if (snapshot.status === 'unavailable') {
    const unloaded = snapshot.issues.some((issue) => issue.code === ISSUE_ENTRY_UNLOADED);
    const render = snapshot.nodes.length > 0 ? snapshot : input.lastGood;
    return { phase: unloaded ? 'reloading' : 'unavailable', render, stale: render !== undefined, notices };
  }
  if (snapshot.nodes.length === 0) return { phase: 'empty', stale: false, notices };
  return { phase: snapshot.status === 'partial' ? 'partial' : 'ok', render: snapshot, stale: false, notices };
}
```

`frontend/src/data/announcer.ts`:
```ts
/**
 * Feeds the card's polite live region. Snapshots can arrive every ~30 s, so
 * at most one message is spoken per interval and only the latest pending one.
 */
export class Announcer {
  private last = Number.NEGATIVE_INFINITY;
  private pending: string | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private readonly emit: (message: string) => void;
  private readonly intervalMs: number;

  constructor(emit: (message: string) => void, intervalMs = 5000) {
    this.emit = emit;
    this.intervalMs = intervalMs;
  }

  announce(message: string): void {
    const wait = this.last + this.intervalMs - Date.now();
    if (wait <= 0 && this.timer === undefined) {
      this.last = Date.now();
      this.emit(message);
      return;
    }
    this.pending = message;
    this.timer ??= setTimeout(() => {
      this.timer = undefined;
      const next = this.pending;
      this.pending = undefined;
      if (next !== undefined) {
        this.last = Date.now();
        this.emit(next);
      }
    }, Math.max(wait, 0));
  }

  dispose(): void {
    if (this.timer !== undefined) clearTimeout(this.timer);
    this.timer = undefined;
    this.pending = undefined;
  }
}
```

- [ ] **Step 5: Run everything and commit**

```bash
npm test && npm run typecheck && npm run lint && npm run build
cd ~/ha-unifi-insights-card
git add frontend custom_components/unifi_insights/frontend/topology-card.js
git commit -m "feat(frontend): topology subscription and card state machine

One subscription per card with a generation guard so racing hass
updates and reconnects never open two streams. After entry_unloaded the
dead subscription is released (so the websocket library will not revive
it) and retried with capped, jittered backoff. Empty revisions are never
deduped: every unavailable snapshot has one.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---
### Task 5: Graph model, layout, keyboard navigation (pure)

**Files:**
- Create: `frontend/src/model/graph-model.ts`, `frontend/src/model/layout.ts`, `frontend/src/model/navigation.ts`
- Test: `frontend/test/graph-model.test.ts`, `frontend/test/layout.test.ts`, `frontend/test/navigation.test.ts`

**Interfaces:**
- Consumes: `contract.ts` types, `config.ts` (`ClientsMode`, `Density`, `Orientation`), `test/helpers.ts`.
- Produces:
  - `graph-model.ts`: `UNCONNECTED_GROUP = 'group:unconnected'`, `ROOT_CLIENT_GROUP = 'group:root'`, `groupIdFor(parentId)`, types `ClientCounts { total; wired; wireless; offline }`, `DeviceVisual { type:'device'; id; node }`, `ClientVisual { type:'client'; id; node }`, `GroupVisual { type:'group'; id; members: TopologyNode[]; counts: ClientCounts; expanded: boolean }`, `Visual`, `VisualLink { childId; parentId; edge?: TopologyEdge; viaHidden: NodeKind[] }`, `UiState { kinds: ReadonlySet<NodeKind>; clients: ClientsMode; toggledGroups: ReadonlySet<string> }`, `GraphModel { snapshot; roots: string[]; visuals: Map<string, Visual>; children: Map<string, string[]>; parentOf: Map<string, string>; links: Map<string, VisualLink>; nodes: Map<string, TopologyNode>; realParent: Map<string, string>; edges: Map<string, TopologyEdge>; clientCounts: Map<string, ClientCounts>; stats: { devices; clients; offlineDevices } }`, `isGroupExpanded(ui, id)`, `buildModel(snapshot, ui)`, `createModelBuilder()`, `siblingsOf(model, id)`, `groupContaining(model, rawId)`.
  - `layout.ts`: `Point { x; y }`, `Bounds { minX; minY; maxX; maxY }`, `Layout { positions: Map<string, Point>; bounds: Bounds }`, `ViewTransform { x; y; k }`, `SPACING`, `CULL_THRESHOLD = 300`, `layoutModel(model, density, orientation)`, `fitTransform(bounds, width, height, padding = 48)`, `visibleIds(layout, transform, width, height, margin = 120)`.
  - `navigation.ts`: `nextGraphFocus(model, current, key, orientation): string | undefined` (undefined = not a navigation key).

- [ ] **Step 1: Write the failing model tests**

`frontend/test/graph-model.test.ts`:
```ts
import { describe, expect, it } from 'vitest';
import { NODE_KINDS, type NodeKind, type SiteTopology, type TopologyNode } from '../src/contract';
import {
  ROOT_CLIENT_GROUP, UNCONNECTED_GROUP, buildModel, createModelBuilder, groupContaining, isGroupExpanded,
  type UiState,
} from '../src/model/graph-model';
import { fixtureSnapshot } from './helpers';

const ui = (overrides: Partial<UiState> = {}): UiState => ({
  kinds: new Set(NODE_KINDS), clients: 'collapsed', toggledGroups: new Set(), ...overrides,
});
const node = (id: string, kind: NodeKind, name: string, extra: Partial<TopologyNode> = {}): TopologyNode =>
  ({ id, kind, name, state: 'online', ...extra });
const snap = (nodes: TopologyNode[], edges: [string, string][]): SiteTopology =>
  fixtureSnapshot({ nodes, edges: edges.map(([source, target]) => ({ source, target, medium: 'wired' })) });

describe('buildModel on the Python fixture', () => {
  const model = buildModel(fixtureSnapshot(), ui());

  it('builds the gateway → core → switches/AP tree, devices first by kind then name', () => {
    expect(model.roots).toEqual(['dev:uuid-gw']);
    expect(model.children.get('dev:uuid-gw')).toEqual(['dev:uuid-core']);
    expect(model.children.get('dev:uuid-core')).toEqual([
      'dev:uuid-flex', 'dev:uuid-lite', 'dev:uuid-pdu', 'dev:uuid-u1', 'dev:uuid-u2', 'dev:uuid-ap',
    ]);
  });

  it('carries the uplink edge on each link', () => {
    expect(model.links.get('dev:uuid-core')).toMatchObject({
      parentId: 'dev:uuid-gw', viaHidden: [], edge: { parent_port: 11, speed_mbps: 10000 },
    });
  });

  it('groups clients under their device, collapsed by default', () => {
    expect(model.children.get('dev:uuid-u1')).toEqual(['group:dev:uuid-u1']);
    expect(model.children.get('dev:uuid-ap')).toEqual(['group:dev:uuid-ap']);
    const group = model.visuals.get('group:dev:uuid-ap');
    expect(group).toMatchObject({ type: 'group', expanded: false, counts: { total: 1, wireless: 1 } });
    expect(model.visuals.has('cli:cli-phone')).toBe(false);
    expect(model.clientCounts.get('dev:uuid-u1')).toMatchObject({ total: 1, wired: 1 });
    expect(model.stats).toMatchObject({ devices: 8, clients: 2 });
  });
});

describe('client modes', () => {
  it('expands every group in expanded mode, and a toggle collapses one again', () => {
    const expanded = buildModel(fixtureSnapshot(), ui({ clients: 'expanded' }));
    expect(expanded.children.get('group:dev:uuid-ap')).toEqual(['cli:cli-phone']);
    expect(expanded.links.get('cli:cli-phone')).toMatchObject({ parentId: 'group:dev:uuid-ap' });
    const toggled = buildModel(fixtureSnapshot(), ui({ clients: 'expanded', toggledGroups: new Set(['group:dev:uuid-ap']) }));
    expect(toggled.visuals.has('cli:cli-phone')).toBe(false);
  });

  it('expands one toggled group in collapsed mode', () => {
    const m = buildModel(fixtureSnapshot(), ui({ toggledGroups: new Set(['group:dev:uuid-u1']) }));
    expect(m.children.get('group:dev:uuid-u1')).toEqual(['cli:cli-tv']);
    expect(isGroupExpanded(ui(), 'group:dev:uuid-u1')).toBe(false);
  });

  it('hides clients entirely but keeps their counts', () => {
    const m = buildModel(fixtureSnapshot(), ui({ clients: 'hidden' }));
    expect([...m.visuals.values()].some((v) => v.type !== 'device')).toBe(false);
    expect(m.clientCounts.get('dev:uuid-ap')?.total).toBe(1);
  });
});

describe('kind filter', () => {
  it('re-attaches children of hidden devices to the nearest visible ancestor', () => {
    const m = buildModel(fixtureSnapshot(), ui({ kinds: new Set<NodeKind>(['gateway', 'access_point', 'client']) }));
    expect(m.roots).toEqual(['dev:uuid-gw']);
    expect(m.children.get('dev:uuid-gw')).toEqual(['dev:uuid-ap', 'group:dev:uuid-gw']);
    expect(m.links.get('dev:uuid-ap')).toMatchObject({ parentId: 'dev:uuid-gw', viaHidden: ['switch'] });
    expect(m.links.get('group:dev:uuid-gw')).toMatchObject({ viaHidden: ['switch'] });
  });

  it('removes clients when the client kind is filtered out', () => {
    const m = buildModel(fixtureSnapshot(), ui({ kinds: new Set<NodeKind>(['gateway', 'switch', 'access_point']) }));
    expect([...m.visuals.keys()].some((id) => id.startsWith('group:'))).toBe(false);
  });

  it('puts clients whose whole ancestry is hidden into one root group', () => {
    const m = buildModel(fixtureSnapshot(), ui({ kinds: new Set<NodeKind>(['client']) }));
    expect(m.roots).toEqual([ROOT_CLIENT_GROUP]);
    expect(m.visuals.get(ROOT_CLIENT_GROUP)).toMatchObject({ counts: { total: 2 } });
  });
});

describe('malformed data', () => {
  it('ignores edges it cannot place', () => {
    const s = snap(
      [node('dev:gw', 'gateway', 'GW'), node('dev:sw', 'switch', 'SW'), node('dev:orphan', 'switch', 'Orphan'),
        node('cli:c', 'client', 'Laptop', { connection: 'wired' })],
      [['dev:sw', 'dev:gw'], ['dev:sw', 'dev:orphan'], ['dev:ghost', 'dev:gw'], ['dev:orphan', 'cli:c'], ['dev:gw', 'dev:gw']],
    );
    const m = buildModel(s, ui());
    expect(m.roots).toEqual(['dev:gw', 'dev:orphan', UNCONNECTED_GROUP]);
    expect(m.children.get('dev:gw')).toEqual(['dev:sw']);
    expect(m.realParent.has('dev:orphan')).toBe(false);
  });

  it('cuts parent cycles', () => {
    const s = snap([node('dev:a', 'switch', 'A'), node('dev:b', 'switch', 'B')], [['dev:a', 'dev:b'], ['dev:b', 'dev:a']]);
    const m = buildModel(s, ui());
    expect(m.roots).toEqual(['dev:b']);
    expect(m.children.get('dev:b')).toEqual(['dev:a']);
  });

  it('puts clients without devices in the unconnected group', () => {
    const s = snap([node('cli:x', 'client', 'X'), node('cli:y', 'client', 'Y', { state: 'offline' })], [['cli:x', 'dev:gone']]);
    const m = buildModel(s, ui());
    expect(m.roots).toEqual([UNCONNECTED_GROUP]);
    expect(m.visuals.get(UNCONNECTED_GROUP)).toMatchObject({ counts: { total: 2, offline: 1 } });
  });
});

describe('helpers', () => {
  it('memoizes on snapshot and ui identity', () => {
    const build = createModelBuilder();
    const s = fixtureSnapshot();
    const u = ui();
    expect(build(s, u)).toBe(build(s, u));
    expect(build(s, ui())).not.toBe(build(s, u));
  });

  it('finds the group holding a collapsed client', () => {
    const m = buildModel(fixtureSnapshot(), ui());
    expect(groupContaining(m, 'cli:cli-tv')?.id).toBe('group:dev:uuid-u1');
    expect(groupContaining(m, 'dev:uuid-u1')).toBeUndefined();
  });
});
```

`frontend/test/layout.test.ts`:
```ts
import { describe, expect, it } from 'vitest';
import { NODE_KINDS } from '../src/contract';
import { buildModel } from '../src/model/graph-model';
import { SPACING, fitTransform, layoutModel, visibleIds } from '../src/model/layout';
import { fixtureSnapshot } from './helpers';

const model = buildModel(fixtureSnapshot(), { kinds: new Set(NODE_KINDS), clients: 'collapsed', toggledGroups: new Set() });

describe('layoutModel', () => {
  it('places every visual, one depth step per level', () => {
    const layout = layoutModel(model, 'comfortable', 'vertical');
    expect([...layout.positions.keys()].sort()).toEqual([...model.visuals.keys()].sort());
    const depth = SPACING.comfortable.depth;
    expect(layout.positions.get('dev:uuid-gw')!.y).toBe(0);
    expect(layout.positions.get('dev:uuid-core')!.y).toBe(depth);
    expect(layout.positions.get('dev:uuid-ap')!.y).toBe(2 * depth);
    expect(layout.positions.get('group:dev:uuid-ap')!.y).toBe(3 * depth);
    const xs = model.children.get('dev:uuid-core')!.map((id) => layout.positions.get(id)!.x);
    expect(new Set(xs).size).toBe(xs.length);
  });

  it('swaps axes when horizontal and tightens when compact', () => {
    const horizontal = layoutModel(model, 'compact', 'horizontal');
    expect(horizontal.positions.get('dev:uuid-core')).toMatchObject({ x: SPACING.compact.depth });
    expect(horizontal.bounds.maxX).toBe(3 * SPACING.compact.depth);
  });

  it('handles an empty model', () => {
    const empty = buildModel(fixtureSnapshot({ nodes: [], edges: [] }), { kinds: new Set(NODE_KINDS), clients: 'collapsed', toggledGroups: new Set() });
    expect(layoutModel(empty, 'comfortable', 'vertical').positions.size).toBe(0);
  });
});

describe('viewport maths', () => {
  it('fits and centres the bounds, clamped to 1.5×', () => {
    expect(fitTransform({ minX: 0, minY: 0, maxX: 100, maxY: 100 }, 400, 300)).toEqual({ k: 1.5, x: 125, y: 75 });
    const wide = fitTransform({ minX: 0, minY: 0, maxX: 10000, maxY: 100 }, 400, 300);
    expect(wide.k).toBe(0.2);
  });

  it('culls positions outside the viewport plus margin', () => {
    const layout = { positions: new Map([['in', { x: 10, y: 10 }], ['out', { x: 5000, y: 10 }]]), bounds: { minX: 10, minY: 10, maxX: 5000, maxY: 10 } };
    expect([...visibleIds(layout, { x: 0, y: 0, k: 1 }, 800, 600)]).toEqual(['in']);
  });
});
```

`frontend/test/navigation.test.ts`:
```ts
import { expect, it } from 'vitest';
import { NODE_KINDS } from '../src/contract';
import { buildModel } from '../src/model/graph-model';
import { nextGraphFocus } from '../src/model/navigation';
import { fixtureSnapshot } from './helpers';

const model = buildModel(fixtureSnapshot(), { kinds: new Set(NODE_KINDS), clients: 'collapsed', toggledGroups: new Set() });

it('follows the tree with arrows (vertical)', () => {
  expect(nextGraphFocus(model, 'dev:uuid-core', 'ArrowUp', 'vertical')).toBe('dev:uuid-gw');
  expect(nextGraphFocus(model, 'dev:uuid-core', 'ArrowDown', 'vertical')).toBe('dev:uuid-flex');
  expect(nextGraphFocus(model, 'dev:uuid-flex', 'ArrowRight', 'vertical')).toBe('dev:uuid-lite');
  expect(nextGraphFocus(model, 'dev:uuid-flex', 'ArrowLeft', 'vertical')).toBe('dev:uuid-flex');
  expect(nextGraphFocus(model, 'dev:uuid-gw', 'ArrowUp', 'vertical')).toBe('dev:uuid-gw');
  expect(nextGraphFocus(model, 'group:dev:uuid-ap', 'ArrowDown', 'vertical')).toBe('group:dev:uuid-ap');
});

it('rotates the arrow keys when horizontal', () => {
  expect(nextGraphFocus(model, 'dev:uuid-core', 'ArrowLeft', 'horizontal')).toBe('dev:uuid-gw');
  expect(nextGraphFocus(model, 'dev:uuid-core', 'ArrowRight', 'horizontal')).toBe('dev:uuid-flex');
  expect(nextGraphFocus(model, 'dev:uuid-flex', 'ArrowDown', 'horizontal')).toBe('dev:uuid-lite');
});

it('starts at the first root and ignores other keys', () => {
  expect(nextGraphFocus(model, undefined, 'ArrowDown', 'vertical')).toBe('dev:uuid-gw');
  expect(nextGraphFocus(model, 'dev:gone', 'ArrowDown', 'vertical')).toBe('dev:uuid-gw');
  expect(nextGraphFocus(model, 'dev:uuid-core', 'Enter', 'vertical')).toBeUndefined();
});
```

Run: `npm test -- graph-model layout navigation` → FAIL (modules not found).

- [ ] **Step 2: Implement `model/graph-model.ts`**

```ts
import type { ClientsMode } from '../config';
import type { NodeKind, SiteTopology, TopologyEdge, TopologyNode } from '../contract';

export const UNCONNECTED_GROUP = 'group:unconnected';
export const ROOT_CLIENT_GROUP = 'group:root';
export const groupIdFor = (parentId: string): string => `group:${parentId}`;

export interface ClientCounts {
  total: number;
  wired: number;
  wireless: number;
  offline: number;
}

export interface DeviceVisual {
  type: 'device';
  id: string;
  node: TopologyNode;
}

export interface ClientVisual {
  type: 'client';
  id: string;
  node: TopologyNode;
}

export interface GroupVisual {
  type: 'group';
  id: string;
  members: TopologyNode[];
  counts: ClientCounts;
  expanded: boolean;
}

export type Visual = DeviceVisual | ClientVisual | GroupVisual;

/** A drawn link, keyed by its child. `viaHidden` lists filtered-out kinds it skips over. */
export interface VisualLink {
  childId: string;
  parentId: string;
  edge?: TopologyEdge | undefined;
  viaHidden: NodeKind[];
}

export interface UiState {
  kinds: ReadonlySet<NodeKind>;
  clients: ClientsMode;
  /** Groups flipped from the mode's default (expanded in collapsed mode, collapsed in expanded mode). */
  toggledGroups: ReadonlySet<string>;
}

export interface GraphModel {
  snapshot: SiteTopology;
  roots: string[];
  visuals: Map<string, Visual>;
  children: Map<string, string[]>;
  /** Visual child id → visual parent id. */
  parentOf: Map<string, string>;
  links: Map<string, VisualLink>;
  /** Raw node lookup (includes clients hidden inside collapsed groups). */
  nodes: Map<string, TopologyNode>;
  /** Raw child id → raw parent id, after invalid edges and cycles are dropped. */
  realParent: Map<string, string>;
  /** Raw child id → its uplink edge. */
  edges: Map<string, TopologyEdge>;
  /** Raw device id → its direct clients, regardless of filters. */
  clientCounts: Map<string, ClientCounts>;
  stats: { devices: number; clients: number; offlineDevices: number };
}

const KIND_ORDER: Record<NodeKind, number> = { gateway: 0, switch: 1, access_point: 2, other: 3, client: 4 };
const byName = (a: TopologyNode, b: TopologyNode): number => a.name.localeCompare(b.name) || a.id.localeCompare(b.id);
const byKindThenName = (a: TopologyNode, b: TopologyNode): number => KIND_ORDER[a.kind] - KIND_ORDER[b.kind] || byName(a, b);

export function isGroupExpanded(ui: UiState, id: string): boolean {
  const toggled = ui.toggledGroups.has(id);
  return ui.clients === 'expanded' ? !toggled : toggled;
}

const emptyCounts = (): ClientCounts => ({ total: 0, wired: 0, wireless: 0, offline: 0 });

function count(counts: ClientCounts, client: TopologyNode): void {
  counts.total++;
  if (client.connection === 'wired') counts.wired++;
  if (client.connection === 'wireless') counts.wireless++;
  if (client.state === 'offline') counts.offline++;
}

/** Drop the edge that closes each parent cycle, so every walk up terminates. */
function cutCycles(order: readonly TopologyNode[], parent: Map<string, string>, edges: Map<string, TopologyEdge>): void {
  const settled = new Set<string>();
  for (const start of order) {
    const path = new Set<string>();
    let current: string | undefined = start.id;
    while (current !== undefined && !settled.has(current)) {
      path.add(current);
      const next = parent.get(current);
      if (next !== undefined && path.has(next)) {
        parent.delete(current);
        edges.delete(current);
        break;
      }
      current = next;
    }
    for (const id of path) settled.add(id);
  }
}

/** Turn one snapshot plus the card's UI state into the tree every view draws. */
export function buildModel(snapshot: SiteTopology, ui: UiState): GraphModel {
  const nodes = new Map(snapshot.nodes.map((n) => [n.id, n]));
  const realParent = new Map<string, string>();
  const edges = new Map<string, TopologyEdge>();
  for (const edge of snapshot.edges) {
    const child = nodes.get(edge.source);
    const parent = nodes.get(edge.target);
    // Unknown ids, self-edges, client parents and second edges for one child cannot be placed.
    if (!child || !parent || child.id === parent.id || parent.kind === 'client' || realParent.has(child.id)) continue;
    realParent.set(child.id, parent.id);
    edges.set(child.id, edge);
  }
  cutCycles(snapshot.nodes, realParent, edges);

  const devices = snapshot.nodes.filter((n) => n.kind !== 'client').sort(byKindThenName);
  const clients = snapshot.nodes.filter((n) => n.kind === 'client').sort(byName);
  const clientCounts = new Map<string, ClientCounts>();
  for (const client of clients) {
    const parent = realParent.get(client.id);
    if (parent === undefined) continue;
    let counts = clientCounts.get(parent);
    if (!counts) clientCounts.set(parent, (counts = emptyCounts()));
    count(counts, client);
  }

  const visuals = new Map<string, Visual>();
  const children = new Map<string, string[]>();
  const parentOf = new Map<string, string>();
  const links = new Map<string, VisualLink>();
  const roots: string[] = [];
  const visible = (n: TopologyNode): boolean => ui.kinds.has(n.kind);
  const nearestVisibleAncestor = (rawId: string): { id: string | undefined; skipped: NodeKind[] } => {
    const skipped: NodeKind[] = [];
    let current = realParent.get(rawId);
    while (current !== undefined) {
      const n = nodes.get(current)!;
      if (visible(n)) return { id: current, skipped };
      skipped.push(n.kind);
      current = realParent.get(current);
    }
    return { id: undefined, skipped };
  };
  const attach = (childId: string, parentId: string | undefined, edge: TopologyEdge | undefined, skipped: Iterable<NodeKind>): void => {
    if (parentId === undefined) {
      roots.push(childId);
      return;
    }
    parentOf.set(childId, parentId);
    links.set(childId, { childId, parentId, edge, viaHidden: [...new Set(skipped)] });
    const list = children.get(parentId);
    if (list) list.push(childId);
    else children.set(parentId, [childId]);
  };

  for (const device of devices) {
    if (!visible(device)) continue;
    visuals.set(device.id, { type: 'device', id: device.id, node: device });
    const ancestor = nearestVisibleAncestor(device.id);
    attach(device.id, ancestor.id, edges.get(device.id), ancestor.skipped);
  }

  if (ui.clients !== 'hidden' && ui.kinds.has('client')) {
    const groups = new Map<string, { parent: string | undefined; members: TopologyNode[]; skipped: Set<NodeKind> }>();
    for (const client of clients) {
      const real = realParent.get(client.id);
      let parent: string | undefined;
      let skipped: NodeKind[] = [];
      let id: string;
      if (real === undefined) {
        id = UNCONNECTED_GROUP;
      } else {
        const realNode = nodes.get(real)!;
        if (visible(realNode)) {
          parent = real;
        } else {
          const ancestor = nearestVisibleAncestor(real);
          parent = ancestor.id;
          skipped = [realNode.kind, ...ancestor.skipped];
        }
        id = parent === undefined ? ROOT_CLIENT_GROUP : groupIdFor(parent);
      }
      let group = groups.get(id);
      if (!group) groups.set(id, (group = { parent, members: [], skipped: new Set() }));
      group.members.push(client);
      for (const kind of skipped) group.skipped.add(kind);
    }
    const ordered = [...groups].sort(([a], [b]) => Number(a === UNCONNECTED_GROUP) - Number(b === UNCONNECTED_GROUP));
    for (const [id, group] of ordered) {
      const counts = emptyCounts();
      for (const member of group.members) count(counts, member);
      const expanded = isGroupExpanded(ui, id);
      visuals.set(id, { type: 'group', id, members: group.members, counts, expanded });
      attach(id, group.parent, undefined, group.skipped);
      if (!expanded) continue;
      for (const member of group.members) {
        visuals.set(member.id, { type: 'client', id: member.id, node: member });
        attach(member.id, id, edges.get(member.id), []);
      }
    }
  }

  return {
    snapshot, roots, visuals, children, parentOf, links, nodes, realParent, edges, clientCounts,
    stats: {
      devices: devices.length,
      clients: clients.length,
      offlineDevices: devices.filter((d) => d.state === 'offline').length,
    },
  };
}

/** buildModel, memoized on snapshot and UI-state identity. */
export function createModelBuilder(): (snapshot: SiteTopology, ui: UiState) => GraphModel {
  let lastSnapshot: SiteTopology | undefined;
  let lastUi: UiState | undefined;
  let last: GraphModel | undefined;
  return (snapshot, ui) => {
    if (last && snapshot === lastSnapshot && ui === lastUi) return last;
    lastSnapshot = snapshot;
    lastUi = ui;
    last = buildModel(snapshot, ui);
    return last;
  };
}

export function siblingsOf(model: GraphModel, id: string): string[] {
  const parent = model.parentOf.get(id);
  return parent === undefined ? model.roots : (model.children.get(parent) ?? []);
}

/** The client group holding a raw client id, whether or not it is expanded. */
export function groupContaining(model: GraphModel, rawId: string): GroupVisual | undefined {
  for (const visual of model.visuals.values()) {
    if (visual.type === 'group' && visual.members.some((m) => m.id === rawId)) return visual;
  }
  return undefined;
}
```

- [ ] **Step 3: Implement `model/layout.ts` and `model/navigation.ts`**

`frontend/src/model/layout.ts`:
```ts
import { hierarchy, tree } from 'd3-hierarchy';
import type { Density, Orientation } from '../config';
import type { GraphModel } from './graph-model';

export interface Point {
  x: number;
  y: number;
}

export interface Bounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

export interface Layout {
  positions: Map<string, Point>;
  bounds: Bounds;
}

export interface ViewTransform {
  x: number;
  y: number;
  k: number;
}

/** Distance between siblings (`breadth`) and between levels (`depth`), in SVG units. */
export const SPACING: Record<Density, { breadth: number; depth: number }> = {
  comfortable: { breadth: 132, depth: 150 },
  compact: { breadth: 92, depth: 112 },
};

/** Above this many visible nodes only those near the viewport are put in the DOM. */
export const CULL_THRESHOLD = 300;

const SUPER_ROOT = '\u0000root';

/** Tidy-tree layout of the model; a synthetic super-root turns the forest into one tree. */
export function layoutModel(model: GraphModel, density: Density, orientation: Orientation): Layout {
  const positions = new Map<string, Point>();
  if (model.roots.length === 0) return { positions, bounds: { minX: 0, minY: 0, maxX: 0, maxY: 0 } };
  const { breadth, depth } = SPACING[density];
  const root = hierarchy<string>(SUPER_ROOT, (id) => (id === SUPER_ROOT ? model.roots : model.children.get(id)));
  const laidOut = tree<string>()
    .nodeSize([breadth, depth])
    .separation((a, b) => (a.parent === b.parent ? 1 : 1.25))(root);
  const bounds: Bounds = { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity };
  for (const n of laidOut.descendants()) {
    if (n.data === SUPER_ROOT) continue;
    const along = n.x;
    const down = (n.depth - 1) * depth;
    const p = orientation === 'vertical' ? { x: along, y: down } : { x: down, y: along };
    positions.set(n.data, p);
    bounds.minX = Math.min(bounds.minX, p.x);
    bounds.minY = Math.min(bounds.minY, p.y);
    bounds.maxX = Math.max(bounds.maxX, p.x);
    bounds.maxY = Math.max(bounds.maxY, p.y);
  }
  return { positions, bounds };
}

/** Transform that centres `bounds` in the viewport, scaled into [0.2, 1.5]. */
export function fitTransform(bounds: Bounds, width: number, height: number, padding = 48): ViewTransform {
  const w = Math.max(bounds.maxX - bounds.minX, 1);
  const h = Math.max(bounds.maxY - bounds.minY, 1);
  const k = Math.min(1.5, Math.max(0.2, Math.min((width - 2 * padding) / w, (height - 2 * padding) / h)));
  const cx = (bounds.minX + bounds.maxX) / 2;
  const cy = (bounds.minY + bounds.maxY) / 2;
  return { k, x: width / 2 - cx * k, y: height / 2 - cy * k };
}

/** Ids whose screen position falls inside the viewport grown by `margin` px. */
export function visibleIds(layout: Layout, t: ViewTransform, width: number, height: number, margin = 120): Set<string> {
  const out = new Set<string>();
  for (const [id, p] of layout.positions) {
    const sx = p.x * t.k + t.x;
    const sy = p.y * t.k + t.y;
    if (sx >= -margin && sx <= width + margin && sy >= -margin && sy <= height + margin) out.add(id);
  }
  return out;
}
```

`frontend/src/model/navigation.ts`:
```ts
import type { Orientation } from '../config';
import { siblingsOf, type GraphModel } from './graph-model';

/**
 * Arrow-key movement over the drawn tree: towards the parent, into the first
 * child, or across siblings, rotated for horizontal layouts. Returns
 * undefined for keys that are not navigation keys; stays put at edges.
 */
export function nextGraphFocus(model: GraphModel, current: string | undefined, key: string, orientation: Orientation): string | undefined {
  const vertical = orientation === 'vertical';
  const keys = {
    parent: vertical ? 'ArrowUp' : 'ArrowLeft',
    child: vertical ? 'ArrowDown' : 'ArrowRight',
    previous: vertical ? 'ArrowLeft' : 'ArrowUp',
    next: vertical ? 'ArrowRight' : 'ArrowDown',
  };
  if (!Object.values(keys).includes(key)) return undefined;
  if (current === undefined || !model.visuals.has(current)) return model.roots[0];
  const siblings = siblingsOf(model, current);
  const index = siblings.indexOf(current);
  switch (key) {
    case keys.parent:
      return model.parentOf.get(current) ?? current;
    case keys.child:
      return model.children.get(current)?.[0] ?? current;
    case keys.previous:
      return siblings[index - 1] ?? current;
    default:
      return siblings[index + 1] ?? current;
  }
}
```

- [ ] **Step 4: Run and commit**

```bash
npm test && npm run typecheck && npm run lint && npm run build
cd ~/ha-unifi-insights-card
git add frontend custom_components/unifi_insights/frontend/topology-card.js
git commit -m "feat(frontend): topology graph model, layout and navigation

Pure functions shared by both views: the contract becomes a tree with
filtered kinds re-attached to their nearest visible ancestor, clients
grouped per device, and malformed input (unknown ids, client parents,
cycles) turned into extra roots instead of errors. Layout is a d3
tidy tree over a synthetic super-root so orphan devices stay visible.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---
### Task 6: Shared view helpers, list view, detail panel

**Files:**
- Create: `frontend/src/views/describe.ts`, `frontend/src/icons.ts`, `frontend/src/styles.ts`, `frontend/src/views/list-view.ts`, `frontend/src/views/detail-panel.ts`
- Modify: `frontend/test/helpers.ts` (append `mount`, `cleanup`, `fixtureModel`)
- Test: `frontend/test/describe.test.ts`, `frontend/test/list-view.test.ts`, `frontend/test/detail-panel.test.ts`

**Interfaces:**
- Consumes: Task 3 (`contract`, `localize`, `ha-types.fireEvent/navigate`, `define.defineOnce`), Task 5 (`GraphModel`, `Visual`, `GroupVisual`, `ROOT_CLIENT_GROUP`, `UNCONNECTED_GROUP`, `buildModel`).
- Produces:
  - `views/describe.ts`: `KIND_KEYS`, `STATE_KEYS`, `MEDIUM_KEYS`, `truncate(text, max)`, `formatSpeed(mbps)`, `formatSpeedLong(mbps)`, `linkLabel(edge?)`, `visualTitle(visual, localize)`, `visualState(visual)`, `describeVisual(model, visual, localize)`.
  - `icons.ts`: `iconFor(node)`, `GROUP_ICON`, `iconTemplate(path)`, re-exported `mdiChevronDown mdiChevronRight mdiClose mdiFitToScreenOutline mdiMagnifyMinusOutline mdiMagnifyPlusOutline mdiOpenInNew`.
  - `styles.ts`: `themeTokens`, `controlStyles` (Lit `CSSResult`s).
  - `<uit-list-view>` properties `model`, `selectedId`, `localize`, `siteName`; exported pure `listRows(model, collapsed, query): ListRow[]` and `interface ListRow { id; visual; level; posinset; setsize; hasChildren; expanded; parentId? }`.
  - `<uit-detail-panel>` properties `model`, `selectedId`, `localize`, `narrow` (reflected attribute).
  - Events (all `bubbles`+`composed`, fired with `fireEvent`): `uit-activate` `{ id }` (select, or toggle+select for groups), `uit-toggle-group` `{ id }`, `uit-select` `{ id }` (raw id, may be a collapsed client), `uit-close`.
  - `test/helpers.ts`: `mount(tag, props)`, `cleanup()`, `fixtureModel(overrides?)`.

- [ ] **Step 1: Extend the test helpers**

Append to `frontend/test/helpers.ts`:
```ts
import { NODE_KINDS as ALL_KINDS } from '../src/contract';
import { buildModel, type GraphModel, type UiState } from '../src/model/graph-model';

export function fixtureModel(ui: Partial<UiState> = {}, snapshot: SiteTopology = fixtureSnapshot()): GraphModel {
  return buildModel(snapshot, { kinds: new Set(ALL_KINDS), clients: 'collapsed', toggledGroups: new Set(), ...ui });
}

export async function mount<T extends HTMLElement>(tag: string, props: Record<string, unknown> = {}): Promise<T> {
  const el = document.createElement(tag) as T & { updateComplete: Promise<boolean> };
  Object.assign(el, props);
  document.body.append(el);
  await el.updateComplete;
  return el;
}

export function cleanup(): void {
  document.body.replaceChildren();
  history.replaceState(null, '', '/');
}
```

- [ ] **Step 2: Write the failing tests**

`frontend/test/describe.test.ts`:
```ts
import { expect, it } from 'vitest';
import { makeLocalize } from '../src/localize';
import { describeVisual, formatSpeed, formatSpeedLong, linkLabel, truncate, visualTitle } from '../src/views/describe';
import { fixtureModel } from './helpers';

const localize = makeLocalize('en');

it('formats link speeds', () => {
  expect([formatSpeed(10000), formatSpeed(2500), formatSpeed(100)]).toEqual(['10G', '2.5G', '100M']);
  expect([formatSpeedLong(10000), formatSpeedLong(100)]).toEqual(['10 gigabit', '100 megabit']);
});

it('labels links with port, speed and PoE', () => {
  expect(linkLabel({ source: 'a', target: 'b', medium: 'wired', parent_port: 20, speed_mbps: 2500, poe_power_w: 12.3 })).toBe('p20 · 2.5G · PoE');
  expect(linkLabel(undefined)).toBe('');
});

it('truncates by characters with an ellipsis', () => {
  expect(truncate('short', 22)).toBe('short');
  expect(truncate('a'.repeat(30), 22)).toBe(`${'a'.repeat(21)}…`);
});

it('describes nodes and groups for screen readers', () => {
  const model = fixtureModel();
  expect(describeVisual(model, model.visuals.get('dev:uuid-core')!, localize)).toBe('Switch Core 24, online, uplink port 11 at 10 gigabit');
  expect(describeVisual(model, model.visuals.get('dev:uuid-u1')!, localize)).toBe('Switch Ultra A, online, 1 client, uplink port 6 at 1 gigabit');
  expect(describeVisual(model, model.visuals.get('group:dev:uuid-ap')!, localize)).toBe('1 client: 1 wireless, 0 offline');
  expect(visualTitle(model.visuals.get('group:dev:uuid-ap')!, localize)).toBe('1 client');
});
```

`frontend/test/list-view.test.ts`:
```ts
import { afterEach, describe, expect, it, vi } from 'vitest';
import { makeLocalize } from '../src/localize';
import { listRows, type UitListView } from '../src/views/list-view';
import { cleanup, fixtureModel, fixtureSnapshot, mount } from './helpers';

const localize = makeLocalize('en');
afterEach(cleanup);

const rowsOf = (el: UitListView) => [...el.shadowRoot!.querySelectorAll<HTMLElement>('[role="treeitem"]')];
const key = (el: UitListView, k: string) =>
  el.shadowRoot!.querySelector('[role="tree"]')!.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true }));

describe('listRows', () => {
  const model = fixtureModel();

  it('flattens the tree depth-first with ARIA positions', () => {
    const rows = listRows(model, new Set(), '');
    expect(rows.map((r) => `${r.level}:${r.id}`)).toEqual([
      '1:dev:uuid-gw', '2:dev:uuid-core', '3:dev:uuid-flex', '3:dev:uuid-lite', '3:dev:uuid-pdu',
      '3:dev:uuid-u1', '4:group:dev:uuid-u1', '3:dev:uuid-u2', '3:dev:uuid-ap', '4:group:dev:uuid-ap',
    ]);
    expect(rows[2]).toMatchObject({ posinset: 1, setsize: 6, hasChildren: false, parentId: 'dev:uuid-core' });
    expect(rows[6]).toMatchObject({ hasChildren: true, expanded: false });
  });

  it('hides the descendants of collapsed devices', () => {
    expect(listRows(model, new Set(['dev:uuid-core']), '').map((r) => r.id)).toEqual(['dev:uuid-gw', 'dev:uuid-core']);
  });

  it('filters to matches and their ancestors, searching inside collapsed groups', () => {
    expect(listRows(model, new Set(['dev:uuid-core']), 'tv').map((r) => r.id)).toEqual([
      'dev:uuid-gw', 'dev:uuid-core', 'dev:uuid-u1', 'group:dev:uuid-u1',
    ]);
  });
});

describe('<uit-list-view>', () => {
  const props = () => ({ model: fixtureModel(), localize, siteName: 'Home' });

  it('renders an ARIA tree with one tab stop', async () => {
    const el = await mount<UitListView>('uit-list-view', props());
    const rows = rowsOf(el);
    expect(el.shadowRoot!.querySelector('[role="tree"]')!.getAttribute('aria-label')).toBe('Home devices and clients');
    expect(rows).toHaveLength(10);
    expect(rows.filter((r) => r.tabIndex === 0)).toHaveLength(1);
    expect(rows[1]!.getAttribute('aria-level')).toBe('2');
    expect(rows[1]!.getAttribute('aria-expanded')).toBe('true');
    expect(rows[2]!.hasAttribute('aria-expanded')).toBe(false);
  });

  it('moves focus with arrows, Home/End and type-ahead', async () => {
    const el = await mount<UitListView>('uit-list-view', props());
    rowsOf(el)[0]!.focus();
    key(el, 'ArrowDown');
    await el.updateComplete;
    expect(el.shadowRoot!.activeElement?.getAttribute('data-id')).toBe('dev:uuid-core');
    key(el, 'End');
    await el.updateComplete;
    expect(el.shadowRoot!.activeElement?.getAttribute('data-id')).toBe('group:dev:uuid-ap');
    key(el, 'Home');
    key(el, 'l');
    await el.updateComplete;
    expect(el.shadowRoot!.activeElement?.getAttribute('data-id')).toBe('dev:uuid-lite');
  });

  it('collapses and expands devices, and asks the card to toggle groups', async () => {
    const el = await mount<UitListView>('uit-list-view', props());
    const toggles = vi.fn();
    el.addEventListener('uit-toggle-group', (e) => toggles((e as CustomEvent).detail));
    rowsOf(el)[1]!.focus();
    key(el, 'ArrowLeft');
    await el.updateComplete;
    expect(rowsOf(el)).toHaveLength(2);
    key(el, 'ArrowRight');
    await el.updateComplete;
    expect(rowsOf(el)).toHaveLength(10);
    rowsOf(el)[6]!.focus();
    key(el, 'ArrowRight');
    expect(toggles).toHaveBeenCalledWith({ id: 'group:dev:uuid-u1' });
  });

  it('activates rows with Enter and click', async () => {
    const el = await mount<UitListView>('uit-list-view', props());
    const activate = vi.fn();
    el.addEventListener('uit-activate', (e) => activate((e as CustomEvent).detail));
    rowsOf(el)[0]!.focus();
    key(el, 'Enter');
    rowsOf(el)[3]!.click();
    expect(activate.mock.calls).toEqual([[{ id: 'dev:uuid-gw' }], [{ id: 'dev:uuid-lite' }]]);
  });

  it('keeps the search box focused while filtering', async () => {
    const el = await mount<UitListView>('uit-list-view', props());
    const input = el.shadowRoot!.querySelector('input')!;
    input.focus();
    input.value = 'ultra';
    input.dispatchEvent(new Event('input'));
    await el.updateComplete;
    expect(el.shadowRoot!.activeElement).toBe(input);
    expect(rowsOf(el).map((r) => r.dataset.id)).toEqual(['dev:uuid-gw', 'dev:uuid-core', 'dev:uuid-u1', 'dev:uuid-u2']);
    input.value = 'zzz';
    input.dispatchEvent(new Event('input'));
    await el.updateComplete;
    expect(el.shadowRoot!.textContent).toContain('No matches');
  });

  it('renders hostile and long names as text', async () => {
    const hostile = '<img src=x onerror=alert(1)>';
    const long = 'x'.repeat(80);
    const snapshot = fixtureSnapshot();
    snapshot.nodes.find((n) => n.id === 'dev:uuid-gw')!.name = hostile;
    snapshot.nodes.find((n) => n.id === 'dev:uuid-core')!.name = long;
    const el = await mount<UitListView>('uit-list-view', { ...props(), model: fixtureModel({}, snapshot) });
    const names = [...el.shadowRoot!.querySelectorAll<HTMLElement>('.name')];
    expect(el.shadowRoot!.querySelector('img')).toBeNull();
    expect(names[0]!.textContent).toBe(hostile);
    expect(names[1]!.title).toBe(long);
  });
});
```

`frontend/test/detail-panel.test.ts`:
```ts
import { afterEach, expect, it, vi } from 'vitest';
import { makeLocalize } from '../src/localize';
import type { UitDetailPanel } from '../src/views/detail-panel';
import '../src/views/detail-panel';
import { cleanup, fixtureModel, mount } from './helpers';

const localize = makeLocalize('en');
afterEach(cleanup);

const panel = (selectedId: string | undefined) =>
  mount<UitDetailPanel>('uit-detail-panel', { model: fixtureModel(), localize, selectedId });
const rows = (el: UitDetailPanel) =>
  Object.fromEntries([...el.shadowRoot!.querySelectorAll('.row')].map((r) => [r.querySelector('dt')!.textContent, r.querySelector('dd')!.textContent]));

it('shows a device with its uplink and an Open device link', async () => {
  const el = await panel('dev:uuid-core');
  expect(el.shadowRoot!.querySelector('h3')!.textContent).toBe('Core 24');
  expect(rows(el)).toMatchObject({ Type: 'Switch', Model: 'USW Pro Max 24', State: 'Online', 'Connected to': 'Gateway', Port: '11 → 26', Speed: '10G', Link: 'Wired' });
  el.shadowRoot!.querySelector<HTMLButtonElement>('button.action')!.click();
  expect(location.pathname).toBe('/config/devices/device/reg-core');
});

it('shows PoE draw on a powered link', async () => {
  expect(rows(await panel('dev:uuid-ap'))).toMatchObject({ PoE: '12.3 W' });
});

it('shows a client hidden inside a collapsed group', async () => {
  const el = await panel('cli:cli-tv');
  expect(rows(el)).toMatchObject({ Connection: 'Wired', VLAN: '3', Network: 'Media', 'Connected to': 'Ultra A', Port: '4' });
  expect(el.shadowRoot!.querySelector('button.action')).toBeNull();
});

it('lists and searches group members, selecting one on click', async () => {
  const el = await panel('group:dev:uuid-u1');
  const selected = vi.fn();
  el.addEventListener('uit-select', (e) => selected((e as CustomEvent).detail));
  el.shadowRoot!.querySelector<HTMLButtonElement>('button.member')!.click();
  expect(selected).toHaveBeenCalledWith({ id: 'cli:cli-tv' });
  const search = el.shadowRoot!.querySelector<HTMLInputElement>('input')!;
  search.value = 'zzz';
  search.dispatchEvent(new Event('input'));
  await el.updateComplete;
  expect(el.shadowRoot!.querySelectorAll('button.member')).toHaveLength(0);
});

it('closes on request and renders nothing without a selection', async () => {
  const el = await panel('dev:uuid-gw');
  const closed = vi.fn();
  el.addEventListener('uit-close', closed);
  el.shadowRoot!.querySelector<HTMLButtonElement>('button.close')!.click();
  expect(closed).toHaveBeenCalledOnce();
  const empty = await panel('dev:gone');
  expect(empty.shadowRoot!.querySelector('section')).toBeNull();
});
```

Run: `npm test -- describe list-view detail-panel` → FAIL (modules not found).

- [ ] **Step 3: Implement `views/describe.ts`, `icons.ts`, `styles.ts`**

`frontend/src/views/describe.ts`:
```ts
import type { LinkMedium, NodeKind, NodeState, TopologyEdge } from '../contract';
import type { LocalizeFunc, LocalizeKey } from '../localize';
import { ROOT_CLIENT_GROUP, UNCONNECTED_GROUP, type GraphModel, type Visual } from '../model/graph-model';

export const KIND_KEYS: Record<NodeKind, LocalizeKey> = {
  gateway: 'kind.gateway', switch: 'kind.switch', access_point: 'kind.access_point', client: 'kind.client', other: 'kind.other',
};
export const STATE_KEYS: Record<NodeState, LocalizeKey> = { online: 'state.online', offline: 'state.offline', unknown: 'state.unknown' };
export const MEDIUM_KEYS: Record<LinkMedium, LocalizeKey> = { wired: 'medium.wired', wireless: 'medium.wireless', unknown: 'medium.unknown' };

/** Shorten to `max` characters (not UTF-16 units) with an ellipsis. */
export function truncate(text: string, max: number): string {
  const chars = [...text];
  return chars.length > max ? `${chars.slice(0, max - 1).join('')}…` : text;
}

const trim = (n: number): string => (Number.isInteger(n) ? String(n) : n.toFixed(1));

export function formatSpeed(mbps: number): string {
  return mbps >= 1000 ? `${trim(mbps / 1000)}G` : `${mbps}M`;
}

export function formatSpeedLong(mbps: number): string {
  return mbps >= 1000 ? `${trim(mbps / 1000)} gigabit` : `${mbps} megabit`;
}

/** Short on-canvas link label, e.g. "p11 · 10G · PoE". */
export function linkLabel(edge: TopologyEdge | undefined): string {
  if (!edge) return '';
  const parts: string[] = [];
  if (edge.parent_port !== undefined) parts.push(`p${edge.parent_port}`);
  if (edge.speed_mbps) parts.push(formatSpeed(edge.speed_mbps));
  if (edge.poe_power_w !== undefined) parts.push('PoE');
  return parts.join(' · ');
}

export function visualTitle(visual: Visual, localize: LocalizeFunc): string {
  if (visual.type !== 'group') return visual.node.name;
  if (visual.id === UNCONNECTED_GROUP) return localize('group.unconnected');
  if (visual.id === ROOT_CLIENT_GROUP) return localize('group.root');
  return visual.counts.total === 1 ? localize('group.client_one') : localize('group.clients', { count: visual.counts.total });
}

/** A group reads as offline only when every member is offline. */
export function visualState(visual: Visual): NodeState {
  if (visual.type !== 'group') return visual.node.state;
  return visual.counts.offline === visual.counts.total ? 'offline' : 'online';
}

/** Full spoken label: kind, name, state, client count, uplink. */
export function describeVisual(model: GraphModel, visual: Visual, localize: LocalizeFunc): string {
  if (visual.type === 'group') {
    return `${visualTitle(visual, localize)}: ${localize('group.summary', { wireless: visual.counts.wireless, offline: visual.counts.offline })}`;
  }
  const n = visual.node;
  const parts = [
    localize('node.label', { kind: localize(KIND_KEYS[n.kind]), name: n.name, state: localize(STATE_KEYS[n.state]).toLocaleLowerCase() }),
  ];
  const clients = model.clientCounts.get(n.id)?.total ?? 0;
  if (clients > 0) parts.push(clients === 1 ? localize('node.client_one') : localize('node.clients', { count: clients }));
  const edge = model.edges.get(n.id);
  if (edge?.parent_port !== undefined) {
    parts.push(
      edge.speed_mbps
        ? localize('node.uplink_speed', { port: edge.parent_port, speed: formatSpeedLong(edge.speed_mbps) })
        : localize('node.uplink', { port: edge.parent_port }),
    );
  } else if (n.connection) {
    parts.push(localize(MEDIUM_KEYS[n.connection]).toLocaleLowerCase());
  }
  return parts.join(', ');
}
```

`frontend/src/icons.ts`:
```ts
import { mdiAccessPoint, mdiDevices, mdiLanConnect, mdiRouterNetwork, mdiSwitch, mdiWifi } from '@mdi/js';
import { html, type TemplateResult } from 'lit';
import type { TopologyNode } from './contract';

export {
  mdiChevronDown, mdiChevronRight, mdiClose, mdiFitToScreenOutline, mdiMagnifyMinusOutline,
  mdiMagnifyPlusOutline, mdiOpenInNew,
} from '@mdi/js';

export const GROUP_ICON = mdiDevices;

export function iconFor(node: TopologyNode): string {
  switch (node.kind) {
    case 'gateway':
      return mdiRouterNetwork;
    case 'switch':
      return mdiSwitch;
    case 'access_point':
      return mdiAccessPoint;
    case 'client':
      return node.connection === 'wireless' ? mdiWifi : mdiLanConnect;
    default:
      return mdiDevices;
  }
}

/** Decorative inline icon for HTML contexts; the surrounding control carries the label. */
export function iconTemplate(path: string): TemplateResult {
  return html`<svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d=${path}></path></svg>`;
}
```

`frontend/src/styles.ts`:
```ts
import { css } from 'lit';

/** State and focus colours from the HA theme (fallbacks are HA's own defaults). */
export const themeTokens = css`
  :host {
    --uit-online: var(--success-color, #43a047);
    --uit-offline: var(--error-color, #db4437);
    --uit-warning: var(--warning-color, #ffa600);
    --uit-unknown: var(--disabled-text-color, #bdbdbd);
    --uit-focus: var(--primary-color, #03a9f4);
    --uit-line: var(--divider-color, rgba(0, 0, 0, 0.12));
    color: var(--primary-text-color);
    font-family: var(--ha-font-family-body, var(--paper-font-body1_-_font-family, sans-serif));
  }
  @media (forced-colors: active) {
    :host {
      --uit-online: CanvasText;
      --uit-offline: CanvasText;
      --uit-warning: CanvasText;
      --uit-unknown: GrayText;
      --uit-focus: Highlight;
    }
  }
`;

/** Native controls styled to sit in an HA card, with ≥ 44 px targets and visible focus. */
export const controlStyles = css`
  button {
    font: inherit;
    color: var(--primary-text-color);
    background: none;
    border: 1px solid var(--uit-line);
    border-radius: 18px;
    min-height: 44px;
    min-width: 44px;
    padding: 0 14px;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  button[aria-pressed='true'] {
    background: var(--primary-color);
    border-color: var(--primary-color);
    color: var(--text-primary-color, #fff);
  }
  input,
  select {
    font: inherit;
    color: var(--primary-text-color);
    background: var(--card-background-color);
    border: 1px solid var(--uit-line);
    border-radius: 8px;
    min-height: 44px;
    padding: 0 12px;
    box-sizing: border-box;
  }
  :focus-visible {
    outline: 2px solid var(--uit-focus);
    outline-offset: 2px;
  }
  .icon {
    width: 20px;
    height: 20px;
    fill: currentColor;
    flex: none;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }
  @media (prefers-reduced-motion: reduce) {
    * {
      transition: none !important;
      animation: none !important;
    }
  }
`;
```

- [ ] **Step 4: Implement `views/list-view.ts`**

```ts
import { LitElement, css, html, nothing, type TemplateResult } from 'lit';
import { repeat } from 'lit/directives/repeat.js';
import { defineOnce } from '../define';
import { fireEvent } from '../ha-types';
import { GROUP_ICON, iconFor, iconTemplate, mdiChevronDown, mdiChevronRight } from '../icons';
import type { LocalizeFunc } from '../localize';
import type { GraphModel, Visual } from '../model/graph-model';
import { controlStyles, themeTokens } from '../styles';
import { STATE_KEYS, describeVisual, visualState, visualTitle } from './describe';

export interface ListRow {
  id: string;
  visual: Visual;
  level: number;
  posinset: number;
  setsize: number;
  hasChildren: boolean;
  expanded: boolean;
  parentId?: string | undefined;
}

function matches(visual: Visual, query: string): boolean {
  if (visual.type === 'group') return visual.members.some((m) => m.name.toLowerCase().includes(query));
  return visual.node.name.toLowerCase().includes(query);
}

/** Visible rows of the ARIA tree: depth-first, filtered to search matches plus their ancestors. */
export function listRows(model: GraphModel, collapsed: ReadonlySet<string>, query: string): ListRow[] {
  const q = query.trim().toLowerCase();
  let keep: Set<string> | undefined;
  if (q) {
    keep = new Set();
    for (const [id, visual] of model.visuals) {
      if (!matches(visual, q)) continue;
      for (let cur: string | undefined = id; cur !== undefined && !keep.has(cur); cur = model.parentOf.get(cur)) keep.add(cur);
    }
  }
  const rows: ListRow[] = [];
  const walk = (ids: readonly string[], level: number, parentId: string | undefined): void => {
    const shown = keep ? ids.filter((id) => keep.has(id)) : ids;
    shown.forEach((id, index) => {
      const visual = model.visuals.get(id)!;
      const kids = model.children.get(id) ?? [];
      const isGroup = visual.type === 'group';
      const hasChildren = isGroup || kids.length > 0;
      const open = isGroup ? visual.expanded : q !== '' || !collapsed.has(id);
      rows.push({ id, visual, level, posinset: index + 1, setsize: shown.length, hasChildren, expanded: hasChildren && open, parentId });
      if (open && kids.length > 0) walk(kids, level + 1, id);
    });
  };
  walk(model.roots, 1, undefined);
  return rows;
}

/** Accessible tree view of the same model the graph draws. */
export class UitListView extends LitElement {
  static override properties = {
    model: { attribute: false },
    selectedId: { attribute: false },
    localize: { attribute: false },
    siteName: { attribute: false },
    query: { state: true },
    collapsed: { state: true },
    focusId: { state: true },
  };

  declare model?: GraphModel;
  declare selectedId?: string;
  declare localize?: LocalizeFunc;
  declare siteName: string;
  declare query: string;
  declare collapsed: ReadonlySet<string>;
  declare focusId?: string;

  private rows: ListRow[] = [];
  private typeahead = '';
  private typeaheadTimer: ReturnType<typeof setTimeout> | undefined;

  constructor() {
    super();
    this.siteName = '';
    this.query = '';
    this.collapsed = new Set();
  }

  protected override willUpdate(): void {
    if (!this.model) return;
    this.rows = listRows(this.model, this.collapsed, this.query);
    if (!this.rows.some((r) => r.id === this.focusId)) this.focusId = this.rows[0]?.id;
  }

  protected override render(): TemplateResult | typeof nothing {
    const { model, localize } = this;
    if (!model || !localize) return nothing;
    return html`
      <div class="search">
        <input
          type="search"
          .value=${this.query}
          placeholder=${localize('list.search')}
          aria-label=${localize('list.search')}
          @input=${(e: Event) => {
            this.query = (e.target as HTMLInputElement).value;
          }}
        />
      </div>
      ${this.rows.length === 0
        ? html`<p class="empty">${localize('list.no_matches')}</p>`
        : html`<div class="tree" role="tree" aria-label=${localize('list.label', { site: this.siteName })} @keydown=${this.onKeydown}>
            ${repeat(this.rows, (r) => r.id, (r) => this.renderRow(model, r, localize))}
          </div>`}
    `;
  }

  private renderRow(model: GraphModel, row: ListRow, localize: LocalizeFunc): TemplateResult {
    const visual = row.visual;
    const title = visualTitle(visual, localize);
    const state = visualState(visual);
    return html`<div
      class="row ${state} ${row.id === this.selectedId ? 'selected' : ''}"
      role="treeitem"
      data-id=${row.id}
      aria-level=${row.level}
      aria-setsize=${row.setsize}
      aria-posinset=${row.posinset}
      aria-selected=${String(row.id === this.selectedId)}
      aria-expanded=${row.hasChildren ? String(row.expanded) : nothing}
      aria-label=${describeVisual(model, visual, localize)}
      tabindex=${row.id === this.focusId ? 0 : -1}
      style=${`--level: ${row.level}`}
      @click=${() => fireEvent(this, 'uit-activate', { id: row.id })}
      @focus=${() => {
        this.focusId = row.id;
      }}
    >
      <span
        class="chevron"
        aria-hidden="true"
        @click=${(e: Event) => {
          e.stopPropagation();
          if (row.hasChildren) this.toggle(row);
        }}
        >${row.hasChildren ? iconTemplate(row.expanded ? mdiChevronDown : mdiChevronRight) : nothing}</span
      >
      ${iconTemplate(visual.type === 'group' ? GROUP_ICON : iconFor(visual.node))}
      <span class="name" title=${title}>${title}</span>
      ${visual.type === 'group'
        ? html`<span class="count">${visual.counts.total}</span>`
        : html`<span class="dot" aria-hidden="true"></span>${state === 'online'
              ? nothing
              : html`<span class="state-text">${localize(STATE_KEYS[state])}</span>`}`}
    </div>`;
  }

  private toggle(row: ListRow): void {
    if (row.visual.type === 'group') {
      fireEvent(this, 'uit-toggle-group', { id: row.id });
      return;
    }
    const next = new Set(this.collapsed);
    if (next.has(row.id)) next.delete(row.id);
    else next.add(row.id);
    this.collapsed = next;
  }

  private onKeydown(e: KeyboardEvent): void {
    const rows = this.rows;
    const index = rows.findIndex((r) => r.id === this.focusId);
    const row = rows[index];
    if (!row) return;
    let target: string | undefined;
    switch (e.key) {
      case 'ArrowDown':
        target = rows[index + 1]?.id;
        break;
      case 'ArrowUp':
        target = rows[index - 1]?.id;
        break;
      case 'Home':
        target = rows[0]?.id;
        break;
      case 'End':
        target = rows.at(-1)?.id;
        break;
      case 'ArrowRight':
        if (row.hasChildren && !row.expanded) this.toggle(row);
        else if (row.expanded) target = rows[index + 1]?.id;
        break;
      case 'ArrowLeft':
        if (row.expanded) this.toggle(row);
        else target = row.parentId;
        break;
      case 'Enter':
      case ' ':
        fireEvent(this, 'uit-activate', { id: row.id });
        break;
      default:
        if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
          e.preventDefault();
          this.typeAhead(e.key, index);
        }
        return;
    }
    e.preventDefault();
    if (target !== undefined) void this.focusRow(target);
  }

  private typeAhead(char: string, from: number): void {
    this.typeahead += char.toLowerCase();
    if (this.typeaheadTimer !== undefined) clearTimeout(this.typeaheadTimer);
    this.typeaheadTimer = setTimeout(() => {
      this.typeahead = '';
    }, 500);
    const rows = this.rows;
    for (let step = 1; step <= rows.length; step++) {
      const row = rows[(from + step) % rows.length]!;
      if (visualTitle(row.visual, this.localize!).toLowerCase().startsWith(this.typeahead)) {
        void this.focusRow(row.id);
        return;
      }
    }
  }

  private async focusRow(id: string): Promise<void> {
    this.focusId = id;
    await this.updateComplete;
    const rows = this.renderRoot.querySelectorAll<HTMLElement>('[role="treeitem"]');
    for (const el of rows) if (el.getAttribute('data-id') === id) el.focus();
  }

  static override styles = [
    themeTokens,
    controlStyles,
    css`
      :host {
        display: flex;
        flex-direction: column;
        flex: 1;
        min-height: 0;
        min-width: 0;
      }
      .search {
        padding: 8px 12px;
      }
      .search input {
        width: 100%;
      }
      .tree {
        overflow: auto;
        flex: 1;
        padding: 0 4px 8px;
      }
      .row {
        display: flex;
        align-items: center;
        gap: 8px;
        min-height: 44px;
        padding-inline-start: calc((var(--level) - 1) * 20px + 4px);
        padding-inline-end: 12px;
        border-radius: 8px;
        cursor: pointer;
      }
      .row.selected {
        background: color-mix(in srgb, var(--uit-focus) 16%, transparent);
      }
      .row.offline .icon,
      .row.offline .name {
        opacity: 0.55;
      }
      .chevron {
        width: 24px;
        display: inline-flex;
      }
      .name {
        flex: 1;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .dot {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: var(--uit-online);
        flex: none;
      }
      .offline .dot {
        background: var(--uit-offline);
      }
      .unknown .dot {
        background: var(--uit-unknown);
      }
      .state-text {
        color: var(--uit-offline);
        font-weight: 600;
        font-size: 0.85em;
      }
      .count {
        color: var(--secondary-text-color);
      }
      .empty {
        padding: 16px;
        color: var(--secondary-text-color);
      }
    `,
  ];
}

defineOnce('uit-list-view', UitListView);

declare global {
  interface HTMLElementTagNameMap {
    'uit-list-view': UitListView;
  }
}
```

- [ ] **Step 5: Implement `views/detail-panel.ts`**

```ts
import { LitElement, css, html, nothing, type PropertyValues, type TemplateResult } from 'lit';
import type { TopologyNode } from '../contract';
import { defineOnce } from '../define';
import { fireEvent, navigate } from '../ha-types';
import { iconFor, iconTemplate, mdiClose, mdiOpenInNew } from '../icons';
import type { LocalizeFunc, LocalizeKey } from '../localize';
import type { GraphModel, GroupVisual } from '../model/graph-model';
import { controlStyles, themeTokens } from '../styles';
import { KIND_KEYS, MEDIUM_KEYS, STATE_KEYS, formatSpeed, visualTitle } from './describe';

type Row = [LocalizeKey, string | undefined];

/** Details of the selected device, client or client group; a side panel, or a bottom sheet when narrow. */
export class UitDetailPanel extends LitElement {
  static override properties = {
    model: { attribute: false },
    selectedId: { attribute: false },
    localize: { attribute: false },
    narrow: { type: Boolean, reflect: true },
    memberQuery: { state: true },
  };

  declare model?: GraphModel;
  declare selectedId?: string;
  declare localize?: LocalizeFunc;
  declare narrow: boolean;
  declare memberQuery: string;

  constructor() {
    super();
    this.narrow = false;
    this.memberQuery = '';
  }

  protected override willUpdate(changed: PropertyValues<this>): void {
    if (changed.has('selectedId')) this.memberQuery = '';
  }

  protected override render(): TemplateResult | typeof nothing {
    const { model, selectedId, localize } = this;
    if (!model || !selectedId || !localize) return nothing;
    const visual = model.visuals.get(selectedId);
    if (visual?.type === 'group') return this.shell(visualTitle(visual, localize), this.groupBody(visual, localize));
    const node = model.nodes.get(selectedId);
    if (!node) return nothing;
    const body = node.kind === 'client' ? this.clientBody(model, node, localize) : this.deviceBody(model, node, localize);
    return this.shell(node.name, body);
  }

  private shell(title: string, body: TemplateResult): TemplateResult {
    const localize = this.localize!;
    return html`<section class="panel" role="region" aria-label=${title}>
      <header>
        <h3 title=${title}>${title}</h3>
        <button class="close" aria-label=${localize('detail.close')} title=${localize('detail.close')} @click=${() => fireEvent(this, 'uit-close')}>
          ${iconTemplate(mdiClose)}
        </button>
      </header>
      ${body}
    </section>`;
  }

  private rows(rows: Row[]): TemplateResult {
    const shown = rows.filter((r): r is [LocalizeKey, string] => r[1] !== undefined && r[1] !== '');
    return html`<dl>
      ${shown.map(([key, value]) => html`<div class="row"><dt>${this.localize!(key)}</dt><dd>${value}</dd></div>`)}
    </dl>`;
  }

  private uplinkRows(model: GraphModel, id: string, localize: LocalizeFunc, withMedium: boolean): Row[] {
    const parentId = model.realParent.get(id);
    const edge = model.edges.get(id);
    let port: string | undefined;
    if (edge?.parent_port !== undefined) {
      port = edge.child_port === undefined ? String(edge.parent_port) : `${edge.parent_port} → ${edge.child_port}`;
    }
    return [
      ['detail.parent', parentId === undefined ? undefined : model.nodes.get(parentId)?.name],
      ['detail.port', port],
      ['detail.speed', edge?.speed_mbps ? formatSpeed(edge.speed_mbps) : undefined],
      ['detail.medium', withMedium && edge ? localize(MEDIUM_KEYS[edge.medium]) : undefined],
      ['detail.poe', edge?.poe_power_w === undefined ? undefined : `${edge.poe_power_w.toFixed(1)} W`],
    ];
  }

  private deviceBody(model: GraphModel, node: TopologyNode, localize: LocalizeFunc): TemplateResult {
    const counts = model.clientCounts.get(node.id);
    const hidden = model.links.get(node.id)?.viaHidden ?? [];
    return html`${this.rows([
        ['detail.kind', localize(KIND_KEYS[node.kind])],
        ['detail.model', node.model],
        ['detail.state', localize(STATE_KEYS[node.state])],
        ...this.uplinkRows(model, node.id, localize, true),
        ['detail.clients', counts ? localize('detail.clients_value', { total: counts.total, wired: counts.wired, wireless: counts.wireless }) : undefined],
        ['detail.via_hidden', hidden.length > 0 ? hidden.map((k) => localize(KIND_KEYS[k])).join(', ') : undefined],
      ])}
      ${node.ha_device_id
        ? html`<button class="action" @click=${() => navigate(`/config/devices/device/${encodeURIComponent(node.ha_device_id!)}`)}>
            ${iconTemplate(mdiOpenInNew)}${localize('detail.open_device')}
          </button>`
        : nothing}`;
  }

  private clientBody(model: GraphModel, node: TopologyNode, localize: LocalizeFunc): TemplateResult {
    return this.rows([
      ['detail.state', localize(STATE_KEYS[node.state])],
      ['detail.connection', node.connection ? localize(MEDIUM_KEYS[node.connection]) : undefined],
      ['detail.vlan', node.vlan_id === undefined ? undefined : String(node.vlan_id)],
      ['detail.network', node.network_name],
      ...this.uplinkRows(model, node.id, localize, false),
    ]);
  }

  private groupBody(group: GroupVisual, localize: LocalizeFunc): TemplateResult {
    const q = this.memberQuery.trim().toLowerCase();
    const members = q ? group.members.filter((m) => m.name.toLowerCase().includes(q)) : group.members;
    const c = group.counts;
    return html`${this.rows([['detail.clients', localize('detail.clients_value', { total: c.total, wired: c.wired, wireless: c.wireless })]])}
      <input
        type="search"
        .value=${this.memberQuery}
        placeholder=${localize('detail.search_members')}
        aria-label=${localize('detail.search_members')}
        @input=${(e: Event) => {
          this.memberQuery = (e.target as HTMLInputElement).value;
        }}
      />
      <ul class="members">
        ${members.map(
          (m) => html`<li>
            <button class="member ${m.state}" @click=${() => fireEvent(this, 'uit-select', { id: m.id })}>
              ${iconTemplate(iconFor(m))}<span class="name" title=${m.name}>${m.name}</span>
              ${m.state === 'online' ? nothing : html`<span class="state-text">${localize(STATE_KEYS[m.state])}</span>`}
            </button>
          </li>`,
        )}
      </ul>`;
  }

  static override styles = [
    themeTokens,
    controlStyles,
    css`
      :host {
        position: absolute;
        top: 8px;
        right: 8px;
        bottom: 8px;
        width: min(320px, 45%);
        z-index: 2;
        pointer-events: none;
      }
      :host([narrow]) {
        top: auto;
        left: 0;
        right: 0;
        bottom: 0;
        width: auto;
        max-height: 60%;
      }
      .panel {
        pointer-events: auto;
        box-sizing: border-box;
        height: 100%;
        overflow: auto;
        padding: 4px 16px 16px;
        background: var(--card-background-color);
        border: 1px solid var(--uit-line);
        border-radius: var(--ha-card-border-radius, 12px);
        box-shadow: var(--ha-card-box-shadow, none);
      }
      header {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      h3 {
        flex: 1;
        min-width: 0;
        margin: 0;
        font-size: 1.1em;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      button.close {
        border: none;
        padding: 0;
      }
      dl {
        margin: 8px 0;
      }
      .row {
        display: flex;
        gap: 12px;
        padding: 4px 0;
      }
      dt {
        color: var(--secondary-text-color);
        min-width: 7em;
      }
      dd {
        margin: 0;
        overflow-wrap: anywhere;
      }
      input {
        width: 100%;
      }
      .members {
        list-style: none;
        margin: 8px 0 0;
        padding: 0;
      }
      .member {
        width: 100%;
        border: none;
        border-radius: 8px;
        justify-content: flex-start;
      }
      .member .name {
        flex: 1;
        min-width: 0;
        text-align: start;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .member.offline .name {
        opacity: 0.55;
      }
      .state-text {
        color: var(--uit-offline);
        font-weight: 600;
      }
      .action {
        margin-top: 8px;
      }
    `,
  ];
}

defineOnce('uit-detail-panel', UitDetailPanel);

declare global {
  interface HTMLElementTagNameMap {
    'uit-detail-panel': UitDetailPanel;
  }
}
```

- [ ] **Step 6: Run and commit**

```bash
npm test && npm run typecheck && npm run lint && npm run build
cd ~/ha-unifi-insights-card
git add frontend custom_components/unifi_insights/frontend/topology-card.js
git commit -m "feat(frontend): list view and detail panel

The list view is the WAI-ARIA tree peer of the graph (arrow keys,
Home/End, type-ahead, search that never steals focus). The detail panel
shows uplink port, speed and PoE, client VLAN/network, a searchable
member list for client groups, and links to the HA device page. Names
render through Lit bindings only, so DHCP hostnames cannot inject markup.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---
### Task 7: Interactive graph view

**Files:**
- Create: `frontend/src/views/graph-view.ts`
- Test: `frontend/test/graph-view.test.ts`

**Interfaces:**
- Consumes: Task 5 (`GraphModel`, `Visual`, `VisualLink`, `groupContaining`, `layoutModel`, `fitTransform`, `visibleIds`, `CULL_THRESHOLD`, `nextGraphFocus`), Task 6 (`describe.ts`, `icons.ts`, `styles.ts`), `ha-types.fireEvent`, `define.defineOnce`.
- Produces: `<uit-graph-view>` with properties `model`, `density: Density`, `orientation: Orientation`, `showLabels: boolean`, `selectedId`, `localize`, `siteName`, `ctrlZoom: boolean`, `reducedMotion: boolean`; public methods `setViewportSize(width, height)`, `fit(animate = true)`, `zoomBy(factor)`, `focusNode(id): Promise<void>`; event `uit-activate` `{ id }`; exported pure `zoomFilter(event, ctrlZoom): 'zoom' | 'hint' | 'ignore'` and class `UitGraphView`.

- [ ] **Step 1: Write the failing tests**

`frontend/test/graph-view.test.ts`:
```ts
import { afterEach, describe, expect, it, vi } from 'vitest';
import { makeLocalize } from '../src/localize';
import { describeVisual } from '../src/views/describe';
import { zoomFilter, type UitGraphView } from '../src/views/graph-view';
import { cleanup, fixtureModel, fixtureSnapshot, mount } from './helpers';

const localize = makeLocalize('en');
afterEach(cleanup);

async function graph(props: Record<string, unknown> = {}): Promise<UitGraphView> {
  const el = await mount<UitGraphView>('uit-graph-view', {
    model: fixtureModel(), localize, siteName: 'Home', reducedMotion: true, ...props,
  });
  el.setViewportSize(800, 600);
  await el.updateComplete;
  return el;
}
const nodes = (el: UitGraphView) => [...el.shadowRoot!.querySelectorAll<SVGGElement>('g.nodes g.node')];
const byId = (el: UitGraphView, id: string) => nodes(el).find((n) => n.getAttribute('data-id') === id)!;
const svgOf = (el: UitGraphView) => el.shadowRoot!.querySelector('svg.canvas')!;

describe('<uit-graph-view> rendering', () => {
  it('draws every visual and link, labelled for assistive tech', async () => {
    const el = await graph();
    const model = fixtureModel();
    expect(nodes(el)).toHaveLength(model.visuals.size);
    expect(el.shadowRoot!.querySelectorAll('g.links path.link')).toHaveLength(model.links.size);
    const svg = svgOf(el);
    expect(svg.getAttribute('role')).toBe('application');
    expect(svg.getAttribute('aria-roledescription')).toBe('network topology');
    expect(svg.getAttribute('aria-label')).toBe('Home topology, 8 devices, 2 clients');
    expect(byId(el, 'dev:uuid-core').getAttribute('aria-label')).toBe(describeVisual(model, model.visuals.get('dev:uuid-core')!, localize));
    expect(byId(el, 'group:dev:uuid-ap').getAttribute('aria-expanded')).toBe('false');
    expect(nodes(el).filter((n) => n.getAttribute('tabindex') === '0').map((n) => n.getAttribute('data-id'))).toEqual(['dev:uuid-gw']);
  });

  it('labels links with port, speed and PoE, and can hide labels', async () => {
    const el = await graph();
    const labels = [...el.shadowRoot!.querySelectorAll('text.link-label')].map((t) => t.textContent);
    expect(labels).toContain('p20 · 2.5G · PoE');
    const bare = await graph({ showLabels: false });
    expect(bare.shadowRoot!.querySelector('text.label, text.link-label')).toBeNull();
  });

  it('renders hostile names as text', async () => {
    const snapshot = fixtureSnapshot();
    snapshot.nodes.find((n) => n.id === 'dev:uuid-gw')!.name = '<img src=x onerror=alert(1)> and a very long gateway name';
    const el = await graph({ model: fixtureModel({}, snapshot) });
    const gw = byId(el, 'dev:uuid-gw');
    expect(el.shadowRoot!.querySelector('img')).toBeNull();
    expect(gw.querySelector('title')!.textContent).toBe('<img src=x onerror=alert(1)> and a very long gateway name');
    expect(gw.querySelector('text.label')!.textContent).toMatch(/…$/);
  });

  it('highlights the path from the selection to the root, via a collapsed client group', async () => {
    const el = await graph({ selectedId: 'cli:cli-tv' });
    const onPath = nodes(el).filter((n) => n.classList.contains('on-path')).map((n) => n.getAttribute('data-id'));
    expect(onPath).toEqual(['dev:uuid-gw', 'dev:uuid-core', 'dev:uuid-u1', 'group:dev:uuid-u1']);
  });

  it('marks offline nodes with text, not colour alone', async () => {
    const snapshot = fixtureSnapshot();
    snapshot.nodes.find((n) => n.id === 'dev:uuid-pdu')!.state = 'offline';
    const el = await graph({ model: fixtureModel({}, snapshot) });
    expect(byId(el, 'dev:uuid-pdu').querySelector('text.state-text')!.textContent).toBe('Offline');
  });
});

describe('<uit-graph-view> interaction', () => {
  it('moves focus along the tree with arrows and activates with Enter or click', async () => {
    const el = await graph();
    const activated = vi.fn();
    el.addEventListener('uit-activate', (e) => activated((e as CustomEvent).detail));
    byId(el, 'dev:uuid-gw').focus();
    svgOf(el).dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    await el.updateComplete;
    await el.updateComplete;
    expect(el.shadowRoot!.activeElement?.getAttribute('data-id')).toBe('dev:uuid-core');
    svgOf(el).dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    byId(el, 'dev:uuid-ap').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(activated.mock.calls).toEqual([[{ id: 'dev:uuid-core' }], [{ id: 'dev:uuid-ap' }]]);
  });

  it('fits on first size and zooms with the keyboard', async () => {
    const el = await graph();
    const viewport = () => el.shadowRoot!.querySelector('g.viewport')!.getAttribute('transform');
    const fitted = viewport();
    expect(fitted).not.toBe('translate(0,0) scale(1)');
    svgOf(el).dispatchEvent(new KeyboardEvent('keydown', { key: '+', bubbles: true }));
    expect(viewport()).not.toBe(fitted);
    svgOf(el).dispatchEvent(new KeyboardEvent('keydown', { key: '0', bubbles: true }));
    expect(viewport()).toBe(fitted);
  });

  it('shows a hint instead of hijacking plain wheel scrolling in dashboards', async () => {
    const el = await graph();
    svgOf(el).dispatchEvent(new WheelEvent('wheel', { deltaY: 100, bubbles: true, cancelable: true }));
    await el.updateComplete;
    expect(el.shadowRoot!.querySelector('.hint')!.hasAttribute('hidden')).toBe(false);
  });

  it('decides which gestures zoom', () => {
    expect(zoomFilter(new WheelEvent('wheel'), true)).toBe('hint');
    expect(zoomFilter(new WheelEvent('wheel', { ctrlKey: true }), true)).toBe('zoom');
    expect(zoomFilter(new WheelEvent('wheel'), false)).toBe('zoom');
    expect(zoomFilter(new MouseEvent('mousedown', { button: 2 }), true)).toBe('ignore');
    expect(zoomFilter(new MouseEvent('mousedown'), true)).toBe('zoom');
  });
});

describe('<uit-graph-view> updates', () => {
  it('fades new nodes in and removed nodes out, unless motion is reduced', async () => {
    const el = await graph({ reducedMotion: false });
    el.model = fixtureModel({ toggledGroups: new Set(['group:dev:uuid-ap']) });
    await el.updateComplete;
    expect(byId(el, 'cli:cli-phone').classList.contains('enter')).toBe(true);
    el.model = fixtureModel();
    await el.updateComplete;
    expect(el.shadowRoot!.querySelectorAll('g.exits g.node')).toHaveLength(1);
    await new Promise((r) => setTimeout(r, 300));
    await el.updateComplete;
    expect(el.shadowRoot!.querySelectorAll('g.exits g.node')).toHaveLength(0);
  });

  it('keeps the view still when motion is reduced', async () => {
    const el = await graph();
    expect(svgOf(el).classList.contains('still')).toBe(true);
    el.model = fixtureModel({ clients: 'hidden' });
    await el.updateComplete;
    expect(el.shadowRoot!.querySelectorAll('g.exits g.node')).toHaveLength(0);
  });
});
```

Run: `npm test -- graph-view` → FAIL (module not found).

- [ ] **Step 2: Implement `views/graph-view.ts`**

```ts
import { select } from 'd3-selection';
import 'd3-transition';
import { zoom, zoomIdentity, type D3ZoomEvent, type ZoomBehavior, type ZoomTransform } from 'd3-zoom';
import { LitElement, css, html, nothing, svg, type PropertyValues, type SVGTemplateResult, type TemplateResult } from 'lit';
import { repeat } from 'lit/directives/repeat.js';
import type { Density, Orientation } from '../config';
import { defineOnce } from '../define';
import { fireEvent } from '../ha-types';
import { GROUP_ICON, iconFor } from '../icons';
import type { LocalizeFunc } from '../localize';
import { groupContaining, type GraphModel, type Visual, type VisualLink } from '../model/graph-model';
import { CULL_THRESHOLD, fitTransform, layoutModel, visibleIds, type Layout, type Point, type ViewTransform } from '../model/layout';
import { nextGraphFocus } from '../model/navigation';
import { themeTokens } from '../styles';
import { STATE_KEYS, describeVisual, linkLabel, truncate, visualState, visualTitle } from './describe';

const RADIUS: Record<Density, number> = { comfortable: 22, compact: 16 };
const EXIT_MS = 250;
const LABEL_CHARS = 22;

/**
 * d3-zoom gesture filter. In dashboard grids a plain wheel scrolls the page
 * (the card shows a hint instead); Ctrl/⌘+wheel and pinch still zoom. Panel
 * view passes ctrlZoom=false so the wheel zooms directly.
 */
export function zoomFilter(event: Event, ctrlZoom: boolean): 'zoom' | 'hint' | 'ignore' {
  if (event.type === 'wheel') {
    const wheel = event as WheelEvent;
    return ctrlZoom && !wheel.ctrlKey && !wheel.metaKey ? 'hint' : 'zoom';
  }
  const pointer = event as MouseEvent;
  return pointer.ctrlKey || (pointer.button ?? 0) !== 0 ? 'ignore' : 'zoom';
}

interface Ghost {
  point: Point;
  visual: Visual;
}

/** SVG tree of the model with pan/zoom, keyboard traversal and keyed incremental updates. */
export class UitGraphView extends LitElement {
  static override properties = {
    model: { attribute: false },
    density: { attribute: false },
    orientation: { attribute: false },
    showLabels: { attribute: false },
    selectedId: { attribute: false },
    localize: { attribute: false },
    siteName: { attribute: false },
    ctrlZoom: { attribute: false },
    reducedMotion: { attribute: false },
    focusId: { state: true },
    hintVisible: { state: true },
  };

  declare model?: GraphModel;
  declare density: Density;
  declare orientation: Orientation;
  declare showLabels: boolean;
  declare selectedId?: string;
  declare localize?: LocalizeFunc;
  declare siteName: string;
  declare ctrlZoom: boolean;
  declare reducedMotion: boolean;
  declare focusId?: string;
  declare hintVisible: boolean;

  private layout: Layout | undefined;
  private entering = new Set<string>();
  private exiting = new Map<string, Ghost>();
  private lastVisuals = new Map<string, Visual>();
  private exitTimer: ReturnType<typeof setTimeout> | undefined;
  private hintTimer: ReturnType<typeof setTimeout> | undefined;
  private transform: ViewTransform = { x: 0, y: 0, k: 1 };
  private width = 0;
  private height = 0;
  private fitted = false;
  private zoomBehavior: ZoomBehavior<SVGSVGElement, unknown> | undefined;
  private resizeObserver: ResizeObserver | undefined;

  constructor() {
    super();
    this.density = 'comfortable';
    this.orientation = 'vertical';
    this.showLabels = true;
    this.siteName = '';
    this.ctrlZoom = true;
    this.reducedMotion = false;
    this.hintVisible = false;
  }

  override connectedCallback(): void {
    super.connectedCallback();
    this.resizeObserver = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect;
      if (box) this.setViewportSize(box.width, box.height);
    });
    this.resizeObserver.observe(this);
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    this.resizeObserver?.disconnect();
    if (this.exitTimer !== undefined) clearTimeout(this.exitTimer);
    if (this.hintTimer !== undefined) clearTimeout(this.hintTimer);
    this.exitTimer = undefined;
    this.hintTimer = undefined;
  }

  /** Viewport size in CSS px; called by the ResizeObserver (and directly by tests). */
  setViewportSize(width: number, height: number): void {
    this.width = width;
    this.height = height;
    if (!this.fitted) this.tryInitialFit();
    else if (this.needsCulling) this.requestUpdate();
  }

  private get needsCulling(): boolean {
    return (this.layout?.positions.size ?? 0) > CULL_THRESHOLD;
  }

  private get svgEl(): SVGSVGElement | null {
    return this.renderRoot.querySelector<SVGSVGElement>('svg.canvas');
  }

  protected override willUpdate(changed: PropertyValues<this>): void {
    if (!this.model) return;
    if (changed.has('model') || changed.has('density') || changed.has('orientation')) {
      const next = layoutModel(this.model, this.density, this.orientation);
      const previous = this.layout;
      this.entering = new Set(previous ? [...next.positions.keys()].filter((id) => !previous.positions.has(id)) : []);
      for (const id of next.positions.keys()) this.exiting.delete(id);
      if (previous && !this.reducedMotion) {
        for (const [id, point] of previous.positions) {
          const visual = this.lastVisuals.get(id);
          if (!next.positions.has(id) && visual) this.exiting.set(id, { point, visual });
        }
        this.scheduleExitCleanup();
      }
      this.layout = next;
      this.lastVisuals = new Map(this.model.visuals);
      if (this.focusId === undefined || !this.model.visuals.has(this.focusId)) this.focusId = this.model.roots[0];
    }
  }

  protected override firstUpdated(): void {
    const svgEl = this.svgEl;
    if (!svgEl) return;
    this.zoomBehavior = zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .extent(() => [[0, 0], [Math.max(this.width, 1), Math.max(this.height, 1)]])
      .filter((event: Event) => {
        const decision = zoomFilter(event, this.ctrlZoom);
        if (decision === 'hint') this.flashHint();
        return decision === 'zoom';
      })
      .on('zoom', (event: D3ZoomEvent<SVGSVGElement, unknown>) => this.onZoom(event.transform))
      .on('end', () => {
        if (this.needsCulling) this.requestUpdate();
      });
    select(svgEl).call(this.zoomBehavior).on('dblclick.zoom', null);
    this.tryInitialFit();
  }

  protected override updated(): void {
    this.tryInitialFit();
  }

  private tryInitialFit(): void {
    if (this.fitted || !this.layout || !this.zoomBehavior || this.width <= 0 || this.height <= 0) return;
    this.fitted = true;
    this.fit(false);
  }

  private onZoom(t: ZoomTransform): void {
    this.transform = { x: t.x, y: t.y, k: t.k };
    // Written directly: a pan must not re-render hundreds of nodes.
    this.renderRoot.querySelector('g.viewport')?.setAttribute('transform', this.transformAttr());
  }

  private transformAttr(): string {
    const { x, y, k } = this.transform;
    return `translate(${x},${y}) scale(${k})`;
  }

  /** Fit the whole graph into the viewport. */
  fit(animate = true): void {
    const svgEl = this.svgEl;
    if (!this.layout || !this.zoomBehavior || !svgEl) return;
    const t = fitTransform(this.layout.bounds, this.width, this.height);
    const target = zoomIdentity.translate(t.x, t.y).scale(t.k);
    if (animate && !this.reducedMotion) this.zoomBehavior.transform(select(svgEl).transition().duration(300), target);
    else this.zoomBehavior.transform(select(svgEl), target);
  }

  zoomBy(factor: number): void {
    const svgEl = this.svgEl;
    if (!this.zoomBehavior || !svgEl) return;
    if (this.reducedMotion) this.zoomBehavior.scaleBy(select(svgEl), factor);
    else this.zoomBehavior.scaleBy(select(svgEl).transition().duration(200), factor);
  }

  /** Move keyboard focus to a node, panning it into view first if needed. */
  async focusNode(id: string): Promise<void> {
    this.focusId = id;
    await this.updateComplete;
    const p = this.layout?.positions.get(id);
    const svgEl = this.svgEl;
    if (p && svgEl && this.zoomBehavior && this.width > 0) {
      const sx = p.x * this.transform.k + this.transform.x;
      const sy = p.y * this.transform.k + this.transform.y;
      const margin = 40;
      if (sx < margin || sx > this.width - margin || sy < margin || sy > this.height - margin) {
        this.zoomBehavior.translateTo(select(svgEl), p.x, p.y);
        await this.updateComplete;
      }
    }
    for (const el of this.renderRoot.querySelectorAll<SVGGElement>('g.nodes g.node')) {
      if (el.getAttribute('data-id') === id) el.focus();
    }
  }

  private flashHint(): void {
    this.hintVisible = true;
    if (this.hintTimer !== undefined) clearTimeout(this.hintTimer);
    this.hintTimer = setTimeout(() => {
      this.hintVisible = false;
    }, 1500);
  }

  private scheduleExitCleanup(): void {
    if (this.exiting.size === 0 || this.exitTimer !== undefined) return;
    this.exitTimer = setTimeout(() => {
      this.exitTimer = undefined;
      this.exiting.clear();
      this.requestUpdate();
    }, EXIT_MS);
  }

  private highlightedPath(): Set<string> {
    const path = new Set<string>();
    const model = this.model;
    if (!model || this.selectedId === undefined) return path;
    let current: string | undefined = model.visuals.has(this.selectedId)
      ? this.selectedId
      : groupContaining(model, this.selectedId)?.id;
    while (current !== undefined) {
      path.add(current);
      current = model.parentOf.get(current);
    }
    return path;
  }

  private onKeydown(e: KeyboardEvent): void {
    const model = this.model;
    if (!model) return;
    const next = nextGraphFocus(model, this.focusId, e.key, this.orientation);
    if (next !== undefined) {
      e.preventDefault();
      void this.focusNode(next);
      return;
    }
    if ((e.key === 'Enter' || e.key === ' ') && this.focusId !== undefined) {
      e.preventDefault();
      fireEvent(this, 'uit-activate', { id: this.focusId });
    } else if (e.key === '+' || e.key === '=') {
      e.preventDefault();
      this.zoomBy(1.25);
    } else if (e.key === '-') {
      e.preventDefault();
      this.zoomBy(0.8);
    } else if (e.key === '0') {
      e.preventDefault();
      this.fit();
    }
  }

  protected override render(): TemplateResult | typeof nothing {
    const { model, layout, localize } = this;
    if (!model || !layout || !localize) return nothing;
    const r = RADIUS[this.density];
    let ids = [...layout.positions.keys()];
    let links = [...model.links.values()];
    if (this.needsCulling && this.width > 0) {
      const shown = visibleIds(layout, this.transform, this.width, this.height);
      if (this.focusId !== undefined) shown.add(this.focusId);
      if (this.selectedId !== undefined) shown.add(this.selectedId);
      ids = ids.filter((id) => shown.has(id));
      links = links.filter((l) => shown.has(l.childId) || shown.has(l.parentId));
    }
    const path = this.highlightedPath();
    return html`
      <svg
        class="canvas ${this.reducedMotion ? 'still' : ''}"
        role="application"
        aria-roledescription=${localize('graph.roledescription')}
        aria-label=${localize('graph.label', { site: this.siteName, devices: model.stats.devices, clients: model.stats.clients })}
        @keydown=${this.onKeydown}
      >
        <g class="viewport" transform=${this.transformAttr()}>
          <g class="links">${repeat(links, (l) => l.childId, (l) => this.renderLink(l, layout, path))}</g>
          <g class="nodes">${repeat(ids, (id) => id, (id) => this.renderNode(model, model.visuals.get(id)!, layout.positions.get(id)!, r, path, true))}</g>
          <g class="exits" aria-hidden="true">
            ${repeat([...this.exiting], ([id]) => id, ([, ghost]) => this.renderGhost(model, ghost, r))}
          </g>
        </g>
      </svg>
      <div class="hint" aria-hidden="true" ?hidden=${!this.hintVisible}>${localize('zoom.hint')}</div>
    `;
  }

  private renderLink(link: VisualLink, layout: Layout, path: Set<string>): SVGTemplateResult | typeof nothing {
    const a = layout.positions.get(link.parentId);
    const b = layout.positions.get(link.childId);
    if (!a || !b) return nothing;
    const mid = this.orientation === 'vertical' ? (a.y + b.y) / 2 : (a.x + b.x) / 2;
    const d = this.orientation === 'vertical'
      ? `M${a.x},${a.y} C${a.x},${mid} ${b.x},${mid} ${b.x},${b.y}`
      : `M${a.x},${a.y} C${mid},${a.y} ${mid},${b.y} ${b.x},${b.y}`;
    const label = this.showLabels ? linkLabel(link.edge) : '';
    const classes = ['link', link.edge?.medium ?? 'unknown', link.viaHidden.length > 0 ? 'via-hidden' : '', path.has(link.childId) ? 'on-path' : ''];
    return svg`<path class=${classes.join(' ')} d=${d}></path>${label
      ? svg`<text class="link-label" x=${(a.x + b.x) / 2} y=${(a.y + b.y) / 2}>${label}</text>`
      : nothing}`;
  }

  private renderNode(model: GraphModel, visual: Visual, p: Point, r: number, path: Set<string>, interactive: boolean): SVGTemplateResult {
    const localize = this.localize!;
    const id = visual.id;
    const state = visualState(visual);
    const title = visualTitle(visual, localize);
    const kind = visual.type === 'group' ? 'group' : visual.node.kind;
    const classes = ['node', visual.type, kind, state, id === this.selectedId ? 'selected' : '', path.has(id) ? 'on-path' : '', this.entering.has(id) ? 'enter' : ''];
    const glyph = visual.type === 'group' ? GROUP_ICON : iconFor(visual.node);
    const labelY = r + 16;
    return svg`<g
      class=${classes.join(' ')}
      data-id=${id}
      role=${interactive ? 'button' : nothing}
      tabindex=${interactive ? (id === this.focusId ? 0 : -1) : nothing}
      aria-label=${interactive ? describeVisual(model, visual, localize) : nothing}
      aria-expanded=${interactive && visual.type === 'group' ? String(visual.expanded) : nothing}
      style=${`transform: translate(${p.x}px, ${p.y}px)`}
      @click=${interactive ? () => fireEvent(this, 'uit-activate', { id }) : nothing}
      @focus=${interactive ? () => { this.focusId = id; } : nothing}
    >
      <title>${title}</title>
      <circle class="hit" r=${Math.max(r, 22)}></circle>
      <circle class="ring" r=${r + 5}></circle>
      <circle class="disc" r=${r}></circle>
      <svg class="glyph" x=${-r * 0.6} y=${-r * 0.6} width=${r * 1.2} height=${r * 1.2} viewBox="0 0 24 24" aria-hidden="true">
        <path d=${glyph}></path>
      </svg>
      <circle class="status" cx=${r * 0.72} cy=${-r * 0.72} r=${Math.max(4, r * 0.24)}></circle>
      ${visual.type === 'group' ? svg`<text class="badge" x=${r * 0.95} y=${r + 2}>${visual.counts.total}</text>` : nothing}
      ${this.showLabels ? svg`<text class="label" y=${labelY}>${truncate(title, LABEL_CHARS)}</text>` : nothing}
      ${state === 'offline'
        ? svg`<text class="state-text" y=${this.showLabels ? labelY + 14 : labelY}>${localize(STATE_KEYS.offline)}</text>`
        : nothing}
    </g>`;
  }

  /** A removed node fading out; it keeps the visual it had, since the model no longer has it. */
  private renderGhost(model: GraphModel, ghost: Ghost, r: number): SVGTemplateResult {
    return this.renderNode(model, ghost.visual, ghost.point, r, new Set(), false);
  }

  static override styles = [
    themeTokens,
    css`
      :host {
        display: block;
        position: relative;
        flex: 1;
        min-width: 0;
        min-height: 0;
      }
      svg.canvas {
        display: block;
        width: 100%;
        height: 100%;
        touch-action: none;
        user-select: none;
      }
      .node {
        cursor: pointer;
        outline: none;
        transition: transform 250ms ease;
      }
      .still .node {
        transition: none;
      }
      .node.enter {
        animation: uit-fade-in 250ms ease;
      }
      .exits .node {
        animation: uit-fade-out 250ms ease forwards;
        pointer-events: none;
      }
      .still .node.enter,
      .still .exits .node {
        animation: none;
      }
      @keyframes uit-fade-in {
        from {
          opacity: 0;
        }
      }
      @keyframes uit-fade-out {
        to {
          opacity: 0;
        }
      }
      .hit {
        fill: transparent;
      }
      .ring {
        fill: none;
        stroke: none;
      }
      .node:focus-visible .ring {
        stroke: var(--uit-focus);
        stroke-width: 2;
      }
      .disc {
        fill: var(--card-background-color, #fff);
        stroke: var(--uit-line);
        stroke-width: 2;
      }
      .selected .disc,
      .on-path .disc {
        stroke: var(--uit-focus);
      }
      .selected .disc {
        stroke-width: 3;
      }
      .glyph path {
        fill: var(--primary-text-color);
      }
      .offline .disc,
      .offline .glyph {
        opacity: 0.55;
      }
      .status {
        fill: var(--uit-online);
        stroke: var(--card-background-color, #fff);
        stroke-width: 2;
      }
      .offline .status {
        fill: var(--uit-offline);
      }
      .unknown .status {
        fill: var(--uit-unknown);
      }
      text {
        font-size: 12px;
        fill: var(--primary-text-color);
        text-anchor: middle;
        dominant-baseline: hanging;
      }
      .badge {
        font-weight: 600;
        text-anchor: start;
      }
      .state-text {
        fill: var(--uit-offline);
        font-weight: 600;
      }
      .link {
        fill: none;
        stroke: var(--secondary-text-color);
        stroke-opacity: 0.6;
        stroke-width: 1.5;
      }
      .link.wireless {
        stroke-dasharray: 2 4;
      }
      .link.via-hidden {
        stroke-dasharray: 8 4;
      }
      .link.on-path {
        stroke: var(--uit-focus);
        stroke-opacity: 1;
        stroke-width: 2.5;
      }
      .link-label {
        font-size: 10px;
        fill: var(--secondary-text-color);
        paint-order: stroke;
        stroke: var(--card-background-color, #fff);
        stroke-width: 3;
      }
      .hint {
        position: absolute;
        left: 50%;
        bottom: 12px;
        transform: translateX(-50%);
        padding: 6px 12px;
        border-radius: 16px;
        background: var(--primary-text-color);
        color: var(--card-background-color, #fff);
        font-size: 12px;
        pointer-events: none;
      }
      .hint[hidden] {
        display: none;
      }
      @media (prefers-reduced-motion: reduce) {
        .node {
          transition: none;
        }
        .node.enter,
        .exits .node {
          animation: none;
        }
      }
    `,
  ];
}

defineOnce('uit-graph-view', UitGraphView);

declare global {
  interface HTMLElementTagNameMap {
    'uit-graph-view': UitGraphView;
  }
}
```

- [ ] **Step 3: Run the tests**

Run: `npm test -- graph-view`
Expected: PASS. If d3-zoom throws in jsdom inside `transform`/`scaleBy` (missing SVG geometry APIs), the fix is in the component, not the test: the explicit `.extent(...)` above must be the only size source d3 consults — check the stack trace for which default accessor ran and supply it (`.extent`, `.translateExtent`, `.constrain`).

- [ ] **Step 4: Run everything and commit**

```bash
npm test && npm run typecheck && npm run lint && npm run build
cd ~/ha-unifi-insights-card
git add frontend custom_components/unifi_insights/frontend/topology-card.js
git commit -m "feat(frontend): interactive topology graph view

SVG nodes are real focusable elements, so keyboard traversal, labels
and HA theme colours work natively. Pan/zoom/pinch come from d3-zoom;
in dashboard grids a plain wheel scrolls the page and shows a
Ctrl+scroll hint. Nodes are keyed by id so a refresh only moves what
changed; above 300 nodes only those near the viewport are rendered.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---
### Task 8: Card shell, picker registration, interaction tests

**Files:**
- Create: `frontend/src/topology-card.ts`
- Modify: `frontend/src/index.ts` (replace placeholder)
- Modify: `frontend/test/helpers.ts` (append `fakeHass`, `settle`)
- Test: `frontend/test/topology-card.test.ts`

**Interfaces:**
- Consumes: every earlier module. Events `uit-activate`, `uit-select`, `uit-toggle-group`, `uit-close` from the views. `UitGraphView.zoomBy/fit`.
- Produces: `class UnifiInsightsTopologyCard` (tag `unifi-insights-topology-card`) with `setConfig(config)`, `getCardSize() → 8`, `getGridOptions() → { columns: 12, rows: 8, min_columns: 6, min_rows: 4 }`, `static getConfigElement()` (creates `unifi-insights-topology-card-editor`), `static getStubConfig(hass)`, public reactive `hass`, `layout`, `selectedId`, `narrow`. `index.ts` registers the card and its `window.customCards` entry. Test helpers `fakeHass(opts)` → `{ hass, subs, connection, push(payload) }`, `settle(el)`.

- [ ] **Step 1: Append the HA fakes to `frontend/test/helpers.ts`**

```ts
import { vi } from 'vitest';
import type { HomeAssistant, MessageBase } from '../src/ha-types';

export interface FakeSub {
  message: MessageBase;
  callback: (message: unknown) => void;
  unsubscribe: ReturnType<typeof vi.fn>;
}

/** A hass object whose sources call and subscribe command are scripted. */
export function fakeHass(opts: { sources?: TopologySource[]; sourcesError?: unknown; subscribeError?: unknown } = {}) {
  const subs: FakeSub[] = [];
  const connection = {
    subscribeMessage: vi.fn((callback: (m: unknown) => void, message: MessageBase) => {
      if (opts.subscribeError !== undefined) return Promise.reject(opts.subscribeError);
      const unsubscribe = vi.fn(async () => undefined);
      subs.push({ message, callback, unsubscribe });
      return Promise.resolve(unsubscribe);
    }),
  };
  const hass = {
    connection,
    callWS: vi.fn(async () => {
      if (opts.sourcesError !== undefined) throw opts.sourcesError;
      return opts.sources ?? SOURCES_ONE;
    }),
    locale: { language: 'en' },
  } as unknown as HomeAssistant;
  return { hass, subs, connection, push: (payload: unknown) => subs.at(-1)!.callback(payload) };
}

/** Let promise callbacks and Lit updates run to completion. */
export async function settle(el: { updateComplete: Promise<boolean> }): Promise<void> {
  for (let i = 0; i < 4; i++) {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await el.updateComplete;
  }
}
```

- [ ] **Step 2: Write the failing card tests**

`frontend/test/topology-card.test.ts`:
```ts
import { afterEach, describe, expect, it } from 'vitest';
import '../src/index';
import { WS_SUBSCRIBE } from '../src/contract';
import type { UnifiInsightsTopologyCard } from '../src/topology-card';
import type { UitGraphView } from '../src/views/graph-view';
import { SOURCES_MULTI, cleanup, fakeHass, fixtureSnapshot, settle, unavailableSnapshot } from './helpers';

const TYPE = 'custom:unifi-insights-topology-card';
afterEach(cleanup);

async function card(config: Record<string, unknown> = {}, fake = fakeHass()) {
  const el = document.createElement('unifi-insights-topology-card') as UnifiInsightsTopologyCard;
  el.setConfig({ type: TYPE, ...config });
  el.hass = fake.hass;
  document.body.append(el);
  await settle(el);
  return { el, fake };
}
const text = (el: Element) => el.shadowRoot!.textContent ?? '';
const q = <T extends Element>(el: Element, selector: string) => el.shadowRoot!.querySelector<T>(selector);
const button = (el: Element, label: string) =>
  [...el.shadowRoot!.querySelectorAll<HTMLButtonElement>('button')].find((b) => b.textContent?.trim() === label)!;
const graphOf = (el: Element) => q<UitGraphView>(el, 'uit-graph-view')!;
const dispatch = (el: Element, type: string, id: string) =>
  q(el, '.card')!.dispatchEvent(new CustomEvent(type, { detail: { id }, bubbles: true, composed: true }));

describe('registration', () => {
  it('appears once in the card picker with a preview', () => {
    const entries = (window.customCards ?? []).filter((c) => c.type === 'unifi-insights-topology-card');
    expect(entries).toEqual([expect.objectContaining({ name: 'UniFi Insights Topology', preview: true })]);
  });

  it('rejects an invalid config with a readable error', () => {
    const el = document.createElement('unifi-insights-topology-card') as UnifiInsightsTopologyCard;
    expect(() => el.setConfig({ type: TYPE, view: 'map' })).toThrow(/view must be one of/);
  });

  it('sizes itself for masonry and sections', () => {
    const el = document.createElement('unifi-insights-topology-card') as UnifiInsightsTopologyCard;
    expect(el.getCardSize()).toBe(8);
    expect(el.getGridOptions()).toEqual({ columns: 12, rows: 8, min_columns: 6, min_rows: 4 });
  });

  it('builds a stub config from the first source', async () => {
    const Card = customElements.get('unifi-insights-topology-card') as unknown as typeof UnifiInsightsTopologyCard;
    expect(await Card.getStubConfig(fakeHass({ sources: SOURCES_MULTI }).hass)).toEqual({ type: TYPE, entry_id: 'entry-1', site_id: 'site-1' });
    expect(await Card.getStubConfig(fakeHass({ sourcesError: { code: 'unknown_command', message: '' } }).hass)).toEqual({ type: TYPE });
  });
});

describe('states', () => {
  it('auto-binds the only site, subscribes and shows loading', async () => {
    const { el, fake } = await card();
    expect(fake.subs).toHaveLength(1);
    expect(fake.subs[0]!.message).toEqual({ type: WS_SUBSCRIBE, entry_id: 'entry-1', site_id: 'site-1', max_clients: 500 });
    expect(text(el)).toContain('Loading network topology…');
  });

  it('renders the graph and the site name once a snapshot arrives', async () => {
    const { el, fake } = await card();
    fake.push(fixtureSnapshot());
    await settle(el);
    expect(graphOf(el).model?.visuals.has('dev:uuid-core')).toBe(true);
    expect(q(el, 'h2')!.textContent).toBe('Home');
    expect(q(el, '[role="status"]')!.textContent).toBe('Topology updated.');
  });

  it('points to the integration when none is loaded', async () => {
    const { el } = await card({}, fakeHass({ sources: [] }));
    expect(text(el)).toContain('No UniFi Insights integration is loaded.');
    button(el, 'Integration').click();
    expect(location.pathname).toBe('/config/integrations/integration/unifi_insights');
  });

  it('asks for a site when several exist and none is configured', async () => {
    const { el, fake } = await card({}, fakeHass({ sources: SOURCES_MULTI }));
    expect(fake.subs).toHaveLength(0);
    expect(text(el)).toContain('Choose a site to show.');
    button(el, 'Edit card').click();
    expect(location.search).toBe('?edit=1');
  });

  it('shows site_not_selected with an edit action', async () => {
    const fake = fakeHass({ subscribeError: { code: 'site_not_selected', message: 'Site gone' } });
    const { el } = await card({ entry_id: 'entry-1', site_id: 'gone' }, fake);
    expect(text(el)).toContain('The configured site no longer exists or is disabled.');
    expect(button(el, 'Edit card')).toBeDefined();
  });

  it('lists each issue of a partial snapshot in a banner', async () => {
    const { el, fake } = await card();
    fake.push(fixtureSnapshot({
      revision: 'b'.repeat(16), status: 'partial',
      issues: [{ code: 'parents_unresolved', severity: 'warning' }],
      unresolved: [{ node_id: 'dev:x', reason: 'parent_not_found' }],
    }));
    await settle(el);
    expect(q(el, '.notices li.warning')!.textContent).toContain("1 nodes couldn't be placed under a parent.");
    expect(graphOf(el)).not.toBeNull();
  });

  it('keeps the last graph, greyed and marked stale, while the site is unavailable', async () => {
    const { el, fake } = await card();
    fake.push(fixtureSnapshot());
    fake.push(unavailableSnapshot('site_unavailable'));
    await settle(el);
    expect(q(el, '.content.stale')).not.toBeNull();
    expect(q(el, '.badge.stale')!.textContent).toBe('Stale');
    expect(graphOf(el).model?.visuals.size).toBeGreaterThan(0);
  });

  it('shows reconnecting after the entry unloads', async () => {
    const { el, fake } = await card();
    fake.push(fixtureSnapshot());
    fake.push(unavailableSnapshot('entry_unloaded'));
    await settle(el);
    expect(q(el, '.badge.stale')!.textContent).toBe('Stale · Reconnecting…');
  });

  it('reports a schema mismatch', async () => {
    const { el, fake } = await card();
    fake.push({ ...fixtureSnapshot(), schema_version: 2 });
    await settle(el);
    expect(text(el)).toContain("Card and integration versions don't match.");
  });
});

describe('interaction', () => {
  async function loaded(config: Record<string, unknown> = {}) {
    const result = await card(config);
    result.fake.push(fixtureSnapshot());
    await settle(result.el);
    return result;
  }

  it('toggles between graph and list views', async () => {
    const { el } = await loaded();
    button(el, 'List').click();
    await settle(el);
    expect(q(el, 'uit-list-view')).not.toBeNull();
    expect(button(el, 'List').getAttribute('aria-pressed')).toBe('true');
    expect(button(el, 'Graph').getAttribute('aria-pressed')).toBe('false');
  });

  it('filters kinds with chips but never hides every kind', async () => {
    const { el } = await loaded();
    button(el, 'Switch').click();
    await settle(el);
    expect(graphOf(el).model?.visuals.has('dev:uuid-core')).toBe(false);
    const single = await loaded({ kinds: ['gateway'] });
    button(single.el, 'Gateway').click();
    await settle(single.el);
    expect(button(single.el, 'Gateway').getAttribute('aria-pressed')).toBe('true');
  });

  it('opens details on activate and closes them with Escape', async () => {
    const { el } = await loaded();
    dispatch(el, 'uit-activate', 'dev:uuid-core');
    await settle(el);
    expect(el.selectedId).toBe('dev:uuid-core');
    expect(q<HTMLElement & { selectedId?: string }>(el, 'uit-detail-panel')!.selectedId).toBe('dev:uuid-core');
    q(el, '.card')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await settle(el);
    expect(el.selectedId).toBeUndefined();
  });

  it('expands a group when it is activated or when one of its clients is selected', async () => {
    const { el } = await loaded();
    dispatch(el, 'uit-activate', 'group:dev:uuid-ap');
    await settle(el);
    expect(graphOf(el).model?.visuals.has('cli:cli-phone')).toBe(true);
    dispatch(el, 'uit-select', 'cli:cli-tv');
    await settle(el);
    expect(graphOf(el).model?.visuals.has('cli:cli-tv')).toBe(true);
    expect(el.selectedId).toBe('cli:cli-tv');
  });

  it('switches sites with the selector without flashing the old graph', async () => {
    const fake = fakeHass({ sources: SOURCES_MULTI });
    const { el } = await card({ entry_id: 'entry-1', site_id: 'site-1', show_site_selector: true }, fake);
    fake.push(fixtureSnapshot());
    await settle(el);
    const select = q<HTMLSelectElement>(el, 'select')!;
    expect(select.options).toHaveLength(3);
    select.value = '1';
    select.dispatchEvent(new Event('change'));
    await settle(el);
    expect(fake.subs[0]!.unsubscribe).toHaveBeenCalledOnce();
    expect(fake.subs[1]!.message).toMatchObject({ entry_id: 'entry-1', site_id: 'site-2' });
    expect(q(el, 'uit-graph-view')).toBeNull();
    expect(text(el)).toContain('Loading network topology…');
  });

  it('collapses the toolbar and compacts the graph when narrow', async () => {
    const { el } = await loaded();
    el.narrow = true;
    await settle(el);
    expect(q(el, 'details.toolbar')).not.toBeNull();
    expect(graphOf(el).density).toBe('compact');
    expect(q<HTMLElement & { narrow: boolean }>(el, 'uit-detail-panel')!.narrow).toBe(true);
  });

  it('lets the wheel zoom directly only in panel view', async () => {
    const { el } = await loaded();
    expect(graphOf(el).ctrlZoom).toBe(true);
    el.layout = 'panel';
    await settle(el);
    expect(graphOf(el).ctrlZoom).toBe(false);
  });
});

describe('lifecycle', () => {
  it('does not resubscribe on ordinary hass updates', async () => {
    const { el, fake } = await card();
    el.hass = { ...fake.hass } as typeof fake.hass;
    await settle(el);
    expect(fake.subs).toHaveLength(1);
  });

  it('resubscribes after being re-attached', async () => {
    const { el, fake } = await card();
    el.remove();
    expect(fake.subs[0]!.unsubscribe).toHaveBeenCalledOnce();
    document.body.append(el);
    await settle(el);
    expect(fake.subs).toHaveLength(2);
    expect(fake.subs[1]!.unsubscribe).not.toHaveBeenCalled();
  });
});
```

Run: `npm test -- topology-card` → FAIL (`../src/topology-card` not found / element not registered).

- [ ] **Step 3: Implement `topology-card.ts`**

```ts
import { LitElement, css, html, nothing, type PropertyValues, type TemplateResult } from 'lit';
import {
  CARD_TYPE, EDITOR_TAG, VIEWS, allSites, resolveBinding, resolveConfig, sameBinding, validateConfig,
  type Density, type ResolvedConfig, type SiteBinding, type TopologyCardConfig, type ViewMode,
} from './config';
import { NODE_KINDS, WS_SOURCES, type NodeKind, type SiteTopology, type TopologySource } from './contract';
import { Announcer } from './data/announcer';
import { deriveState, issueNotice, type CardPhase, type CardState, type Notice, type NoticeAction } from './data/state';
import { TopologySubscription } from './data/subscription';
import { navigate, toWsError, type Connection, type HomeAssistant, type WsError } from './ha-types';
import { iconTemplate, mdiFitToScreenOutline, mdiMagnifyMinusOutline, mdiMagnifyPlusOutline } from './icons';
import { makeLocalize, type LocalizeFunc, type LocalizeKey, type LocalizeVars } from './localize';
import { createModelBuilder, groupContaining, type GraphModel, type UiState } from './model/graph-model';
import { controlStyles, themeTokens } from './styles';
import { KIND_KEYS } from './views/describe';
import './views/detail-panel';
import './views/graph-view';
import type { UitGraphView } from './views/graph-view';
import './views/list-view';

const NARROW_PX = 600;
const INTEGRATION_PATH = '/config/integrations/integration/unifi_insights';
const VIEW_KEYS: Record<ViewMode, LocalizeKey> = { graph: 'view.graph', list: 'view.list' };
const ACTION_KEYS: Record<NoticeAction, LocalizeKey> = { integration: 'action.integration', edit: 'action.edit' };
const PHASE_MESSAGES: Partial<Record<CardPhase, { key: LocalizeKey; action?: NoticeAction }>> = {
  loading: { key: 'state.loading' },
  no_sources: { key: 'state.no_sources', action: 'integration' },
  unconfigured: { key: 'state.unconfigured', action: 'edit' },
  empty: { key: 'state.empty' },
  incompatible: { key: 'state.incompatible' },
  reloading: { key: 'state.reconnecting' },
};

const offlineDevices = (snapshot: SiteTopology | undefined): number =>
  snapshot?.nodes.filter((n) => n.kind !== 'client' && n.state === 'offline').length ?? 0;

/** Lovelace card: one UniFi site's topology as an interactive graph or an accessible list. */
export class UnifiInsightsTopologyCard extends LitElement {
  static override properties = {
    hass: { attribute: false },
    layout: { attribute: false },
    config: { state: true },
    sources: { state: true },
    snapshot: { state: true },
    lastGood: { state: true },
    error: { state: true },
    incompatible: { state: true },
    ui: { state: true },
    view: { state: true },
    selectedId: { state: true },
    siteOverride: { state: true },
    narrow: { state: true },
    reducedMotion: { state: true },
    announcement: { state: true },
  };

  declare hass?: HomeAssistant;
  /** Set by hui-card: "panel" | "grid" | "masonry". */
  declare layout?: string;
  declare config?: ResolvedConfig;
  declare sources?: TopologySource[];
  declare snapshot?: SiteTopology;
  declare lastGood?: SiteTopology;
  declare error?: WsError;
  declare incompatible: boolean;
  declare ui: UiState;
  declare view: ViewMode;
  declare selectedId?: string;
  declare siteOverride?: SiteBinding;
  declare narrow: boolean;
  declare reducedMotion: boolean;
  declare announcement: string;

  private readonly subscription = new TopologySubscription({
    onSnapshot: (snapshot) => this.applySnapshot(snapshot),
    onError: (error) => {
      this.error = error;
    },
    onIncompatible: () => {
      this.incompatible = true;
    },
  });
  private readonly buildModel = createModelBuilder();
  private readonly announcer = new Announcer((message) => {
    this.announcement = message;
  });
  private sourcesFor: Connection | undefined;
  private boundKey: string | undefined;
  private cardState: CardState = { phase: 'loading', stale: false, notices: [] };
  private model: GraphModel | undefined;
  private resizeObserver: ResizeObserver | undefined;
  private motionQuery: MediaQueryList | undefined;
  private localizeLang: string | undefined;
  private localizeFn: LocalizeFunc | undefined;

  constructor() {
    super();
    this.incompatible = false;
    this.ui = { kinds: new Set(NODE_KINDS), clients: 'collapsed', toggledGroups: new Set() };
    this.view = 'graph';
    this.narrow = false;
    this.reducedMotion = false;
    this.announcement = '';
  }

  setConfig(config: TopologyCardConfig): void {
    const resolved = resolveConfig(validateConfig(config));
    this.config = resolved;
    this.view = resolved.view;
    this.ui = { kinds: new Set(resolved.kinds), clients: resolved.clients, toggledGroups: new Set() };
    this.siteOverride = undefined;
  }

  getCardSize(): number {
    return 8;
  }

  getGridOptions(): { columns: number; rows: number; min_columns: number; min_rows: number } {
    return { columns: 12, rows: 8, min_columns: 6, min_rows: 4 };
  }

  static getConfigElement(): HTMLElement {
    return document.createElement(EDITOR_TAG);
  }

  static async getStubConfig(hass: HomeAssistant): Promise<TopologyCardConfig> {
    try {
      const first = allSites(await hass.callWS<TopologySource[]>({ type: WS_SOURCES }))[0];
      if (first) return { type: CARD_TYPE, ...first.binding };
    } catch {
      // The card renders its own error state once added.
    }
    return { type: CARD_TYPE };
  }

  override connectedCallback(): void {
    super.connectedCallback();
    this.resizeObserver = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width ?? 0;
      this.narrow = width > 0 && width < NARROW_PX;
    });
    this.resizeObserver.observe(this);
    this.motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    this.motionQuery.addEventListener('change', this.onMotionChange);
    this.onMotionChange();
    this.sync();
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    this.subscription.stop();
    this.announcer.dispose();
    this.resizeObserver?.disconnect();
    this.resizeObserver = undefined;
    this.motionQuery?.removeEventListener('change', this.onMotionChange);
    this.sourcesFor = undefined;
  }

  protected override willUpdate(changed: PropertyValues<this>): void {
    if (changed.has('hass') || changed.has('config') || changed.has('sources') || changed.has('siteOverride')) this.sync();
    const config = this.config;
    if (!config) return;
    this.cardState = deriveState({
      sources: this.sources,
      binding: this.binding,
      snapshot: this.snapshot,
      lastGood: this.lastGood,
      error: this.error,
      incompatible: this.incompatible,
      maxClients: config.max_clients,
    });
    this.model = this.cardState.render ? this.buildModel(this.cardState.render, this.ui) : undefined;
    const selected = this.selectedId;
    if (selected !== undefined && !(this.model?.visuals.has(selected) || this.model?.nodes.has(selected))) {
      this.selectedId = undefined;
    }
  }

  private get binding(): SiteBinding | undefined {
    return this.config ? (this.siteOverride ?? resolveBinding(this.config, this.sources)) : undefined;
  }

  private get localize(): LocalizeFunc {
    const lang = this.hass?.locale?.language ?? this.hass?.language ?? 'en';
    if (lang !== this.localizeLang || !this.localizeFn) {
      this.localizeLang = lang;
      this.localizeFn = makeLocalize(lang);
    }
    return this.localizeFn;
  }

  private get graphView(): UitGraphView | null {
    return this.renderRoot.querySelector('uit-graph-view');
  }

  /** Fetch sources once per connection and point the subscription at the bound site. */
  private sync(): void {
    const { hass, config } = this;
    if (!this.isConnected || !hass || !config) return;
    if (this.sourcesFor !== hass.connection) {
      this.sourcesFor = hass.connection;
      void this.loadSources(hass);
    }
    const binding = this.binding;
    const key = binding ? `${binding.entry_id}\u0000${binding.site_id}` : undefined;
    if (key !== this.boundKey) {
      // A different site must never show the previous site's graph.
      this.boundKey = key;
      this.snapshot = undefined;
      this.lastGood = undefined;
      this.error = undefined;
      this.incompatible = false;
      this.selectedId = undefined;
    }
    this.subscription.update(hass.connection, binding ? { ...binding, max_clients: config.max_clients } : undefined);
  }

  private async loadSources(hass: HomeAssistant): Promise<void> {
    try {
      this.sources = await hass.callWS<TopologySource[]>({ type: WS_SOURCES });
    } catch (err) {
      this.error = toWsError(err);
    }
  }

  private applySnapshot(snapshot: SiteTopology): void {
    const previous = this.snapshot;
    this.snapshot = snapshot;
    this.error = undefined;
    this.incompatible = false;
    if (snapshot.status !== 'unavailable' && snapshot.nodes.length > 0) this.lastGood = snapshot;
    const localize = this.localize;
    let message = localize('announce.updated');
    const firstIssue = snapshot.issues[0];
    if (snapshot.status === 'unavailable' && firstIssue) {
      const notice = issueNotice(firstIssue, snapshot, this.config?.max_clients ?? 0);
      message = localize(notice.key, notice.vars);
    } else if (offlineDevices(snapshot) > 0 && offlineDevices(snapshot) !== offlineDevices(previous)) {
      message = localize('announce.offline', { count: offlineDevices(snapshot) });
    }
    this.announcer.announce(message);
  }

  private readonly onMotionChange = (): void => {
    this.reducedMotion = this.motionQuery?.matches ?? false;
  };

  private readonly onActivate = (e: Event): void => {
    const id = (e as CustomEvent<{ id: string }>).detail.id;
    if (this.model?.visuals.get(id)?.type === 'group') this.toggleGroup(id);
    this.selectedId = id;
  };

  private readonly onSelect = (e: Event): void => {
    const id = (e as CustomEvent<{ id: string }>).detail.id;
    const model = this.model;
    if (model && !model.visuals.has(id)) {
      const group = groupContaining(model, id);
      if (group && !group.expanded) this.toggleGroup(group.id);
    }
    this.selectedId = id;
  };

  private readonly onToggleGroup = (e: Event): void => {
    this.toggleGroup((e as CustomEvent<{ id: string }>).detail.id);
  };

  private readonly onClose = (): void => {
    this.selectedId = undefined;
  };

  private readonly onKeydown = (e: KeyboardEvent): void => {
    if (e.key === 'Escape' && this.selectedId !== undefined) {
      e.stopPropagation();
      this.selectedId = undefined;
    }
  };

  private toggleGroup(id: string): void {
    const toggled = new Set(this.ui.toggledGroups);
    if (toggled.has(id)) toggled.delete(id);
    else toggled.add(id);
    this.ui = { ...this.ui, toggledGroups: toggled };
  }

  private toggleKind(kind: NodeKind): void {
    const kinds = new Set(this.ui.kinds);
    if (kinds.has(kind)) {
      if (kinds.size === 1) return;
      kinds.delete(kind);
    } else {
      kinds.add(kind);
    }
    this.ui = { ...this.ui, kinds };
  }

  private runAction(action: NoticeAction): void {
    navigate(action === 'integration' ? INTEGRATION_PATH : `${location.pathname}?edit=1`);
  }

  protected override render(): TemplateResult | typeof nothing {
    const config = this.config;
    if (!config) return nothing;
    const localize = this.localize;
    const state = this.cardState;
    const model = this.model;
    const title = config.title ?? state.render?.site_name ?? this.snapshot?.site_name ?? localize('card.name');
    return html`<ha-card>
      <div
        class="card ${this.narrow ? 'narrow' : ''}"
        @keydown=${this.onKeydown}
        @uit-activate=${this.onActivate}
        @uit-select=${this.onSelect}
        @uit-toggle-group=${this.onToggleGroup}
        @uit-close=${this.onClose}
      >
        <header>
          <h2 class="title" title=${title}>${title}</h2>
          ${this.renderSiteSelector(config, localize)}
        </header>
        ${model ? this.renderToolbar(localize) : nothing}
        ${model ? this.renderNotices(state.notices, localize) : nothing}
        <div class="body">${model ? this.renderContent(model, state, config, localize) : this.renderMessage(state, localize)}</div>
        <div class="sr-only" role="status" aria-live="polite">${this.announcement}</div>
      </div>
    </ha-card>`;
  }

  private renderSiteSelector(config: ResolvedConfig, localize: LocalizeFunc): TemplateResult | typeof nothing {
    const sites = allSites(this.sources ?? []);
    if (!config.show_site_selector || sites.length < 2) return nothing;
    const current = this.binding;
    return html`<label class="site">
      <span class="sr-only">${localize('toolbar.site')}</span>
      <select
        @change=${(e: Event) => {
          const site = sites[Number((e.target as HTMLSelectElement).value)];
          if (site) this.siteOverride = site.binding;
        }}
      >
        ${sites.map((s, i) => html`<option value=${i} ?selected=${sameBinding(s.binding, current)}>${s.label}</option>`)}
      </select>
    </label>`;
  }

  private renderToolbar(localize: LocalizeFunc): TemplateResult {
    const controls = html`
      <div class="group" role="group" aria-label=${localize('toolbar.view')}>
        ${VIEWS.map(
          (v) => html`<button aria-pressed=${String(this.view === v)} @click=${() => { this.view = v; }}>${localize(VIEW_KEYS[v])}</button>`,
        )}
      </div>
      <div class="group" role="group" aria-label=${localize('toolbar.filters')}>
        ${NODE_KINDS.map(
          (k) => html`<button aria-pressed=${String(this.ui.kinds.has(k))} @click=${() => this.toggleKind(k)}>${localize(KIND_KEYS[k])}</button>`,
        )}
      </div>
      ${this.view === 'graph'
        ? html`<div class="group" role="group" aria-label=${localize('toolbar.zoom')}>
            ${this.iconButton(mdiMagnifyPlusOutline, localize('zoom.in'), () => this.graphView?.zoomBy(1.25))}
            ${this.iconButton(mdiMagnifyMinusOutline, localize('zoom.out'), () => this.graphView?.zoomBy(0.8))}
            ${this.iconButton(mdiFitToScreenOutline, localize('zoom.fit'), () => this.graphView?.fit())}
          </div>`
        : nothing}
    `;
    return this.narrow
      ? html`<details class="toolbar"><summary>${localize('toolbar.options')}</summary><div class="controls">${controls}</div></details>`
      : html`<div class="toolbar"><div class="controls">${controls}</div></div>`;
  }

  private iconButton(icon: string, label: string, run: () => void): TemplateResult {
    return html`<button class="icon-button" aria-label=${label} title=${label} @click=${run}>${iconTemplate(icon)}</button>`;
  }

  private actionButton(action: NoticeAction, localize: LocalizeFunc): TemplateResult {
    return html`<button class="action" @click=${() => this.runAction(action)}>${localize(ACTION_KEYS[action])}</button>`;
  }

  private renderNotices(notices: Notice[], localize: LocalizeFunc): TemplateResult | typeof nothing {
    if (notices.length === 0) return nothing;
    return html`<ul class="notices">
      ${notices.map(
        (n) => html`<li class=${n.severity}>
          <span>${localize(n.key, n.vars)}</span>${n.action ? this.actionButton(n.action, localize) : nothing}
        </li>`,
      )}
    </ul>`;
  }

  private renderMessage(state: CardState, localize: LocalizeFunc): TemplateResult {
    const phase = PHASE_MESSAGES[state.phase];
    const vars: LocalizeVars = { site: this.snapshot?.site_name ?? '' };
    const items: { key: LocalizeKey; vars?: LocalizeVars; action?: NoticeAction }[] = [];
    if (phase) items.push({ ...phase, vars });
    items.push(...state.notices);
    return html`<div class="message ${state.phase}">
      ${state.phase === 'loading'
        ? html`<svg class="skeleton" viewBox="0 0 120 60" aria-hidden="true">
            <path d="M60 18 L30 37 M60 18 L90 37"></path>
            <circle cx="60" cy="10" r="8"></circle><circle cx="30" cy="45" r="8"></circle><circle cx="90" cy="45" r="8"></circle>
          </svg>`
        : nothing}
      ${items.map((i) => html`<p>${localize(i.key, i.vars)}</p>${i.action ? this.actionButton(i.action, localize) : nothing}`)}
    </div>`;
  }

  private renderContent(model: GraphModel, state: CardState, config: ResolvedConfig, localize: LocalizeFunc): TemplateResult {
    const density: Density = config.density ?? (this.narrow ? 'compact' : 'comfortable');
    const site = state.render?.site_name ?? '';
    const badge = state.phase === 'reloading' ? `${localize('state.stale')} · ${localize('state.reconnecting')}` : localize('state.stale');
    return html`<div class="content ${state.stale ? 'stale' : ''}">
      ${state.stale ? html`<span class="badge stale">${badge}</span>` : nothing}
      ${this.view === 'graph'
        ? html`<uit-graph-view
            .model=${model}
            .density=${density}
            .orientation=${config.orientation}
            .showLabels=${config.show_labels}
            .selectedId=${this.selectedId}
            .localize=${localize}
            .siteName=${site}
            .ctrlZoom=${this.layout !== 'panel'}
            .reducedMotion=${this.reducedMotion}
          ></uit-graph-view>`
        : html`<uit-list-view .model=${model} .selectedId=${this.selectedId} .localize=${localize} .siteName=${site}></uit-list-view>`}
      <uit-detail-panel .model=${model} .selectedId=${this.selectedId} .localize=${localize} ?narrow=${this.narrow}></uit-detail-panel>
    </div>`;
  }

  static override styles = [
    themeTokens,
    controlStyles,
    css`
      :host {
        display: block;
        height: 100%;
      }
      ha-card {
        height: 100%;
        display: flex;
        flex-direction: column;
        overflow: hidden;
        container-type: inline-size;
      }
      .card {
        position: relative;
        display: flex;
        flex-direction: column;
        flex: 1;
        min-height: 0;
      }
      header {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px 16px 4px;
      }
      .title {
        flex: 1;
        min-width: 0;
        margin: 0;
        font-size: var(--ha-card-header-font-size, 1.25rem);
        font-weight: normal;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .toolbar {
        padding: 4px 12px;
      }
      details.toolbar > summary {
        min-height: 44px;
        display: flex;
        align-items: center;
        cursor: pointer;
        padding: 0 4px;
      }
      .controls {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 8px 16px;
      }
      .group {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
      }
      .icon-button {
        padding: 0;
        border-radius: 50%;
      }
      .notices {
        list-style: none;
        margin: 4px 12px;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 4px;
      }
      .notices li {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 10px;
        border-radius: 8px;
        border-inline-start: 4px solid var(--uit-warning);
        background: color-mix(in srgb, var(--uit-warning) 12%, transparent);
      }
      .notices li.info {
        border-color: var(--uit-focus);
        background: color-mix(in srgb, var(--uit-focus) 10%, transparent);
      }
      .notices li.error {
        border-color: var(--uit-offline);
        background: color-mix(in srgb, var(--uit-offline) 12%, transparent);
      }
      .notices li span {
        flex: 1;
      }
      .body {
        position: relative;
        display: flex;
        flex: 1;
        min-height: 280px;
      }
      .content {
        position: relative;
        display: flex;
        flex: 1;
        min-width: 0;
      }
      .content.stale uit-graph-view,
      .content.stale uit-list-view {
        opacity: 0.55;
        filter: grayscale(1);
      }
      .badge.stale {
        position: absolute;
        top: 8px;
        left: 12px;
        z-index: 1;
        padding: 2px 10px;
        border-radius: 12px;
        background: var(--card-background-color);
        border: 1px solid var(--uit-line);
        font-size: 0.85em;
      }
      .message {
        margin: auto;
        padding: 24px;
        text-align: center;
        color: var(--secondary-text-color);
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 8px;
      }
      .message p {
        margin: 0;
      }
      .skeleton {
        width: 120px;
        fill: var(--uit-line);
        stroke: var(--uit-line);
        stroke-width: 2;
        animation: uit-pulse 1.5s ease-in-out infinite;
      }
      @keyframes uit-pulse {
        50% {
          opacity: 0.4;
        }
      }
      @container (width < 600px) {
        header {
          padding: 8px 12px 0;
        }
        .body {
          min-height: 240px;
        }
      }
    `,
  ];
}
```

- [ ] **Step 4: Replace `index.ts`**

```ts
// Entry point of the topology card bundle, served by the integration (frontend.py).
import { CARD_TAG } from './config';
import { defineOnce } from './define';
import { makeLocalize } from './localize';
import { UnifiInsightsTopologyCard } from './topology-card';

defineOnce(CARD_TAG, UnifiInsightsTopologyCard);

const localize = makeLocalize('en');
window.customCards ??= [];
if (!window.customCards.some((card) => card.type === CARD_TAG)) {
  window.customCards.push({
    type: CARD_TAG,
    name: localize('card.name'),
    description: localize('card.description'),
    preview: true,
    documentationURL: 'https://github.com/ruaan-deysel/ha-unifi-insights#network-topology-card',
  });
}
```

- [ ] **Step 5: Run and commit**

```bash
npm test && npm run typecheck && npm run lint && npm run build && npm run size
cd ~/ha-unifi-insights-card
git add frontend custom_components/unifi_insights/frontend/topology-card.js
git commit -m "feat(frontend): topology card shell and picker registration

Wires contract, subscription, model and views into the Lovelace card:
per-card site binding with an optional in-card selector, the loading /
empty / partial / unavailable / reloading / error / incompatible states
with actionable buttons, view toggle, kind filter chips, zoom controls,
a throttled live region, and a collapsed toolbar below 600 px.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---
### Task 9: Card editor

**Files:**
- Create: `frontend/src/topology-card-editor.ts`
- Modify: `frontend/src/index.ts` (register the editor)
- Test: `frontend/test/topology-card-editor.test.ts`

**Interfaces:**
- Consumes: `config.ts` (`VIEWS`, `CLIENT_MODES`, `DENSITIES`, `ORIENTATIONS`, `allSites`, `sameBinding`, `SiteOption`, `TopologyCardConfig`), `contract.ts`, `ha-types.ts` (`fireEvent`, `CardHelpers`, `HomeAssistant`), `localize.ts`, `views/describe.KIND_KEYS`.
- Produces: `class UnifiInsightsTopologyCardEditor` (tag `unifi-insights-topology-card-editor`) with `hass`, `setConfig(config)`, firing `config-changed` `{ config }`; pure exports `STALE_SITE = 'current'`, `interface EditorFormData`, `interface FormField`, `siteValue(config, sites)`, `buildSchema(config, sites, localize)`, `toFormData(config, sites)`, `fromFormData(data, previous, sites)`, `ensureHaForm(registry?, loadHelpers?)`.

- [ ] **Step 1: Write the failing tests**

`frontend/test/topology-card-editor.test.ts`:
```ts
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import '../src/index';
import { allSites } from '../src/config';
import { NODE_KINDS } from '../src/contract';
import { makeLocalize } from '../src/localize';
import {
  STALE_SITE, buildSchema, ensureHaForm, fromFormData, toFormData, type EditorFormData, type FormField,
} from '../src/topology-card-editor';
import { SOURCES_MULTI, cleanup, fakeHass, settle } from './helpers';

const TYPE = 'custom:unifi-insights-topology-card';
const sites = allSites(SOURCES_MULTI);
const localize = makeLocalize('en');

class FakeHaForm extends HTMLElement {
  hass?: unknown;
  data?: EditorFormData;
  schema?: FormField[];
  computeLabel?: (field: FormField) => string;
}

beforeAll(() => {
  if (!customElements.get('ha-form')) customElements.define('ha-form', FakeHaForm);
});
afterEach(cleanup);

describe('form mapping', () => {
  it('maps a config to form data with defaults', () => {
    expect(toFormData({ type: TYPE, entry_id: 'entry-1', site_id: 'site-2' }, sites)).toEqual({
      site: '1', title: '', view: 'graph', clients: 'collapsed', density: 'auto', orientation: 'vertical',
      kinds: [...NODE_KINDS], show_site_selector: false, show_labels: true, max_clients: 500,
    });
    expect(toFormData({ type: TYPE }, sites).site).toBe('');
  });

  it('writes a chosen site and keeps keys the form does not own', () => {
    const previous = { type: TYPE, grid_options: { columns: 12 } };
    const next = fromFormData({ ...toFormData(previous, sites), site: '2', title: 'Office', view: 'list' }, previous, sites);
    expect(next).toMatchObject({ type: TYPE, entry_id: 'entry-2', site_id: 'default', title: 'Office', view: 'list', grid_options: { columns: 12 } });
  });

  it('drops defaults that have their own meaning when absent', () => {
    const previous = { type: TYPE, title: 'Old', density: 'compact' as const, kinds: ['gateway' as const] };
    const next = fromFormData({ ...toFormData(previous, sites), title: '', density: 'auto', kinds: [...NODE_KINDS] }, previous, sites);
    expect(next).not.toHaveProperty('title');
    expect(next).not.toHaveProperty('density');
    expect(next).not.toHaveProperty('kinds');
  });

  it('never saves an empty kind list or an out-of-range client cap', () => {
    const previous = { type: TYPE, kinds: ['gateway' as const], max_clients: 100 };
    const next = fromFormData({ ...toFormData(previous, sites), kinds: [], max_clients: 9000 }, previous, sites);
    expect(next.kinds).toEqual(['gateway']);
    expect(next.max_clients).toBe(100);
  });

  it('keeps a stale site binding selectable', () => {
    const previous = { type: TYPE, entry_id: 'entry-9', site_id: 'gone', show_labels: true };
    expect(toFormData(previous, sites).site).toBe(STALE_SITE);
    const siteField = buildSchema(previous, sites, localize)[0]!;
    expect(siteField.selector).toMatchObject({
      select: { options: expect.arrayContaining([{ value: STALE_SITE, label: 'gone (unavailable)' }]) },
    });
    const next = fromFormData({ ...toFormData(previous, sites), show_labels: false }, previous, sites);
    expect(next).toMatchObject({ entry_id: 'entry-9', site_id: 'gone', show_labels: false });
  });

  it('labels every select option', () => {
    const schema = buildSchema({ type: TYPE }, sites, localize);
    const kinds = schema.find((f) => f.name === 'kinds')!;
    expect(kinds.selector).toMatchObject({ select: { multiple: true, options: expect.arrayContaining([{ value: 'access_point', label: 'Access point' }]) } });
    expect(schema.find((f) => f.type === 'grid')!.schema!.map((f) => f.name)).toEqual(['view', 'clients', 'density', 'orientation']);
  });
});

describe('<unifi-insights-topology-card-editor>', () => {
  async function editor(config: Record<string, unknown>) {
    const el = document.createElement('unifi-insights-topology-card-editor') as HTMLElement & {
      hass?: unknown; setConfig(c: unknown): void; updateComplete: Promise<boolean>;
    };
    el.hass = fakeHass({ sources: SOURCES_MULTI }).hass;
    el.setConfig({ type: TYPE, ...config });
    document.body.append(el);
    await settle(el);
    return el;
  }

  it('is what the card returns as its config element', () => {
    const Card = customElements.get('unifi-insights-topology-card') as unknown as { getConfigElement(): HTMLElement };
    expect(Card.getConfigElement().tagName.toLowerCase()).toBe('unifi-insights-topology-card-editor');
  });

  it('renders ha-form with site options from the integration', async () => {
    const el = await editor({ entry_id: 'entry-1', site_id: 'site-1' });
    const form = el.shadowRoot!.querySelector('ha-form') as FakeHaForm;
    expect(form.data?.site).toBe('0');
    expect(form.schema![0]!.selector).toMatchObject({ select: { options: [
      { value: '0', label: 'Crestwood — Home' }, { value: '1', label: 'Crestwood — Cabin' }, { value: '2', label: 'Office — Default' },
    ] } });
    expect(form.computeLabel!({ name: 'max_clients' })).toBe('Maximum clients');
  });

  it('fires config-changed with the merged config', async () => {
    const el = await editor({ entry_id: 'entry-1', site_id: 'site-1' });
    const changed = vi.fn();
    el.addEventListener('config-changed', (e) => changed((e as CustomEvent).detail.config));
    const form = el.shadowRoot!.querySelector('ha-form') as FakeHaForm;
    form.dispatchEvent(new CustomEvent('value-changed', { detail: { value: { ...form.data, site: '2' } } }));
    expect(changed).toHaveBeenCalledWith(expect.objectContaining({ type: TYPE, entry_id: 'entry-2', site_id: 'default' }));
  });
});

describe('ensureHaForm', () => {
  it('forces HA to load ha-form through a built-in card editor', async () => {
    const getConfigElement = vi.fn(async () => undefined);
    class EntitiesCard extends HTMLElement {
      static getConfigElement = getConfigElement;
    }
    const createCardElement = vi.fn(() => new EntitiesCard());
    if (!customElements.get('fake-entities-card')) customElements.define('fake-entities-card', EntitiesCard);
    await ensureHaForm({ get: () => undefined } as unknown as CustomElementRegistry, async () => ({ createCardElement }));
    expect(createCardElement).toHaveBeenCalledWith({ type: 'entities', entities: [] });
    expect(getConfigElement).toHaveBeenCalledOnce();
  });

  it('does nothing when ha-form already exists', async () => {
    const load = vi.fn();
    await ensureHaForm(customElements, load);
    expect(load).not.toHaveBeenCalled();
  });
});
```

Run: `npm test -- topology-card-editor` → FAIL (module not found).

- [ ] **Step 2: Implement `topology-card-editor.ts`**

```ts
import { LitElement, html, nothing, type TemplateResult } from 'lit';
import {
  CLIENT_MODES, DENSITIES, ORIENTATIONS, VIEWS, allSites, sameBinding,
  type ClientsMode, type Density, type Orientation, type SiteOption, type TopologyCardConfig, type ViewMode,
} from './config';
import { MAX_CLIENTS_PER_SITE, NODE_KINDS, WS_SOURCES, type NodeKind, type TopologySource } from './contract';
import { fireEvent, type CardHelpers, type HomeAssistant } from './ha-types';
import { makeLocalize, type LocalizeFunc, type LocalizeKey } from './localize';
import { KIND_KEYS } from './views/describe';

/** Site value for a configured site that no longer exists: kept, labelled "(unavailable)". */
export const STALE_SITE = 'current';
const NO_SITE = '';

export interface EditorFormData {
  site: string;
  title: string;
  view: string;
  clients: string;
  density: string;
  orientation: string;
  kinds: string[];
  show_site_selector: boolean;
  show_labels: boolean;
  max_clients: number;
}

export interface FormField {
  name: string;
  type?: 'grid';
  selector?: Record<string, unknown>;
  schema?: FormField[];
}

const VIEW_KEYS: Record<ViewMode, LocalizeKey> = { graph: 'view.graph', list: 'view.list' };
const CLIENT_KEYS: Record<ClientsMode, LocalizeKey> = { collapsed: 'clients.collapsed', expanded: 'clients.expanded', hidden: 'clients.hidden' };
const DENSITY_KEYS: Record<'auto' | Density, LocalizeKey> = { auto: 'density.auto', comfortable: 'density.comfortable', compact: 'density.compact' };
const ORIENTATION_KEYS: Record<Orientation, LocalizeKey> = { vertical: 'orientation.vertical', horizontal: 'orientation.horizontal' };
const LABEL_KEYS: Record<string, LocalizeKey> = {
  site: 'editor.site', title: 'editor.title', view: 'editor.view', clients: 'editor.clients', kinds: 'editor.kinds',
  density: 'editor.density', orientation: 'editor.orientation', show_site_selector: 'editor.show_site_selector',
  show_labels: 'editor.show_labels', max_clients: 'editor.max_clients',
};

function options<T extends string>(values: readonly T[], keys: Record<T, LocalizeKey>, localize: LocalizeFunc): { value: T; label: string }[] {
  return values.map((value) => ({ value, label: localize(keys[value]) }));
}

const isOneOf = <T extends string>(value: unknown, allowed: readonly T[]): value is T =>
  typeof value === 'string' && (allowed as readonly string[]).includes(value);

export function siteValue(config: TopologyCardConfig, sites: SiteOption[]): string {
  const { entry_id, site_id } = config;
  if (entry_id === undefined || site_id === undefined) return NO_SITE;
  const index = sites.findIndex((s) => sameBinding(s.binding, { entry_id, site_id }));
  return index >= 0 ? String(index) : STALE_SITE;
}

export function buildSchema(config: TopologyCardConfig, sites: SiteOption[], localize: LocalizeFunc): FormField[] {
  const siteOptions = sites.map((s, i) => ({ value: String(i), label: s.label }));
  if (siteValue(config, sites) === STALE_SITE) {
    siteOptions.push({ value: STALE_SITE, label: localize('editor.site_unavailable', { site: config.site_id ?? '' }) });
  }
  return [
    { name: 'site', selector: { select: { mode: 'dropdown', options: siteOptions } } },
    { name: 'title', selector: { text: {} } },
    {
      name: '',
      type: 'grid',
      schema: [
        { name: 'view', selector: { select: { mode: 'dropdown', options: options(VIEWS, VIEW_KEYS, localize) } } },
        { name: 'clients', selector: { select: { mode: 'dropdown', options: options(CLIENT_MODES, CLIENT_KEYS, localize) } } },
        { name: 'density', selector: { select: { mode: 'dropdown', options: options(['auto', ...DENSITIES] as const, DENSITY_KEYS, localize) } } },
        { name: 'orientation', selector: { select: { mode: 'dropdown', options: options(ORIENTATIONS, ORIENTATION_KEYS, localize) } } },
      ],
    },
    { name: 'kinds', selector: { select: { multiple: true, mode: 'list', options: options(NODE_KINDS, KIND_KEYS, localize) } } },
    { name: 'show_site_selector', selector: { boolean: {} } },
    { name: 'show_labels', selector: { boolean: {} } },
    { name: 'max_clients', selector: { number: { min: 1, max: MAX_CLIENTS_PER_SITE, mode: 'box' } } },
  ];
}

export function toFormData(config: TopologyCardConfig, sites: SiteOption[]): EditorFormData {
  return {
    site: siteValue(config, sites),
    title: config.title ?? '',
    view: config.view ?? 'graph',
    clients: config.clients ?? 'collapsed',
    density: config.density ?? 'auto',
    orientation: config.orientation ?? 'vertical',
    kinds: config.kinds ? [...config.kinds] : [...NODE_KINDS],
    show_site_selector: config.show_site_selector ?? false,
    show_labels: config.show_labels ?? true,
    max_clients: config.max_clients ?? MAX_CLIENTS_PER_SITE,
  };
}

/** Merge edited form values into the previous config, keeping keys the form does not own. */
export function fromFormData(data: Partial<EditorFormData>, previous: TopologyCardConfig, sites: SiteOption[]): TopologyCardConfig {
  const next: TopologyCardConfig = { ...previous };
  const site = data.site ?? NO_SITE;
  if (site === NO_SITE) {
    delete next.entry_id;
    delete next.site_id;
  } else if (site !== STALE_SITE) {
    const chosen = sites[Number(site)];
    if (chosen) {
      next.entry_id = chosen.binding.entry_id;
      next.site_id = chosen.binding.site_id;
    }
  }
  if (data.title) next.title = data.title;
  else delete next.title;
  if (isOneOf(data.view, VIEWS)) next.view = data.view;
  if (isOneOf(data.clients, CLIENT_MODES)) next.clients = data.clients;
  if (isOneOf(data.orientation, ORIENTATIONS)) next.orientation = data.orientation;
  if (isOneOf(data.density, DENSITIES)) next.density = data.density;
  else if (data.density === 'auto') delete next.density;
  const kinds = (data.kinds ?? []).filter((k): k is NodeKind => isOneOf(k, NODE_KINDS));
  if (kinds.length === NODE_KINDS.length) delete next.kinds;
  else if (kinds.length > 0) next.kinds = NODE_KINDS.filter((k) => kinds.includes(k));
  if (typeof data.show_site_selector === 'boolean') next.show_site_selector = data.show_site_selector;
  if (typeof data.show_labels === 'boolean') next.show_labels = data.show_labels;
  const max = data.max_clients;
  if (typeof max === 'number' && Number.isInteger(max) && max >= 1 && max <= MAX_CLIENTS_PER_SITE) next.max_clients = max;
  return next;
}

/**
 * ha-form is lazy-loaded by HA and may not exist when a custom editor opens.
 * Creating a built-in card's config element forces it to register.
 */
export async function ensureHaForm(
  registry: CustomElementRegistry = customElements,
  loadHelpers: (() => Promise<CardHelpers>) | undefined = window.loadCardHelpers,
): Promise<void> {
  if (registry.get('ha-form')) return;
  const helpers = await loadHelpers?.();
  const card = helpers?.createCardElement({ type: 'entities', entities: [] });
  const ctor = card?.constructor as { getConfigElement?: () => Promise<unknown> } | undefined;
  await ctor?.getConfigElement?.();
}

/** Visual editor: site picker from `topology/sources` plus every card option. */
export class UnifiInsightsTopologyCardEditor extends LitElement {
  static override properties = {
    hass: { attribute: false },
    config: { state: true },
    sources: { state: true },
    formReady: { state: true },
  };

  declare hass?: HomeAssistant;
  declare config?: TopologyCardConfig;
  declare sources?: TopologySource[];
  declare formReady: boolean;

  private sourcesRequested = false;

  constructor() {
    super();
    this.formReady = false;
  }

  setConfig(config: TopologyCardConfig): void {
    this.config = { ...config };
  }

  override connectedCallback(): void {
    super.connectedCallback();
    void ensureHaForm()
      .catch(() => undefined)
      .then(() => {
        this.formReady = true;
      });
  }

  protected override willUpdate(): void {
    if (this.hass && !this.sourcesRequested) {
      this.sourcesRequested = true;
      this.hass.callWS<TopologySource[]>({ type: WS_SOURCES }).then(
        (sources) => {
          this.sources = sources;
        },
        () => {
          this.sources = [];
        },
      );
    }
  }

  protected override render(): TemplateResult | typeof nothing {
    const { hass, config } = this;
    if (!hass || !config) return nothing;
    const localize = makeLocalize(hass.locale?.language ?? hass.language);
    if (!this.formReady) return html`<p>${localize('state.loading')}</p>`;
    const sites = allSites(this.sources ?? []);
    return html`<ha-form
      .hass=${hass}
      .data=${toFormData(config, sites)}
      .schema=${buildSchema(config, sites, localize)}
      .computeLabel=${(field: FormField) => {
        const key = LABEL_KEYS[field.name];
        return key ? localize(key) : '';
      }}
      @value-changed=${this.onValueChanged}
    ></ha-form>`;
  }

  private readonly onValueChanged = (e: Event): void => {
    e.stopPropagation();
    const previous = this.config;
    if (!previous) return;
    const value = (e as CustomEvent<{ value: Partial<EditorFormData> }>).detail.value;
    const next = fromFormData(value, previous, allSites(this.sources ?? []));
    this.config = next;
    fireEvent(this, 'config-changed', { config: next });
  };
}
```

- [ ] **Step 3: Register the editor in `index.ts`**

Change the imports and definitions at the top of `frontend/src/index.ts` to:
```ts
import { CARD_TAG, EDITOR_TAG } from './config';
import { defineOnce } from './define';
import { makeLocalize } from './localize';
import { UnifiInsightsTopologyCard } from './topology-card';
import { UnifiInsightsTopologyCardEditor } from './topology-card-editor';

defineOnce(CARD_TAG, UnifiInsightsTopologyCard);
defineOnce(EDITOR_TAG, UnifiInsightsTopologyCardEditor);
```
(keep the `window.customCards` block unchanged).

- [ ] **Step 4: Run and commit**

```bash
npm test && npm run typecheck && npm run lint && npm run build && npm run size
cd ~/ha-unifi-insights-card
git add frontend custom_components/unifi_insights/frontend/topology-card.js
git commit -m "feat(frontend): topology card editor

The card is configurable entirely from the UI: an ha-form editor with a
site picker fed by topology/sources plus every card option. A site that
no longer exists stays selectable as '(unavailable)' so editing other
fields never silently rebinds the card. ha-form is force-loaded through
a built-in card editor because HA lazy-loads it.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: Accessibility audit and performance benchmark

**Files:**
- Test: `frontend/test/a11y.test.ts`, `frontend/test/benchmark.test.ts`

**Interfaces:**
- Consumes: the full card (`../src/index`), `buildModel`, `layoutModel`, `UitGraphView.setViewportSize`, test helpers.
- Produces: CI evidence for the #166 accessibility baseline and "performance profiling" items; no new source.

- [ ] **Step 1: Write the axe audit**

`frontend/test/a11y.test.ts`:
```ts
import axe from 'axe-core';
import { afterEach, describe, expect, it } from 'vitest';
import '../src/index';
import type { UnifiInsightsTopologyCard } from '../src/topology-card';
import { cleanup, fakeHass, fixtureSnapshot, settle } from './helpers';

afterEach(cleanup);

async function audit(root: Element): Promise<string[]> {
  const result = await axe.run(root, {
    runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] },
    // jsdom cannot compute colours; contrast comes from HA theme variables (see styles.ts).
    rules: { 'color-contrast': { enabled: false } },
  });
  return result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`);
}

async function loadedCard(config: Record<string, unknown> = {}, snapshot = fixtureSnapshot()) {
  const fake = fakeHass();
  const el = document.createElement('unifi-insights-topology-card') as UnifiInsightsTopologyCard;
  el.setConfig({ type: 'custom:unifi-insights-topology-card', ...config });
  el.hass = fake.hass;
  document.body.append(el);
  await settle(el);
  fake.push(snapshot);
  await settle(el);
  return el;
}

describe('WCAG 2.2 AA (axe-core)', () => {
  it('graph view', async () => {
    expect(await audit(await loadedCard())).toEqual([]);
  });

  it('list view', async () => {
    expect(await audit(await loadedCard({ view: 'list' }))).toEqual([]);
  });

  it('partial snapshot banner with the detail panel open', async () => {
    const el = await loadedCard({}, fixtureSnapshot({
      status: 'partial', issues: [{ code: 'devices_unavailable', severity: 'warning' }],
    }));
    el.selectedId = 'dev:uuid-core';
    await settle(el);
    expect(await audit(el)).toEqual([]);
  });

  it('error state', async () => {
    const fake = fakeHass({ subscribeError: { code: 'entry_not_found', message: '' } });
    const el = document.createElement('unifi-insights-topology-card') as UnifiInsightsTopologyCard;
    el.setConfig({ type: 'custom:unifi-insights-topology-card', entry_id: 'x', site_id: 'y' });
    el.hass = fake.hass;
    document.body.append(el);
    await settle(el);
    expect(await audit(el)).toEqual([]);
  });

  it('narrow layout with the collapsed toolbar', async () => {
    const el = await loadedCard();
    el.narrow = true;
    await settle(el);
    expect(await audit(el)).toEqual([]);
  });
});
```

- [ ] **Step 2: Run it and fix real violations in the source**

Run: `npm test -- a11y`
Expected: PASS. If axe reports a violation, fix the component (missing name, invalid ARIA attribute or role, duplicate id, nested interactive) — do not disable the rule. Only `color-contrast` is disabled, for the reason in the comment.

- [ ] **Step 3: Write the benchmark**

`frontend/test/benchmark.test.ts`:
```ts
import { afterEach, describe, expect, it } from 'vitest';
import { NODE_KINDS, type SiteTopology, type TopologyEdge, type TopologyNode } from '../src/contract';
import { makeLocalize } from '../src/localize';
import { buildModel } from '../src/model/graph-model';
import { CULL_THRESHOLD, layoutModel } from '../src/model/layout';
import type { UitGraphView } from '../src/views/graph-view';
import '../src/views/graph-view';
import { cleanup, fixtureSnapshot, mount } from './helpers';

afterEach(cleanup);

/** A gateway, a core switch, 18 access switches/APs and 500 clients spread across them. */
function bigSnapshot(): SiteTopology {
  const nodes: TopologyNode[] = [
    { id: 'dev:gw', kind: 'gateway', name: 'Gateway', state: 'online' },
    { id: 'dev:core', kind: 'switch', name: 'Core', state: 'online' },
  ];
  const edges: TopologyEdge[] = [{ source: 'dev:core', target: 'dev:gw', medium: 'wired', parent_port: 1, speed_mbps: 10000 }];
  for (let i = 0; i < 18; i++) {
    nodes.push({ id: `dev:d${i}`, kind: i % 3 === 0 ? 'access_point' : 'switch', name: `Device ${i}`, state: 'online' });
    edges.push({ source: `dev:d${i}`, target: 'dev:core', medium: 'wired', parent_port: i + 2, speed_mbps: 1000 });
  }
  for (let i = 0; i < 500; i++) {
    const parent = `dev:d${i % 18}`;
    nodes.push({ id: `cli:c${i}`, kind: 'client', name: `Client ${i}`, state: 'online', connection: i % 2 ? 'wired' : 'wireless' });
    edges.push({ source: `cli:c${i}`, target: parent, medium: i % 2 ? 'wired' : 'wireless' });
  }
  return fixtureSnapshot({ nodes, edges, truncation: null });
}

const ui = { kinds: new Set(NODE_KINDS), clients: 'expanded' as const, toggledGroups: new Set<string>() };

describe('large site (20 devices, 500 clients, fully expanded)', () => {
  it('builds and lays out within budget', () => {
    const snapshot = bigSnapshot();
    const start = performance.now();
    const model = buildModel(snapshot, ui);
    const layout = layoutModel(model, 'comfortable', 'vertical');
    const ms = performance.now() - start;
    console.info(`[benchmark] model + layout for ${layout.positions.size} nodes: ${ms.toFixed(1)} ms`);
    expect(layout.positions.size).toBe(20 + 18 + 500); // devices + one group per access device + clients
    expect(ms).toBeLessThan(500); // generous for CI runners; typical is far lower
  });

  it('renders only the nodes near the viewport', async () => {
    const model = buildModel(bigSnapshot(), ui);
    expect(model.visuals.size).toBeGreaterThan(CULL_THRESHOLD);
    const el = await mount<UitGraphView>('uit-graph-view', { model, localize: makeLocalize('en'), siteName: 'Big', reducedMotion: true });
    el.setViewportSize(800, 600);
    await el.updateComplete;
    const rendered = el.shadowRoot!.querySelectorAll('g.nodes g.node').length;
    console.info(`[benchmark] rendered ${rendered} of ${model.visuals.size} nodes`);
    expect(rendered).toBeGreaterThan(0);
    expect(rendered).toBeLessThan(model.visuals.size);
  });
});
```

- [ ] **Step 4: Run, check coverage, commit**

```bash
npm test -- benchmark
npm test -- --coverage
```
Expected: benchmark passes and prints its timings; coverage summary shows ≥ 90 % lines on `src/`. If below 90 %, add tests for the uncovered branches the summary names (do not lower the threshold).
```bash
npm run lint && npm run typecheck
cd ~/ha-unifi-insights-card
git add frontend
git commit -m "test(frontend): accessibility audit and large-site benchmark

axe-core (WCAG 2.2 AA tags) runs over the graph, list, partial-banner
with detail panel, error and narrow states. The benchmark lays out a
500-client site within a generous CI budget and proves viewport culling
keeps the DOM bounded.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 11: Documentation, changelog, full verification

**Files:**
- Modify: `README.md` (new `## Network topology card` section directly above `## Troubleshooting`)
- Modify: `CHANGELOG.md` (`## [Unreleased]` → `### Added`)

**Interfaces:**
- Consumes: the finished card.
- Produces: user docs whose anchor matches `documentationURL` (`#network-topology-card`); release note.

- [ ] **Step 1: Add the README section** (directly above `## Troubleshooting`)

```markdown
## Network topology card

The integration ships a Lovelace card that draws each site's network: the
gateway, switches and access points, and the clients connected to them. It is
installed with the integration — there is no separate download and no
dashboard resource to add.

**Add it:** edit a dashboard → *Add card* → search for **UniFi Insights
Topology**. With a single UniFi site the card works without any configuration;
with several, pick the site in the card editor.

**Use it:**

- **Graph** view: drag to pan, pinch or Ctrl + scroll to zoom (plain scroll
  zooms in panel view), and use the zoom buttons or `+` / `-` / `0` keys.
  Select a device to see its uplink port, link speed, PoE draw and client
  counts, with a link to its Home Assistant device page.
- **List** view: the same network as an indented list with search. It is the
  recommended view for screen readers.
- Clients are grouped under their switch or access point ("12 clients");
  select a group to expand it.
- The filter buttons hide gateways, switches, access points, clients or other
  devices; devices under a hidden one stay visible, linked with a dashed line.

**Options** (all optional, all available in the card editor):

| Option | Values | Default |
| --- | --- | --- |
| `entry_id` + `site_id` | the site to show | the only site, if there is one |
| `title` | text | the site name |
| `view` | `graph`, `list` | `graph` |
| `show_site_selector` | `true`, `false` | `false` |
| `clients` | `collapsed`, `expanded`, `hidden` | `collapsed` |
| `kinds` | any of `gateway`, `switch`, `access_point`, `client`, `other` | all |
| `density` | `comfortable`, `compact` | automatic (compact on narrow cards) |
| `orientation` | `vertical`, `horizontal` | `vertical` |
| `show_labels` | `true`, `false` | `true` |
| `max_clients` | 1–500 | 500 |

The card only receives what the topology API sends — names, models, states,
ports and VLANs. MAC addresses, IP addresses, hostnames and firmware versions
are never included.
```

- [ ] **Step 2: Add the changelog entry** (first bullet under `## [Unreleased]` → `### Added`)

```markdown
- Network topology dashboard card, served by the integration and listed in the
  card picker as **UniFi Insights Topology**. It draws each site's gateway,
  switches, access points and clients as an interactive graph (pan, zoom,
  pinch, node details with uplink port, speed and PoE) or an accessible list,
  with per-card site selection, client grouping, kind filters, and clear
  loading, partial-data, reconnecting and error states. Configurable entirely
  from the card editor.
  [#166](https://github.com/ruaan-deysel/ha-unifi-insights/issues/166)
```

- [ ] **Step 3: Full verification**

```bash
cd ~/ha-unifi-insights-card/frontend
npm ci && npm run lint && npm run typecheck && npm test -- --coverage && npm run build && npm run size
git -C .. diff --exit-code -- custom_components/unifi_insights/frontend/
cd ..
$VENV/pytest --cov --cov-branch -q
$VENV/mypy custom_components/unifi_insights
$VENV/bandit -r custom_components/unifi_insights -q
$VENV/pre-commit run --all-files
```
Expected: every command exits 0; the committed bundle equals a fresh build; Python branch coverage ≥ 90 %; mypy 0; bandit 0 issues; pre-commit clean. If codespell flags a frontend identifier, add it to the existing codespell ignore list rather than renaming. Record the exact numbers (test counts, coverage %, bundle KB, benchmark ms) — Task 12 puts them in the PR body.

- [ ] **Step 4: Check ruff introduced nothing new**

```bash
~/ai-tools/scripts/ruff-new-findings.sh upstream/main
```
Expected: zero new findings across every file the branch touches. The script checks the COMMITTED tree, so run it after Step 5's commit as well if Step 5 changes Python. If bandit/ast tooling fails on PEP 758 `except A, B:` syntax, run it under Python 3.14 (`uvx --python 3.14 bandit ...`).

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: topology card README section and changelog entry

Closes the #166 loop for users: how to add the card, what each view
does, every option with its default, and what data the card can see.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 12: Live verification on VM113 and local PR draft

**Files:**
- Modify (local only, gitignored): `~/ha-unifi-insights/.local/pr-bodies/topology-card-166.md`
- Memory + KB: update `topology-card-166-spec` memory file and KB entry `a8e08d83-96b0-5280-9fd9-a7f419e2b7ce` (supersede)

**Interfaces:**
- Consumes: the finished branch; tools `~/ai-tools/scripts/ha-hacs-branch-deploy.py`, `~/ai-tools/scripts/ha-dashboard-screenshot.py`, `~/ai-tools/scripts/ha-ws-client.py`, `~/ai-tools/scripts/secret-get.sh home-assistant-token`.
- Produces: live evidence and a filled PR body. **Does not push or open the PR** — Justin posts it.

- [ ] **Step 1: Ask before touching VM113**

VM113 currently runs another preview build (`deploy/topology-sm177-20260924`, the #177 Site Manager test). Ask Justin whether to replace it now. Do not continue until he says yes.

- [ ] **Step 2: Look up the deploy procedure instead of guessing flags**

```bash
~/ai-tools/scripts/ha-hacs-branch-deploy.py --help
```
Also run `knowledge_search` for "ha-hacs-branch-deploy fork branch deploy VM113" and read memory `vm113-upstream-steady-state.md`. Use the documented fork-branch deploy form (a pushed branch on `delacjus/ha-unifi-insights`, deploy branch name `deploy/topology-card-<yyyymmdd>`). Pushing a `deploy/*` branch to the fork is the established test path; still confirm with Justin in Step 1.

- [ ] **Step 3: Remove the prototype card first**

The prototype registers the same tag. List dashboard resources and delete only the prototype's entry (`/local/unifi-insights-topology-card.js?v=...`), leaving the file in `/config/www` for rollback:
```bash
~/ai-tools/scripts/ha-ws-client.py '{"type":"lovelace/resources"}'
~/ai-tools/scripts/ha-ws-client.py '{"type":"lovelace/resources/delete","resource_id":"<id of the prototype resource>"}'
```

- [ ] **Step 4: Deploy, restart, and verify the bundle is served**

Deploy with the procedure from Step 2, restart Home Assistant, then:
```bash
curl -s -o /dev/null -w '%{http_code} %{size_download}\n' "http://<VM113 HA>:8123/unifi_insights/topology-card.js"
```
Expected: `200` and the bundle size from Task 11. Check the HA log (`ha-ws-client.py '{"type":"system_log/list"}'`) for new errors mentioning `unifi_insights` or `frontend`.

- [ ] **Step 5: Exercise the card on a real dashboard**

On a test dashboard, add the card from the picker, configure it in the editor (Crestwood), then verify and note each result:
1. 7 device edges match the controller's uplink table (same check as #167's live test).
2. Graph, list, detail panel (core switch: port, 10G, Open device works), client group expand.
3. Filter chips; site selector (if a second site exists).
4. Reload the integration → card shows "Stale · Reconnecting…" → recovers by itself.
5. Keyboard only: Tab to the graph, arrows, Enter, Esc, `+`/`-`/`0`; then the list view.
6. Screenshots, dark and light, desktop and mobile width:
   ```bash
   ~/ai-tools/scripts/ha-dashboard-screenshot.py /<test-dashboard>/default --dark
   ~/ai-tools/scripts/ha-dashboard-screenshot.py /<test-dashboard>/default
   ```
   (use the script's `--help` for the mobile-width flag).
7. No new log lines beyond the known Protect 429 / `/sites` warnings.

- [ ] **Step 6: Roll VM113 back**

Restore the build it had before Step 4 (ask Justin whether that is the #177 preview or upstream). For upstream: `~/ai-tools/scripts/ha-hacs-branch-deploy.py deploy --repo 917968755 --version <current upstream release tag>`. Re-add the prototype resource only if Justin wants it back.

- [ ] **Step 7: Fill the local PR body**

Edit `~/ha-unifi-insights/.local/pr-bodies/topology-card-166.md`: replace every `⟨fill⟩` with the Task 11 numbers and the Step 5 results, attach the screenshot paths, and fill the per-API compatibility table from the spec §7. Re-read `.github/pull_request_template.md` and the merged #167 body first (house format). Tell Justin the branch and the body are ready; do not push or open the PR.

- [ ] **Step 8: Update memory and KB**

Update `~/.claude/projects/-home-tacoriffic-ha-unifi-insights/memory/topology-card-166-spec.md` (and its `MEMORY.md` line) with: branch head, test/coverage numbers, live result, VM113 state after rollback. Write the same to the KB with `knowledge_write(..., supersedes="a8e08d83-96b0-5280-9fd9-a7f419e2b7ce")`.
