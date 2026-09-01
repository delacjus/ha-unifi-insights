"""Traffic Route (Policy-Based Routing) models for UniFi Network API."""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, Field, model_validator


class TrafficRouteTargetDevice(BaseModel):
    """Target device/network model for a traffic route."""

    type: str | None = Field(
        default=None, description="Target type, e.g. NETWORK, CLIENT, DEVICE"
    )
    client_mac: str | None = Field(
        default=None, alias="clientMac", description="Client MAC address"
    )
    device_mac: str | None = Field(
        default=None, alias="deviceMac", description="Device MAC address"
    )
    network_id: str | None = Field(
        default=None, alias="networkId", description="Target network ID"
    )
    ip_address: str | None = Field(
        default=None, alias="ipAddress", description="Target IP address"
    )

    model_config = {"populate_by_name": True, "extra": "allow"}


class TrafficRoute(BaseModel):
    """Canonical UniFi Traffic Route (Policy-Based Routing) model."""

    id: str | None = Field(default=None, alias="_id", description="Route ID")
    name: str | None = Field(default=None, description="Descriptive route name")
    description: str | None = Field(
        default=None, description="Route description / name from controller"
    )
    enabled: bool = Field(default=True, description="Whether the route is enabled")
    matching_target: str | None = Field(
        default=None,
        alias="matchingTarget",
        description="Matching target type (e.g. INTERNET, DOMAIN, IP, REGION)",
    )
    network_id: str | None = Field(
        default=None,
        alias="networkId",
        description="Network ID the route applies to",
    )
    target_devices: list[TrafficRouteTargetDevice] = Field(
        default_factory=list,
        alias="targetDevices",
        description="Target devices/networks the route applies to",
    )
    domains: list[Any] = Field(
        default_factory=list,
        description="List of domains with ports (used with matching_target: DOMAIN)",
    )
    ip_addresses: list[Any] = Field(
        default_factory=list,
        alias="ipAddresses",
        description="List of IPs/subnets with ports (used with matching_target: IP)",
    )
    ip_ranges: list[Any] = Field(
        default_factory=list,
        alias="ipRanges",
        description="List of IP ranges (used with matching_target: IP)",
    )
    regions: list[str] = Field(
        default_factory=list,
        description="List of regions (used with matching_target: REGION)",
    )
    kill_switch_enabled: bool = Field(
        default=False,
        alias="killSwitchEnabled",
        description="Whether kill switch is active (blocks traffic if VPN drops)",
    )
    next_hop: str | None = Field(
        default=None,
        alias="nextHop",
        description="Next hop IP or interface identifier",
    )
    interface: str | None = Field(
        default=None,
        description="Egress interface (e.g., WAN1, WAN2, VPN interface)",
    )
    route_type: str | None = Field(
        default=None,
        alias="routeType",
        description="Route type classification",
    )
    fall_back_type: str | None = Field(
        default=None,
        alias="fallBackType",
        description="Fallback type if primary interface fails",
    )
    site_id: str | None = Field(
        default=None,
        alias="siteId",
        description="Site ID the route belongs to",
    )

    model_config = {"populate_by_name": True, "extra": "allow"}

    @model_validator(mode="after")
    def populate_fallbacks(self) -> Self:
        """Populate name fallback from description if not set and vice versa."""
        if not self.name and self.description:
            self.name = self.description
        elif not self.description and self.name:
            self.description = self.name
        return self
