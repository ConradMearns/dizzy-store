link: true shares bytes with the original; a broken promise is caught and repaired.
tags: adopt, link, scrub, repair, principle-5, found-by-independent-review
Hard links cost no space (the point, for a nearly full disk). The price is that an
in-place edit of the original reaches the blob too. The content address makes that
loud: scrub quarantines the changed bytes and the sweep fetches the right ones back.
