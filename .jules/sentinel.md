## 2026-10-18 - Redact API keys from Auth model reprs
**Vulnerability:** API keys were hardcoded into the `__repr__` of the `ApiKeyAuth` and `LocalAuth` dataclasses in `custom_components/unifi_insights/api/auth.py`. Since `api_key` was not excluded using `repr=False`, any print statement, logging, or exception traceback could accidentally expose the plaintext credentials.
**Learning:** Python's `@dataclass` automatically includes all fields in the `__repr__` output unless specifically disabled via `repr=False`. Even if a field holds a secret, it will be leaked if the dataclass is dumped.
**Prevention:** For any dataclass handling secrets, always pass `repr=False` in the decorator and override `__repr__` manually to redact sensitive information like passwords, tokens, or API keys.
