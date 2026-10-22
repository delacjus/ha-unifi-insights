## 2026-10-22 - [Dataclass Secret Leakage]

**Vulnerability:** Dataclasses holding sensitive keys/tokens (like `_NodeKeys` holding hex keys in `custom_components/unifi_insights/topology.py`) can leak secrets via their default `__repr__` method in logs or debugging output.
**Learning:** Python's `@dataclass` generates a `__repr__` by default which prints all attributes, exposing keys if not handled.
**Prevention:** Always use `@dataclass(repr=False)` or explicit field `repr=False` for fields storing secrets, and define a custom `__repr__` method to redact secrets in logs.
