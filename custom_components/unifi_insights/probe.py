"""
Shared UniFi Protect connectivity probe.

Used by both the config flow and integration setup to determine whether a
console exposes a working, authenticated UniFi Protect application,
independent of whether the Network application is present (e.g. a
standalone Protect-only NVR with no Network app running).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .api import UniFiConnectionError, UniFiTimeoutError

if TYPE_CHECKING:
    from .api.protect import UniFiProtectClient

_LOGGER = logging.getLogger(__name__)


async def async_probe_protect(
    protect_client: UniFiProtectClient,
    *,
    propagate_connection_errors: bool = False,
) -> bool:
    """
    Return True if the Protect API is reachable and authenticated.

    An empty camera list is ambiguous (no cameras vs. a bad key/console), so
    fall back to fetching NVR info, which fails for a genuinely bad key or a
    console with no Protect application.

    By default all errors are swallowed and treated as "Protect not
    available" - this is what `__init__.py` wants, since a flaky Protect
    probe there should just disable Protect support, not block setup.

    Callers that need to distinguish "no Protect application here" from "the
    console/network is genuinely unreachable" (e.g. the config flow, which
    should surface a connection error as `cannot_connect` rather than
    `invalid_auth`) can pass `propagate_connection_errors=True` to let
    `UniFiConnectionError`/`UniFiTimeoutError` raise instead of being
    swallowed.
    """
    try:
        cameras = await protect_client.cameras.get_all()
    except (UniFiConnectionError, UniFiTimeoutError):
        if propagate_connection_errors:
            raise
        _LOGGER.debug("Protect probe: camera list fetch failed", exc_info=True)
        return False
    except Exception:  # pylint: disable=broad-except
        _LOGGER.debug("Protect probe: camera list fetch failed", exc_info=True)
        return False

    if cameras is None or not isinstance(cameras, list):
        return False
    if len(cameras) > 0:
        return True

    try:
        nvr = await protect_client.nvr.get()
    except (UniFiConnectionError, UniFiTimeoutError):
        if propagate_connection_errors:
            raise
        _LOGGER.debug("Protect probe: NVR fetch failed", exc_info=True)
        return False
    except Exception:  # pylint: disable=broad-except
        _LOGGER.debug("Protect probe: NVR fetch failed", exc_info=True)
        return False

    return bool(nvr)
