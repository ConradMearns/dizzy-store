"""Exit statuses (sysexits.h), shared by the CLI and the daemon so systemd's unit can rely on them."""
EX_IOERR = 74       # the store's disk vanished while it was running
EX_TEMPFAIL = 75    # `run --until-idle` could not finish: no peer reachable, or what it wants is not to be had — try again
EX_CONFIG = 78      # a configuration problem a restart cannot fix: no such store, an unmounted drive, a port or store already taken
