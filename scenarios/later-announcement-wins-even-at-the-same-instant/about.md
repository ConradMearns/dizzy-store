A device's own later fact beats its earlier one even when the clock has not moved.
tags: lww, clock, announce, found-by-http-conformance
Last-writer-wins on occurred_at used a payload-digest tie-break, so two announcements
at the same instant were decided by a hash coin flip — which depended on the random
port in the card, making the draining scenario flaky over HTTP only. A device now
issues LWW facts strictly after its own previous one for the subject (also protects
against an NTP step backwards).
