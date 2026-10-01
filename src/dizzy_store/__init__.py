"""dizzy_store — the runtime glue around store.feat.yaml's generated library.

Nothing here knows what a blob_stored is: wiring.py reads the feat. The pieces:
  wiring  — feat graph -> a registered Engine (convention-driven, no hand mirror)
  node    — one device: event store + read models + blob root + engine
  sim     — an in-process cluster: nodes, a network that can partition, a clock
  sweep   — the paced catch-up tick (product code: the daemon and scenarios share it)
"""

from . import _kit  # noqa: F401,E402  — puts the feature's lib + the runtime kit on sys.path first
