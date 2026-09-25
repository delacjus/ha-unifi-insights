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


async def test_registers_bundle_once(hass, http, enable_custom_integrations) -> None:
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
        patch("custom_components.unifi_insights.async_register_frontend") as register,
    ):
        assert await async_setup(hass, {})

    register.assert_awaited_once_with(hass)


def test_manifest_loads_after_web_components() -> None:
    """http/frontend are ordering hints, not hard dependencies.

    Tests run without hass_frontend.
    """
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert set(manifest["after_dependencies"]) >= {"http", "frontend"}
    assert "frontend" not in manifest["dependencies"]


def test_bundle_is_shipped() -> None:
    """HACS installs the repository tree, so the built bundle must be committed."""
    assert CARD_PATH.is_file()
