## 2023-10-19 - [Data Class Repr Leaking Secrets]

**Vulnerability:** The `ApiKeyAuth` and `LocalAuth` dataclasses holding sensitive API keys leaked those keys when their `repr()` was evaluated.
**Learning:** Default `@dataclass` without `repr=False` outputs all properties in plain text. Since these are commonly used for auth and configurations, this causes API keys to be visible in logs or tracebacks.
**Prevention:** Always use `repr=False` in `@dataclass` decorators when holding sensitive values (API keys, passwords, tokens) and implement a custom `__repr__` method that redacts them (e.g., using `**REDACTED**`).
