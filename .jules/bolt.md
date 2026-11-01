## 2026-10-31 - [Avoid ipaddress instantiation in hot paths]
**Learning:** Instantiating `ipaddress.ip_address` objects is computationally expensive and creates a bottleneck when parsing rapid network telemetry data where IP address validity checks are frequent.
**Action:** Use direct string matching (e.g., `value in ("0.0.0.0", "::")  # noqa: S104`) instead of `ipaddress` objects for simple validity or equivalence checks on unspecified IPs in hot paths.
