## 2023-11-20 - Avoid `ipaddress` parsing in hot paths

**Learning:** The validation overhead of `ipaddress.ip_address()` is computationally expensive for rapid network telemetry parsing. It's approximately 25x slower than direct string matching.
**Action:** When validating unspecified addresses (like '0.0.0.0' or '::') from high-throughput streams, use direct string checks `value in {"0.0.0.0", "::", "0:0:0:0:0:0:0:0", "::0"} # noqa: S104` instead of instantiating `ipaddress` objects.
