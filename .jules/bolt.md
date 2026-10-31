## 2023-10-31 - [Direct string matching over ipaddress module]
**Learning:** Avoid instantiating `ipaddress.ip_address` objects in hot paths (like checking if an IP is "0.0.0.0" or "::") as the validation overhead is computationally expensive.
**Action:** Use direct string matching where applicable for unspecified IP checks.
