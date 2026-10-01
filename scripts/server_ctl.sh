#!/usr/bin/env bash
# Deploy / tear down the store TEST device on the server. Everything lives under
# /opt/dizzy-store-test (including uv's package cache), plus one transient systemd
# unit — `teardown` removes all of it. The logger's data and services are untouched.
#
#   server_ctl.sh preflight | deploy | teardown | verify-clean
set -euo pipefail
IP="${SERVER_IP:?set SERVER_IP to the address of the remote test machine (it is reached over ssh as root)}"
R=/opt/dizzy-store-test
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SSH=(ssh -o ConnectTimeout=15 "root@$IP")

case "${1:?usage: server_ctl.sh preflight|deploy|teardown|verify-clean}" in
  preflight)
    "${SSH[@]}" 'df -h / | tail -1; free -m | sed -n 2p; systemctl is-active dizzy-logger dizzy-workers caddy redis-server; ls -d /opt/dizzy-store-test 2>/dev/null || echo "(no previous test dir)"'
    ;;

  deploy)
    "${SSH[@]}" "mkdir -p $R/store $R/ext/dizzy $R/dagstore $R/host $R/data $R/.uvcache"
    cd "$REPO"
    EX=(--exclude .venv --exclude __pycache__ --exclude '*.pyc' --exclude .pytest_cache)
    rsync -az --delete "${EX[@]}" --exclude tests --exclude scenarios store/ "root@$IP:$R/store/"
    rsync -az --delete "${EX[@]}" --exclude .git --exclude docs --exclude examples ext/dizzy/ "root@$IP:$R/ext/dizzy/"
    rsync -az --delete "${EX[@]}" --exclude tests dagstore/ "root@$IP:$R/dagstore/"
    rsync -az host/engine.py host/store.py host/replicate.py "root@$IP:$R/host/"
    # reuse an interpreter that is already on the box (no Python download left behind)
    PY=$("${SSH[@]}" 'readlink -f /opt/dizzy-logger/host/.venv/bin/python')
    echo "python on server: $PY"
    # no git on the box: dizzy takes its version from git tags (hatch-vcs), so pretend one
    if ! OUT=$("${SSH[@]}" "cd $R && SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 UV_CACHE_DIR=$R/.uvcache /root/.local/bin/uv sync --frozen --project store --no-dev --python $PY" 2>&1); then
      echo "uv sync FAILED on the server:" >&2; echo "$OUT" >&2; exit 1
    fi
    echo "$OUT" | tail -3
    "${SSH[@]}" "cat > /etc/systemd/system/dizzy-store-test.service" <<EOF
[Unit]
Description=dizzy-store TEST device (temporary — see /opt/dizzy-store-test)
After=network.target

[Service]
Type=simple
WorkingDirectory=$R
Environment=PYTHONPATH=$R/store/src
Environment=UV_CACHE_DIR=$R/.uvcache
Environment=SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0
ExecStart=/root/.local/bin/uv run --frozen --no-dev --project store python -m dizzy_store --root $R/data run
Restart=on-failure
RestartSec=3
MemoryMax=300M
Nice=10
EOF
    "${SSH[@]}" "systemctl daemon-reload && du -sh $R"
    ;;

  teardown)
    "${SSH[@]}" "systemctl stop dizzy-store-test 2>/dev/null || true; systemctl reset-failed dizzy-store-test 2>/dev/null || true; rm -f /etc/systemd/system/dizzy-store-test.service; systemctl daemon-reload; rm -rf $R"
    ;;

  verify-clean)
    "${SSH[@]}" "echo 'dir:  '\$(ls -d $R 2>&1 | tail -1); echo 'unit: '\$(systemctl list-unit-files | grep -c dizzy-store-test) ; echo 'ports:'; ss -ltn | grep -E ':(7701|7702)\b' || echo '  (none listening)'; df -h / | tail -1; systemctl is-active dizzy-logger dizzy-workers caddy redis-server | tr '\n' ' '; echo"
    ;;
esac
