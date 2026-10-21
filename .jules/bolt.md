## 2026-10-20 - Exception handling in hot paths

**Learning:** Checking for an unspecified IP address (0.0.0.0 / ::) via `try/except ipaddress.ip_address(value).is_unspecified` creates unnecessary CPU overhead in hot parsing routines for valid IP addresses (they raise and catch `ValueError`).
**Action:** Use direct string matching `value in ("0.0.0.0", "::")` and `# noqa: S104` for IP validations when exact values are expected.
