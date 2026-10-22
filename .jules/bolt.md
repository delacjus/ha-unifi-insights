## 2024-10-22 - [Optimize unspecified IP address check]

**Learning:** Instantiating `ipaddress.ip_address` objects in hot paths (e.g., parsing rapid network telemetry data) causes significant overhead because the validation is computationally expensive.
**Action:** Use direct string matching where applicable, such as checking for known unspecified addresses like "0.0.0.0" and "::", instead of parsing the IP string to an object first.
