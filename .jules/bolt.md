## 2024-05-18 - [Avoid ipaddress in hot paths]

**Learning:** Using `ipaddress.ip_address(value).is_unspecified` inside hot paths (e.g. processing rapid network telemetry or frequently validating unspecified IPs) is computationally expensive due to validation overhead. Simple string matching is roughly ~50x-80x faster.
**Action:** Avoid instantiating `ipaddress.ip_address` objects for simple matching logic against known string literals (like "0.0.0.0" or "::") when parsing high-volume data. Use `value in ("0.0.0.0", "::")` instead, and append `# noqa: S104` to suppress Ruff's "Possible binding to all interfaces" warning.
