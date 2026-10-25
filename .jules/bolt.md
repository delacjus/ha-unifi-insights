## 2025-02-09 - Avoid ipaddress object instantiation in hot paths

**Learning:** Instantiating `ipaddress.ip_address` objects in hot paths (e.g., parsing rapid network telemetry data) has high validation overhead and is computationally expensive compared to string matching.
**Action:** Use direct string matching where applicable, appending `# noqa: S104` to suppress Ruff's "Possible binding to all interfaces" warning.
