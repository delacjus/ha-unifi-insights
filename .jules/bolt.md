## 2026-10-10 - Optimizing normalize_mac

**Learning:** `normalize_mac` in `custom_components/unifi_insights/topology_contract.py` is called very frequently during topology polling. Adding a fast path to avoid regex and string manipulation for already normalized MAC addresses provides a significant performance improvement.

**Action:** Look for string manipulation functions that are heavily utilized in loops and add fast paths for the most common input format if they don't already exist.
