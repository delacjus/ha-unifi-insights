"""NAT rule data model for UniFi Network API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class NatRule(BaseModel):
    """
    Custom NAT rule in UniFi Network (v2 ``/nat``).

    Reference shape, not observed on a live console (0 records on Network 11,
    2026-10-12). Keys per the sirkirby/unifi-mcp Network 10.6 fixture:
    _id, description, destination_filter, enabled, exclude, in_interface,
    ip_address, ip_version, is_predefined, logging, port, pppoe_use_base_interface,
    protocol, rule_index, setting_preference, source_filter, type.

    Only id, description and enabled are declared; every other key is kept as an
    extra so a type change on the controller cannot make a record fail validation
    (a skipped record would look deleted to the switch orphan prune).
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = Field(alias="_id")
    description: str | None = None
    enabled: bool | None = None
