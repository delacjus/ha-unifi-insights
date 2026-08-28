"""Tests for the vendored UniFi Protect WebSocket client.

This module lives under `custom_components/unifi_insights/api/**`, which is
excluded from the coverage gate (see `[tool.coverage.run].omit` in
pyproject.toml) because it is a vendored package. It still runs live against
production door-lock sensors, so it is tested directly here regardless of the
gate.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.unifi_insights.api import ApiKeyAuth, ConnectionType, LocalAuth
from custom_components.unifi_insights.api.protect import UniFiProtectClient
from custom_components.unifi_insights.api.protect.websocket import ProtectWebSocket


def _local_client() -> UniFiProtectClient:
    return UniFiProtectClient(
        auth=LocalAuth(api_key="test-key", verify_ssl=False),
        base_url="https://192.168.1.1",
        connection_type=ConnectionType.LOCAL,
    )


def _remote_client() -> UniFiProtectClient:
    return UniFiProtectClient(
        auth=ApiKeyAuth(api_key="test-key"),
        connection_type=ConnectionType.REMOTE,
        console_id="console-1",
    )


def test_subscribe_path_local_uses_integration_api() -> None:
    """LOCAL WS subscribe path must match the client's own REST convention.

    Regression test: the WS path used to be hardcoded to a cloud-only
    `/ea/hosts/{host_id}/sites/{site_id}/subscribe/...` scheme that does not
    exist on a local console, which made the WebSocket silently non-functional
    for LOCAL (including Protect-only) consoles.
    """
    client = _local_client()

    assert (
        client.websocket._subscribe_path("devices")
        == "/proxy/protect/integration/v1/subscribe/devices"
    )
    assert (
        client.websocket._subscribe_path("events")
        == "/proxy/protect/integration/v1/subscribe/events"
    )


def test_subscribe_path_remote_uses_connector_routing() -> None:
    """REMOTE WS subscribe path must route through the connector like REST calls."""
    client = _remote_client()

    assert client.websocket._subscribe_path("devices") == (
        "/v1/connector/consoles/console-1/protect/integration/v1/subscribe/devices"
    )


def _make_ws(messages: list[aiohttp.WSMessage]) -> MagicMock:
    """Build a fake aiohttp WebSocket that yields the given messages then ends."""
    ws = MagicMock()
    ws.closed = False

    async def _aiter():
        for msg in messages:
            yield msg

    ws.__aiter__ = lambda self=ws: _aiter()
    ws.close = AsyncMock(side_effect=lambda: setattr(ws, "closed", True))
    return ws


@pytest.mark.asyncio
async def test_subscribe_with_callback_dispatches_messages() -> None:
    """A single successful connection delivers decoded JSON messages."""
    client = _local_client()
    ws_socket = ProtectWebSocket(client)

    text_msg = MagicMock(type=aiohttp.WSMsgType.TEXT, data='{"modelKey": "sensor"}')
    close_msg = MagicMock(type=aiohttp.WSMsgType.CLOSED)
    fake_ws = _make_ws([text_msg, close_msg])

    ws_socket._connect = AsyncMock(return_value=fake_ws)
    received: list[dict] = []

    await ws_socket.subscribe_with_callback(
        "nvr1", "default", "devices", received.append, reconnect=False
    )

    assert received == [{"modelKey": "sensor"}]
    fake_ws.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_subscribe_with_callback_invalid_subscription_type() -> None:
    """Only 'devices'/'events' are valid subscription types."""
    client = _local_client()
    ws_socket = ProtectWebSocket(client)

    with pytest.raises(ValueError, match=r"devices.*events"):
        await ws_socket.subscribe_with_callback(
            "nvr1", "default", "bogus", lambda _msg: None
        )


@pytest.mark.asyncio
async def test_subscribe_with_callback_drops_invalid_json(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Non-JSON text frames are dropped without invoking the callback."""
    client = _local_client()
    ws_socket = ProtectWebSocket(client)

    bad_msg = MagicMock(type=aiohttp.WSMsgType.TEXT, data="not-json")
    close_msg = MagicMock(type=aiohttp.WSMsgType.CLOSED)
    fake_ws = _make_ws([bad_msg, close_msg])
    ws_socket._connect = AsyncMock(return_value=fake_ws)

    callback = MagicMock()
    with caplog.at_level(logging.DEBUG):
        await ws_socket.subscribe_with_callback(
            "nvr1", "default", "devices", callback, reconnect=False
        )

    callback.assert_not_called()


@pytest.mark.asyncio
async def test_subscribe_with_callback_reconnects_after_client_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A connection error is logged at WARNING and triggers a reconnect."""
    client = _local_client()
    ws_socket = ProtectWebSocket(client)

    close_msg = MagicMock(type=aiohttp.WSMsgType.CLOSED)
    good_ws = _make_ws([close_msg])

    connect_calls = 0

    async def _connect(_path: str):
        nonlocal connect_calls
        connect_calls += 1
        if connect_calls == 1:
            msg = "handshake failed"
            raise aiohttp.ClientConnectionError(msg)
        # Second attempt succeeds, then subscribe_with_callback stops because
        # reconnect=False keeps _running True only for one more loop; force
        # stop from within the second connection.
        ws_socket.stop()
        return good_ws

    ws_socket._connect = _connect

    with caplog.at_level(logging.WARNING):
        await ws_socket.subscribe_with_callback(
            "nvr1",
            "default",
            "devices",
            lambda _msg: None,
            reconnect=True,
            reconnect_delay=0,
        )

    assert connect_calls == 2
    assert "connection error" in caplog.text.lower()


@pytest.mark.asyncio
async def test_subscribe_with_callback_propagates_cancellation() -> None:
    """Cancellation must propagate, not be swallowed into a reconnect loop.

    Regression test: the previous implementation caught
    `asyncio.CancelledError` alongside `aiohttp.ClientError` and fell through
    to the reconnect-sleep branch, so `task.cancel()` from the integration's
    unload path never actually stopped the background WebSocket loop.
    """
    client = _local_client()
    ws_socket = ProtectWebSocket(client)

    async def _connect(_path: str):
        raise asyncio.CancelledError

    ws_socket._connect = _connect

    with pytest.raises(asyncio.CancelledError):
        await ws_socket.subscribe_with_callback(
            "nvr1", "default", "devices", lambda _msg: None
        )


def test_stop_sets_running_false() -> None:
    """stop() flips the running flag so the reconnect loop exits."""
    client = _local_client()
    ws_socket = ProtectWebSocket(client)
    ws_socket._running = True

    ws_socket.stop()

    assert ws_socket._running is False


@pytest.mark.asyncio
async def test_subscribe_with_callback_reports_connect_then_disconnect() -> None:
    """`on_connection_state_change` fires True after connect, False on exit.

    The coordinator's WS health signal and its "reconcile on WS reconnect"
    safety net (see coordinators/protect.py) both depend on knowing exactly
    when a subscription connects/disconnects - this method is the only place
    that actually knows.
    """
    client = _local_client()
    ws_socket = ProtectWebSocket(client)

    close_msg = MagicMock(type=aiohttp.WSMsgType.CLOSED)
    fake_ws = _make_ws([close_msg])
    ws_socket._connect = AsyncMock(return_value=fake_ws)

    states: list[bool] = []

    await ws_socket.subscribe_with_callback(
        "nvr1",
        "default",
        "devices",
        lambda _msg: None,
        reconnect=False,
        on_connection_state_change=states.append,
    )

    assert states == [True, False]


@pytest.mark.asyncio
async def test_subscribe_with_callback_reports_disconnect_before_reconnect() -> None:
    """A connection error reports False (never connected) before the retry,
    then True/False again around the successful reconnection.
    """
    client = _local_client()
    ws_socket = ProtectWebSocket(client)

    close_msg = MagicMock(type=aiohttp.WSMsgType.CLOSED)
    good_ws = _make_ws([close_msg])

    connect_calls = 0

    async def _connect(_path: str):
        nonlocal connect_calls
        connect_calls += 1
        if connect_calls == 1:
            msg = "handshake failed"
            raise aiohttp.ClientConnectionError(msg)
        ws_socket.stop()
        return good_ws

    ws_socket._connect = _connect
    states: list[bool] = []

    await ws_socket.subscribe_with_callback(
        "nvr1",
        "default",
        "devices",
        lambda _msg: None,
        reconnect=True,
        reconnect_delay=0,
        on_connection_state_change=states.append,
    )

    assert states == [False, True, False]


@pytest.mark.asyncio
async def test_subscribe_with_callback_without_state_callback_still_works() -> None:
    """`on_connection_state_change` is optional and defaults to a no-op."""
    client = _local_client()
    ws_socket = ProtectWebSocket(client)

    close_msg = MagicMock(type=aiohttp.WSMsgType.CLOSED)
    fake_ws = _make_ws([close_msg])
    ws_socket._connect = AsyncMock(return_value=fake_ws)

    # Must not raise even though no callback was supplied.
    await ws_socket.subscribe_with_callback(
        "nvr1", "default", "devices", lambda _msg: None, reconnect=False
    )
