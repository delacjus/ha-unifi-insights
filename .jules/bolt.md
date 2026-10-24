## 2023-10-24 - Avoid ipaddress object instantiation in hot paths
**Learning:** Found that `ipaddress.ip_address` instantiation is extremely slow. For checking if an address is unspecified ("0.0.0.0" or "::"), using a simple string `in` check is ~43x faster than parsing the IP address.
**Action:** When validating specific IP addresses like "0.0.0.0", use direct string matching and append `# noqa: S104` to bypass Ruff's "Possible binding to all interfaces" warning.
