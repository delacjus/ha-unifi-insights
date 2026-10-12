## 2024-05-19 - [O(N) vs O(N^2) data merging]

**Learning:** In the Home Assistant coordinator pattern, mapping clients to devices in `_process_site` and passing the map to `_process_device` provides a massive O(1) performance boost instead of doing an O(N) scan inside the loop, especially for large network data.
**Action:** Always pre-calculate maps (like `clients_by_uplink`) before looping through related items.
