"""Tests for the UniFi Insights integration initialization."""

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from custom_components.unifi_insights import UnifiInsightsData
from custom_components.unifi_insights.api import (
    UniFiAuthenticationError,
    UniFiConnectionError,
    UniFiTimeoutError,
)


async def test_setup_entry_success(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_network_client,
    mock_protect_client,
    mock_local_auth,
    enable_custom_integrations,
) -> None:
    """Test successful setup of config entry."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state == ConfigEntryState.LOADED


async def test_setup_entry_auth_failed(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_network_client,
    mock_local_auth,
    enable_custom_integrations,
) -> None:
    """Test setup fails with authentication error."""
    mock_network_client.sites.get_all.side_effect = UniFiAuthenticationError(
        "Invalid API key"
    )

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state == ConfigEntryState.SETUP_ERROR


async def test_setup_entry_connection_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_network_client,
    mock_local_auth,
    enable_custom_integrations,
) -> None:
    """Test setup fails with connection error."""
    mock_network_client.sites.get_all.side_effect = UniFiConnectionError(
        "Cannot connect"
    )

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state == ConfigEntryState.SETUP_RETRY


async def test_setup_entry_timeout_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_network_client,
    mock_local_auth,
    enable_custom_integrations,
) -> None:
    """Test setup fails with timeout error."""
    mock_network_client.sites.get_all.side_effect = UniFiTimeoutError(
        "Connection timeout"
    )

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state == ConfigEntryState.SETUP_RETRY


async def test_setup_entry_protect_unavailable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_network_client,
    mock_protect_client,
    mock_local_auth,
    enable_custom_integrations,
) -> None:
    """Test setup succeeds even if Protect is unavailable."""
    mock_protect_client.cameras.get_all.side_effect = Exception("Protect unavailable")

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state == ConfigEntryState.LOADED


async def test_unload_entry(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    enable_custom_integrations,
) -> None:
    """Test successful unload of a config entry."""
    assert await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()

    assert init_integration.state == ConfigEntryState.NOT_LOADED


async def test_setup_entry_starts_protect_websocket(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    enable_custom_integrations,
) -> None:
    """Test setup resolves host_id and starts the real-time WebSocket.

    Regression test for the dead `hasattr(..., "register_device_update_callback")`
    stub: the coordinator must actually invoke `get_host_id()` and hand a real
    background task to `ProtectWebSocket.subscribe_with_callback`, not just
    construct without error.
    """
    runtime_data = init_integration.runtime_data
    protect_coordinator = runtime_data.protect_coordinator
    assert protect_coordinator is not None

    runtime_data.protect_client.get_host_id.assert_awaited_once()
    assert protect_coordinator.websocket_task is not None
    await protect_coordinator.websocket_task
    protect_coordinator._protect_websocket.subscribe_with_callback.assert_awaited_once()


async def test_unload_entry_cancels_real_websocket_task(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    enable_custom_integrations,
) -> None:
    """Test unload stops the ProtectWebSocket and cancels/awaits the real task.

    Regression test: `websocket_task.cancel()` alone does not stop
    `subscribe_with_callback`'s reconnect loop (it swallowed
    `CancelledError` and slept/reconnected instead), which would leave an
    orphaned WebSocket loop running after a config entry reload.
    """
    runtime_data = init_integration.runtime_data
    protect_coordinator = runtime_data.protect_coordinator
    assert protect_coordinator is not None
    websocket_task = protect_coordinator.websocket_task
    assert websocket_task is not None

    assert await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()

    assert init_integration.state == ConfigEntryState.NOT_LOADED
    protect_coordinator._protect_websocket.stop.assert_called_once()
    assert websocket_task.done()


async def test_reload_entry(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    enable_custom_integrations,
) -> None:
    """Test successful reload of a config entry."""
    await hass.config_entries.async_reload(init_integration.entry_id)
    await hass.async_block_till_done()

    assert init_integration.state == ConfigEntryState.LOADED


async def test_reload_entry_via_options_update(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    enable_custom_integrations,
) -> None:
    """Test reload triggered by options update (update listener)."""
    # Update options to trigger the update listener (async_reload_entry)
    hass.config_entries.async_update_entry(
        init_integration,
        options={"track_wifi_clients": True},
    )
    await hass.async_block_till_done()

    # Entry should be reloaded and in loaded state
    assert init_integration.state == ConfigEntryState.LOADED


async def test_setup_entry_no_sites_found(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_network_client,
    mock_protect_client,
    mock_local_auth,
    enable_custom_integrations,
) -> None:
    """Test setup fails when neither Network sites nor Protect are found."""
    # Return empty list - no sites found
    mock_network_client.sites.get_all.return_value = []
    # Protect probe also fails (empty cameras + no NVR) so there is no
    # fallback path that would let this console validate as Protect-only.
    mock_protect_client.cameras.get_all.return_value = []
    mock_protect_client.nvr.get.return_value = None

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Should fail with auth failed (no sites and no Protect means bad API key)
    assert mock_config_entry.state == ConfigEntryState.SETUP_ERROR


async def test_setup_entry_protect_only_via_cameras(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_network_client,
    mock_protect_client,
    mock_local_auth,
    enable_custom_integrations,
) -> None:
    """Test setup succeeds Protect-only when Network has no sites but cameras exist."""
    mock_network_client.sites.get_all.return_value = []
    # cameras.get_all() populated - the non-ambiguous success branch.

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state == ConfigEntryState.LOADED
    # A Protect-only entry must produce real entities, not just a loaded
    # shell - confirm the camera from mock_protect_client materialized.
    assert hass.states.async_entity_ids()


async def test_setup_entry_protect_only_via_nvr_fallback(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_network_client,
    mock_protect_client,
    mock_local_auth,
    enable_custom_integrations,
) -> None:
    """Test setup succeeds Protect-only via the empty-cameras + NVR fallback."""
    mock_network_client.sites.get_all.return_value = []
    # Empty camera list is ambiguous - disambiguate via a truthy NVR fetch.
    mock_protect_client.cameras.get_all.return_value = []
    mock_protect_client.nvr.get.return_value = MagicMock(
        id="nvr1", name="NVR", type="UNVR"
    )

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state == ConfigEntryState.LOADED


async def test_setup_entry_remote_connection(
    hass: HomeAssistant,
    mock_network_client,
    mock_protect_client,
    mock_local_auth,
    enable_custom_integrations,
) -> None:
    """Test setup with remote connection type includes Protect."""
    # Create remote config entry
    remote_entry = MockConfigEntry(
        domain="unifi_insights",
        data={
            "connection_type": "remote",
            "console_id": "test_console",
            "api_key": "test_api_key",
        },
        entry_id="remote_entry",
    )

    remote_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(remote_entry.entry_id)
    await hass.async_block_till_done()

    assert remote_entry.state == ConfigEntryState.LOADED


async def test_unload_entry_with_websocket_task(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    enable_custom_integrations,
) -> None:
    """Test unload entry cancels websocket task."""

    # Add a mock websocket task to the protect coordinator
    runtime_data = init_integration.runtime_data
    if runtime_data.protect_coordinator:
        mock_task = MagicMock()
        mock_task.cancel = MagicMock()
        runtime_data.protect_coordinator.websocket_task = mock_task

    assert await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()

    assert init_integration.state == ConfigEntryState.NOT_LOADED


async def test_unload_entry_protect_close_error(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    enable_custom_integrations,
) -> None:
    """Test unload entry handles protect client close error gracefully."""
    # Make protect client close raise an error
    runtime_data = init_integration.runtime_data
    if runtime_data.protect_client:
        runtime_data.protect_client.close = AsyncMock(
            side_effect=Exception("Close error")
        )

    # Should still unload successfully
    assert await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()

    assert init_integration.state == ConfigEntryState.NOT_LOADED


async def test_unload_entry_network_close_error(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    enable_custom_integrations,
) -> None:
    """Test unload entry handles network client close error gracefully."""
    # Make network client close raise an error
    runtime_data = init_integration.runtime_data
    runtime_data.network_client.close = AsyncMock(side_effect=Exception("Close error"))

    # Should still unload successfully
    assert await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()

    assert init_integration.state == ConfigEntryState.NOT_LOADED


async def test_unifi_insights_data_coordinator_not_initialized(
    hass: HomeAssistant,
) -> None:
    """Test UnifiInsightsData raises error when facade coordinator not initialized."""
    # Create data object with None facade coordinator
    data = UnifiInsightsData(
        config_coordinator=MagicMock(),
        device_coordinator=MagicMock(),
        protect_coordinator=None,
        network_client=MagicMock(),
        protect_client=None,
        _facade_coordinator=None,
    )

    # Accessing coordinator property should raise RuntimeError
    with pytest.raises(RuntimeError, match="Facade coordinator not initialized"):
        _ = data.coordinator
