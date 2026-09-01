"""Traffic Routes (Policy-Based Routing) endpoint for UniFi Network API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..models.routes import TrafficRoute

if TYPE_CHECKING:
    from ..client import UniFiNetworkClient


class RoutesEndpoint:
    """Endpoint for managing policy-based traffic routes."""

    def __init__(self, client: UniFiNetworkClient) -> None:
        """
        Initialize the routes endpoint.

        Args:
            client: The UniFi Network client.

        """
        self._client = client

    async def list_routes(self, site_name: str) -> list[TrafficRoute]:
        """
        List all traffic routes for a site.

        Args:
            site_name: The UniFi site name (e.g., 'default').

        Returns:
            List of traffic routes.

        """
        path = self._client.build_legacy_v2_api_path(site_name, "/trafficroutes")
        response = await self._client._get(path)

        if response is None:
            return []

        data = (
            response.get("data", response) if isinstance(response, dict) else response
        )
        if isinstance(data, list):
            return [
                TrafficRoute.model_validate(item)
                for item in data
                if isinstance(item, dict)
            ]
        return []

    async def get_route(self, site_name: str, route_id: str) -> TrafficRoute:
        """
        Get a specific traffic route by ID.

        Args:
            site_name: The UniFi site name (e.g., 'default').
            route_id: The traffic route ID.

        Returns:
            The traffic route.

        Raises:
            ValueError: If the route is not found.

        """
        routes = await self.list_routes(site_name)
        for route in routes:
            if route.id == route_id:
                return route
        raise ValueError(f"Traffic route {route_id} not found")

    async def update_route(
        self,
        site_name: str,
        route_id: str,
        **kwargs: Any,
    ) -> TrafficRoute:
        """
        Update an existing traffic route.

        Fetches current route list, updates the matching payload, and sends PUT.

        Args:
            site_name: The UniFi site name (e.g., 'default').
            route_id: The traffic route ID.
            **kwargs: Properties to update on the traffic route.

        Returns:
            The updated traffic route.

        Raises:
            ValueError: If the route is not found.

        """
        path = self._client.build_legacy_v2_api_path(site_name, "/trafficroutes")
        response = await self._client._get(path)

        data = (
            response.get("data", response) if isinstance(response, dict) else response
        )
        if not isinstance(data, list):
            raise ValueError(f"Traffic route {route_id} not found")

        matching_payload: dict[str, Any] | None = None
        for item in data:
            if isinstance(item, dict) and (
                item.get("_id") == route_id or item.get("id") == route_id
            ):
                matching_payload = dict(item)
                break

        if matching_payload is None:
            raise ValueError(f"Traffic route {route_id} not found")

        matching_payload.update(kwargs)

        put_path = self._client.build_legacy_v2_api_path(
            site_name, f"/trafficroutes/{route_id}"
        )
        put_response = await self._client._put(put_path, json_data=matching_payload)

        if isinstance(put_response, dict):
            result = put_response.get("data", put_response)
            if isinstance(result, dict):
                return TrafficRoute.model_validate(result)
        return TrafficRoute.model_validate(matching_payload)
