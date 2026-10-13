"""Static route data model for UniFi Network API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StaticRoute(BaseModel):
    """
    Static route in UniFi Network (classic ``/rest/routing``).

    Reference shape, not observed on a live console (0 records on Network 11,
    2026-10-12). Keys per filipowm/go-unifi ``Routing.json`` (v9.5.21):
    _id, enabled, gateway_device, gateway_type, name, site_id,
    static-route_distance, static-route_interface, static-route_network,
    static-route_nexthop, static-route_type, type.

    Only id, name and enabled are declared; every other key is kept as an extra so a
    type change on the controller cannot make a record fail validation (a skipped
    record would look deleted to the switch orphan prune).
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = Field(alias="_id")
    name: str | None = None
    enabled: bool | None = None
