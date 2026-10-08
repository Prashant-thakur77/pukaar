#!/usr/bin/env bash
# Setup script for Claude Code cloud sessions (see cloud/ENVIRONMENT.md).
# Installs the AWS CLI, SAM CLI, backend dev dependencies and frontend
# dependencies. The three installs run in parallel; the AWS tools are
# non-critical and never fail the script.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${TMPDIR:-/tmp}/pukaar-setup"
mkdir -p "$LOG_DIR"
export PATH="$HOME/.local/bin:$PATH"

pip_install() {
  python3 -m pip install --user --quiet --disable-pip-version-check "$@" 2>/dev/null \
    || python3 -m pip install --user --quiet --disable-pip-version-check --break-system-packages "$@"
}

install_aws_tools() {
  local tools=()
  command -v aws >/dev/null 2>&1 || tools+=(awscli)
  command -v sam >/dev/null 2>&1 || tools+=(aws-sam-cli)
  if [ "${#tools[@]}" -gt 0 ]; then
    pip_install "${tools[@]}"
  fi
}

install_backend() {
  cd "$ROOT/backend" && uv sync --frozen --extra dev
}

install_frontend() {
  cd "$ROOT/frontend" && npm ci --legacy-peer-deps --no-audit --no-fund --loglevel=error
}

start=$(date +%s)

# uv first, so the parallel jobs below never run two pip installs at once.
command -v uv >/dev/null 2>&1 || pip_install uv || true

( timeout 280 bash -c "$(declare -f pip_install install_aws_tools); install_aws_tools" \
    >"$LOG_DIR/aws.log" 2>&1 || true ) &
aws_pid=$!
install_backend >"$LOG_DIR/backend.log" 2>&1 &
backend_pid=$!
install_frontend >"$LOG_DIR/frontend.log" 2>&1 &
frontend_pid=$!

status=0
wait "$aws_pid" || true
if wait "$backend_pid"; then echo "backend: ok"; else echo "backend: FAILED (see $LOG_DIR/backend.log)"; status=1; fi
if wait "$frontend_pid"; then echo "frontend: ok"; else echo "frontend: FAILED (see $LOG_DIR/frontend.log)"; status=1; fi
command -v aws >/dev/null 2>&1 && echo "aws: $(aws --version 2>&1 | head -n 1)" || echo "aws: not installed (see $LOG_DIR/aws.log)"
command -v sam >/dev/null 2>&1 && echo "sam: $(sam --version 2>&1 | head -n 1)" || echo "sam: not installed (see $LOG_DIR/aws.log)"
echo "setup took $(( $(date +%s) - start ))s"
exit "$status"
