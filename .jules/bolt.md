## 2026-10-19 - Optimize IP address validation
**Learning:** Instantiating `ipaddress.ip_address` objects in hot paths (e.g., parsing rapid network telemetry data) has a computationally expensive validation overhead.
**Action:** Avoid instantiating `ipaddress.ip_address` objects in hot paths and use direct string matching where applicable. When implementing direct string matching for unspecified IP addresses like '0.0.0.0' or '::', append `# noqa: S104` to suppress Ruff's 'Possible binding to all interfaces' warning.
