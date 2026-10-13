"""Static routes endpoint for UniFi Network API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from custom_components.unifi_insights.api.const import ENDPOINT_STATIC_ROUTES
from custom_components.unifi_insights.api.exceptions import (
    UniFiNotFoundError,
    UniFiResponseError,
)
from custom_components.unifi_insights.api.network.models.static_route import (
    StaticRoute,
)

if TYPE_CHECKING:
    from custom_components.unifi_insights.api.network.client import UniFiNetworkClient

_LOGGER = logging.getLogger(__name__)


class StaticRoutesEndpoint:
    """
    Endpoint for static routes.

    Targets the classic controller endpoint:
    ``/proxy/network/api/s/{site_name}/rest/routing``

    This path is not in the official UniFi API (Network 11 returns 404 on v2
    ``/static-route``). Its shape is reference-derived (filipowm/go-unifi
    ``Routing.json``, sirkirby/unifi-network-rules) and was not observed on a
    live console: Network 11 answered 200 with no records on 2026-10-12. An
    update fetches the list, finds the record, toggles ``enabled`` and PUTs the
    full raw object to ``rest/routing/{rule_id}``. X-API-Key acceptance for the
    PUT is unverified.
    """

    def __init__(self, client: UniFiNetworkClient) -> None:
        """Initialize the Static Routes endpoint."""
        self._client = client

    def _extract_items(self, response: Any) -> list[dict[str, Any]]:
        """Extract data items from a legacy response envelope."""
        if response is None:
            return []

        if isinstance(response, dict):
            meta = response.get("meta")
            if isinstance(meta, dict) and meta.get("rc") == "error":
                msg = meta.get("msg", "UniFi Network API error")
                raise UniFiResponseError(
                    msg, status_code=200, response_body=str(response)
                )

            data = response.get("data", response)
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
            if isinstance(data, dict):
                return [data]
            return []

        if isinstance(response, list):
            return [item for item in response if isinstance(item, dict)]

        return []

    async def list_static_routes(self, site_name: str) -> list[StaticRoute]:
        """List all static routes for a site."""
        path = self._client.build_legacy_api_path(site_name, ENDPOINT_STATIC_ROUTES)
        response = await self._client._get(path)
        items = self._extract_items(response)

        rules: list[StaticRoute] = []
        for item in items:
            try:
                rules.append(StaticRoute.model_validate(item))
            except ValidationError as err:
                _LOGGER.debug("Skipping invalid static route item: %s", err)
                continue

        return rules

    async def update_static_route(
        self, site_name: str, rule_id: str, *, enabled: bool
    ) -> StaticRoute:
        """Enable or disable a static route."""
        list_path = self._client.build_legacy_api_path(site_name, ENDPOINT_STATIC_ROUTES)
        items = self._extract_items(await self._client._get(list_path))
        current = next(
            (i for i in items if (i.get("_id") or i.get("id")) == rule_id), None
        )
        if current is None:
            msg = f"Static route {rule_id} not found"
            raise UniFiNotFoundError(msg, status_code=404)

        payload = dict(current)
        payload["enabled"] = enabled

        put_path = self._client.build_legacy_api_path(
            site_name, f"{ENDPOINT_STATIC_ROUTES}/{rule_id}"
        )
        put_items = self._extract_items(
            await self._client._put(put_path, json_data=payload)
        )
        if put_items and (put_items[0].get("_id") or put_items[0].get("id")) == rule_id:
            return StaticRoute.model_validate(put_items[0])

        return StaticRoute.model_validate(payload)
