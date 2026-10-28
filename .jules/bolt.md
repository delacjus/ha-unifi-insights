## 2026-10-27 - [Direct String Matching for IP Validation]

**Learning:** Instantiating `ipaddress.ip_address` in hot paths (like parsing rapid network telemetry data) creates significant validation overhead and slows down data transformations.
**Action:** Use direct string matching where applicable and append `# noqa: S104` to suppress Ruff's warning.
