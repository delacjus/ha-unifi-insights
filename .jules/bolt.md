## 2024-10-24 - [Avoid reallocating dictionaries in Python data transformations]
**Learning:** Frequent Python API response normalizations perform measurably worse when local dictionaries are re-allocated inside functions instead of using module-level constants.
**Action:** Always extract static mapping dictionaries from transformation functions to the module scope (as constants like `_DEVICE_STATUS_MAP`) to skip memory allocation on every record processed.
