## 2026-10-19 - IP Address Validation Bottleneck

**Learning:** The `ipaddress.ip_address(value).is_unspecified` function in Python is surprisingly slow due to extensive internal validation on instantiation. In hot paths like `_is_unspecified_address` (used heavily during gateway WAN status parsing), this object instantiation becomes a measurable bottleneck.
**Action:** When a known finite set of valid canonical IP strings (e.g., `"0.0.0.0"`, `"::"`) can be expected (like placeholder downlinks from UniFi), replace `ipaddress` instantiation with direct tuple string membership checks `value in ("0.0.0.0", "::", "0:0:0:0:0:0:0:0")` for an easy >40x performance gain.
