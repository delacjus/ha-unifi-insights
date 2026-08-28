"""Tests for the shared UniFi Protect connectivity probe."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from custom_components.unifi_insights.api import UniFiConnectionError, UniFiTimeoutError
from custom_components.unifi_insights.probe import async_probe_protect

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_probe_true_with_cameras() -> None:
    """Probe succeeds immediately when cameras are present."""
    client = MagicMock()
    client.cameras.get_all = AsyncMock(return_value=[MagicMock(id="camera1")])

    assert await async_probe_protect(client) is True


async def test_probe_true_via_nvr_fallback() -> None:
    """Probe succeeds via the NVR fallback when cameras are empty."""
    client = MagicMock()
    client.cameras.get_all = AsyncMock(return_value=[])
    client.nvr.get = AsyncMock(return_value=MagicMock(id="nvr1"))

    assert await async_probe_protect(client) is True


async def test_probe_false_when_nvr_falsy() -> None:
    """Probe fails when cameras are empty and NVR fetch returns falsy."""
    client = MagicMock()
    client.cameras.get_all = AsyncMock(return_value=[])
    client.nvr.get = AsyncMock(return_value=None)

    assert await async_probe_protect(client) is False


async def test_probe_false_when_cameras_raises() -> None:
    """Probe fails when the camera list fetch raises."""
    client = MagicMock()
    client.cameras.get_all = AsyncMock(side_effect=Exception("boom"))

    assert await async_probe_protect(client) is False


async def test_probe_false_when_nvr_raises() -> None:
    """Probe fails when the NVR fallback fetch raises."""
    client = MagicMock()
    client.cameras.get_all = AsyncMock(return_value=[])
    client.nvr.get = AsyncMock(side_effect=Exception("boom"))

    assert await async_probe_protect(client) is False


async def test_probe_false_when_cameras_not_a_list() -> None:
    """Probe fails when the camera fetch returns a non-list, non-None value."""
    client = MagicMock()
    client.cameras.get_all = AsyncMock(return_value="unexpected")

    assert await async_probe_protect(client) is False


async def test_probe_false_when_cameras_none() -> None:
    """Probe fails when the camera fetch returns None."""
    client = MagicMock()
    client.cameras.get_all = AsyncMock(return_value=None)

    assert await async_probe_protect(client) is False


async def test_probe_swallows_connection_error_by_default() -> None:
    """By default a connection error is swallowed, matching __init__.py's
    "disable Protect support, don't block setup" behavior.
    """
    client = MagicMock()
    client.cameras.get_all = AsyncMock(side_effect=UniFiConnectionError("boom"))

    assert await async_probe_protect(client) is False


async def test_probe_propagates_connection_error_when_opted_in() -> None:
    """With propagate_connection_errors=True, a connection error during the
    camera fetch raises instead of being swallowed, so callers like the
    config flow can distinguish it from "no Protect app here".
    """
    client = MagicMock()
    client.cameras.get_all = AsyncMock(side_effect=UniFiConnectionError("boom"))

    with pytest.raises(UniFiConnectionError):
        await async_probe_protect(client, propagate_connection_errors=True)


async def test_probe_swallows_connection_error_from_nvr_fallback_by_default() -> None:
    """A connection error during the NVR fallback is swallowed by default."""
    client = MagicMock()
    client.cameras.get_all = AsyncMock(return_value=[])
    client.nvr.get = AsyncMock(side_effect=UniFiConnectionError("boom"))

    assert await async_probe_protect(client) is False


async def test_probe_propagates_timeout_error_from_nvr_fallback() -> None:
    """A timeout during the NVR fallback also propagates when opted in."""
    client = MagicMock()
    client.cameras.get_all = AsyncMock(return_value=[])
    client.nvr.get = AsyncMock(side_effect=UniFiTimeoutError("timed out"))

    with pytest.raises(UniFiTimeoutError):
        await async_probe_protect(client, propagate_connection_errors=True)


async def test_probe_swallows_validation_error_by_default() -> None:
    """A malformed API response (pydantic ValidationError) is swallowed by
    default, matching __init__.py's "disable Protect support, don't block
    setup" behavior for any other probe failure.
    """
    client = MagicMock()
    client.cameras.get_all = AsyncMock(
        side_effect=ValidationError.from_exception_data("Camera", line_errors=[])
    )

    assert await async_probe_protect(client) is False


async def test_probe_propagates_validation_error_when_opted_in() -> None:
    """With propagate_connection_errors=True, a ValidationError during the
    camera fetch also raises instead of being swallowed, so the config flow
    can surface it as site_parse_error instead of the generic invalid_auth.
    """
    client = MagicMock()
    client.cameras.get_all = AsyncMock(
        side_effect=ValidationError.from_exception_data("Camera", line_errors=[])
    )

    with pytest.raises(ValidationError):
        await async_probe_protect(client, propagate_connection_errors=True)
