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
