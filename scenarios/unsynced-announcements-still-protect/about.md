Eviction trusts a peer's LIVE role and draining state, not what the log last said about it.
tags: eviction, safety, live-proof, principle-7, found-by-mutation
The log lags: a peer can begin draining, or be reclassified a cold drive, before the evicting
node has merged the announcement. The proof request returns the peer's own current card.
