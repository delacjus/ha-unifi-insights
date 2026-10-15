## 2024-05-18 - [API Base Missing Redaction Keys]
**Vulnerability:** Redaction of sensitive fields in `_SENSITIVE_KEYS` and `_SENSITIVE_KEYS_RE` of `custom_components/unifi_insights/api/base.py` missed some keys present in `diagnostics.py` such as `access_token` and `x_passphrase` which could lead to sensitive data exposure in logs.
**Learning:** Security updates in diagnostic redactions are not always propagated to API log redactions. Both need to be kept in sync.
**Prevention:** Unify sensitive key lists where possible or establish a process to update both simultaneously.
