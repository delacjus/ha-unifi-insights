## 2024-10-24 - Secure Logging for Secret Node Keys
**Vulnerability:** Dataclasses containing sensitive cryptographic/secret keys (e.g., `_NodeKeys` in `custom_components/unifi_insights/topology_keys.py`) automatically generate a `__repr__` method that exposes all fields, risking accidental leakage of keys into system logs or exception stack traces.
**Learning:** Python's dataclass default `__repr__` is a silent leak vector for sensitive configuration and state data kept in memory.
**Prevention:** For any dataclass handling secrets, explicitly set `repr=False` in the decorator and provide a custom `__repr__` method to safely redact sensitive fields. Ensure temporary files used during development are cleaned up before final review/commits.
