## 2024-10-07 - Inefficient list comprehension in site health
**Learning:** The `build_site_health_snapshot` function in `site_health.py` used list comprehensions to count wired and wireless clients. This iterated over the entire clients list multiple times and created intermediate lists in memory just to get a count, which is O(N) space and multiple O(N) passes. We can use a single pass for loop which is faster and doesn't create intermediate lists.
**Action:** Replace multiple O(N) passes with a single pass O(N) loop.
