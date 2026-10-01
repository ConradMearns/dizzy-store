Blobs nobody can supply right now must not starve the ones that can be fetched.
tags: sweep, pacing, backoff, principle-9, found-by-independent-review
With a per-tick cap of 2 and the two newest blobs unfetchable, older blobs never arrived.
The sweep now remembers failures and backs off, so progress goes on behind them.
