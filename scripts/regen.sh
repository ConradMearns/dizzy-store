#!/usr/bin/env bash
# Re-author def/ from the feat, then regenerate gen_def/ and gen_int/ with the PINNED DIZZY
# generator — ext/dizzy's own venv, not the `dizzy` uv tool, which tracks a newer checkout
# (it emits an `attempt` field in contexts that the pinned engine does not know).
#
#   store/scripts/regen.sh          # from anywhere
set -euo pipefail
STORE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(cd "$STORE/.." && pwd)"
DIZZY="$REPO/ext/dizzy/.venv/bin/dizzy"
[ -x "$DIZZY" ] || { echo "no $DIZZY — run 'just dizzy-init' (and 'uv sync' in ext/dizzy)" >&2; exit 1; }

python3 "$STORE/scripts/author_defs.py"

# generate in a scratch copy, then mirror into lib/python-uv (so a failed run leaves nothing half-written)
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
cp "$STORE/store.feat.yaml" "$STORE/libconfig.yaml" "$TMP/" && cp -r "$STORE/def" "$TMP/def"
(cd "$TMP" && PATH="$REPO/ext/dizzy/.venv/bin:$PATH" "$DIZZY" generate static store.feat.yaml . | tail -1)
for pkg in gen_def gen_int; do
  rsync -a --delete --exclude __pycache__ "$TMP/lib/python-uv/$pkg/" "$STORE/lib/python-uv/$pkg/"
done
echo "regenerated gen_def and gen_int from store.feat.yaml"
