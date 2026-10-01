Re-running an adoption costs a directory walk: names already held are not re-read.
tags: adopt, idempotence, cron, from-independent-review
A 30k-file tree re-hashed in full on every run would make "adopt" unusable on a schedule.
Proved without a spy: the originals are made unreadable, so any re-read would fail the step.
