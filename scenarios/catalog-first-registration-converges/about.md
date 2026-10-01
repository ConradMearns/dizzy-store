Two devices registering the same bytes concurrently converge on one catalog row.
tags: convergence, catalog, lww, principle-3, found-by-independent-review
The catalog was first-FOLDED-wins, so after full sync a and b disagreed forever about the
blob's collection (and therefore its policy). It now keeps the earliest registration by
(occurred_at, payload digest), whatever order a node folds in.
