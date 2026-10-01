#!/usr/bin/env bash
# Seed a device from a remote content-addressed tree (say a server's cas/): rsync it into the device's root,
# then adopt it in place — every file is hashed against its own name before it is recorded.
#
#   REMOTE=user@host:/path/to/cas ROOT=~/.dizzy-store/laptop scripts/seed_from_remote.sh
#
# READ-ONLY on the remote (no --delete, nothing removed there), polite to it (niced, capped at BWLIMIT), and
# resumable: run it again after any interruption and it carries on; run it again after it finished and it copies
# only what is new. Over a slow link this is the long step — see `BWLIMIT`.
#
#   ROOT         the device root (the folder holding .store/); its daemon must be running
#   BWLIMIT      cap on the transfer, rsync syntax (default 2M = 2 MiB/s)
#   COLLECTION   what to call the blobs (default media)
#   REMOTE_RSYNC how to start rsync on the remote (default: nice -n 19 ionice -c3 rsync)
#   DRY_RUN=1    only say what would be copied
set -euo pipefail
REMOTE="${REMOTE:?set REMOTE=user@host:/path/to/the/remote/cas}"
ROOT="${ROOT:?set ROOT=the device root, the folder that holds .store/}"
BWLIMIT="${BWLIMIT:-2M}"
COLLECTION="${COLLECTION:-media}"
ROOT="$(cd "$ROOT" && pwd)"
[[ -f "$ROOT/.store/device.json" ]] || { echo "$ROOT is not a store device (no .store/device.json)" >&2; exit 2; }

TMP="$ROOT/.store/tmp/rsync"          # in-progress and interrupted files live inside the store's state, never in the blob tree
mkdir -p "$TMP"
RSYNC=(rsync -a --no-o --no-g --partial-dir="$TMP" --temp-dir="$TMP" --bwlimit="$BWLIMIT" --exclude='/tmp*' --stats
       -e "ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=30 -o ServerAliveCountMax=6"
       --rsync-path="${REMOTE_RSYNC:-nice -n 19 ionice -c3 rsync}")
[[ -t 1 ]] && RSYNC+=(--info=progress2)

if [[ -n "${DRY_RUN:-}" ]]; then
    "${RSYNC[@]}" -n "${REMOTE%/}/" "$ROOT/"
    exit 0
fi
dizzy-store --root "$ROOT" status >/dev/null || { echo "the device at $ROOT is not answering — start it first" >&2; exit 3; }

for attempt in 1 2 3 4 5 6 7 8; do
    if "${RSYNC[@]}" "${REMOTE%/}/" "$ROOT/"; then break; fi
    [[ $attempt == 8 ]] && { echo "rsync keeps failing — run this again to resume" >&2; exit 1; }
    echo "rsync stopped (attempt $attempt) — resuming in 30s" >&2
    sleep 30
done
dizzy-store --root "$ROOT" cmd adopt_collection collection="$COLLECTION" root="$ROOT" layout=cas
echo "adopted. Next: let the other devices catch up (dizzy-store -d NAME run --until-idle), then check the copies"
echo "with scripts/cold_verify.py ROOT and scripts/compare_manifests.py."
