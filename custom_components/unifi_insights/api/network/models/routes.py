"""Policy-Based Route (Traffic Route) models for UniFi Network API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PolicyBasedRoute(BaseModel):
    """
    Model representing a Policy-Based Route (Traffic Route) in UniFi Network.

    Traffic routes allow selective routing of traffic (by domain, IP, client,
    or network) out through a specific WAN interface or VPN Client.
    """

    id: str = Field(default="", alias="_id")
    description: str | None = None
    name: str | None = None
    enabled: bool = True
    target: str | None = None
    matching_target: str | None = Field(default=None, alias="matchingTarget")
    interface: str | None = None
    vpn_client_id: str | None = Field(default=None, alias="vpnClientId")
    kill_switch: bool | None = Field(default=None, alias="killSwitch")
    fall_back_to_default_wan: bool | None = Field(
        default=None, alias="fallBackToDefaultWAN"
    )
    domains: list[str] = Field(default_factory=list)
    ip_addresses: list[str] = Field(default_factory=list, alias="ipAddresses")
    ips: list[str] = Field(default_factory=list)
    client_macs: list[str] = Field(default_factory=list, alias="clientMacs")
    network_ids: list[str] = Field(default_factory=list, alias="networkIds")
    site_id: str | None = Field(default=None, alias="siteId")

    model_config = {"populate_by_name": True, "extra": "allow"}

    @property
    def display_name(self) -> str:
        """
        Return human-readable display name for the route.

        Falls back to description, name, matching target/interface, or route ID.
        """
        if self.description:
            return self.description
        if self.name:
            return self.name
        if self.matching_target and self.interface:
            return f"Route {self.matching_target} to {self.interface}"
        return f"Route {self.id}"
