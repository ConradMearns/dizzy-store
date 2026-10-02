min_evict_bytes protects small blobs from PRESSURE only; a node that is leaving still empties itself, small blobs included.
tags: drain, eviction, min-evict-bytes, principle-7, principle-11
Like "a collection it WANTS in full", the exemption is a pressure rule. If it held back a draining node, the drive could
never be unplugged: get_drain_remaining would stay above zero for blobs the device itself decided to keep.
