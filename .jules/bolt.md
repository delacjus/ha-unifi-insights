## 2024-05-24 - [Avoid ipaddress object instantiation overhead]

**Learning:** Avoid instantiating `ipaddress.ip_address` objects in hot paths as the validation overhead is computationally expensive. Direct string matching is faster.
**Action:** Use direct string matching for '0.0.0.0' or '::' (with `# noqa: S104`) instead of `ipaddress.ip_address(value).is_unspecified`.
