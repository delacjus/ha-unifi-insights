## 2026-11-20 - Optimize unspecified IP address parsing

**Learning:** `ipaddress.ip_address` object instantiation and validation is computationally expensive, adding significant overhead when executed repeatedly in hot paths like network telemetry parsing.
**Action:** Avoid instantiating `ipaddress.ip_address` objects for simple IP state checks in hot paths. Use direct string matching (e.g., `value in ("0.0.0.0", "::")`) where applicable, suppressing Ruff warnings with `# noqa: S104` if necessary.
