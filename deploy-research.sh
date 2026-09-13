#!/usr/bin/env bash
set -Eeuo pipefail

# Research-ASL production deploy/restart script.
# Run on asl-server from the repository root:
#   bash deploy-research.sh [auto|full|fast|restart]
#
# Configure with environment variables when the server differs from defaults:
#   REPO_DIR="$HOME/research-asl"
#   SERVICE_NAME="research-asl.service"
#   PUBLIC_URL="https://research.appliedsentiencelabs.com"
#   HEALTH_PATH="/sitemap.xml"

MODE="${1:-auto}"
case "$MODE" in
  auto|full|fast|restart) ;;
  -h|--help)
    printf 'Usage: bash deploy-research.sh [auto|full|fast|restart]\n'
    printf '  auto    Pull and install only when repository files changed.\n'
    printf '  full    Pull, recreate the virtualenv, and install dependencies.\n'
    printf '  fast    Restart the service without pulling or installing.\n'
    printf '  restart Same as fast.\n'
    exit 0
    ;;
  *)
    printf 'Unknown mode: %s\n' "$MODE" >&2
    exit 1
    ;;
esac

REPO_DIR="${REPO_DIR:-$HOME/research-asl}"
SERVICE_NAME="${SERVICE_NAME:-research-asl.service}"
VENV_DIR="${VENV_DIR:-$REPO_DIR/.venv}"
PUBLIC_URL="${PUBLIC_URL:-https://research.appliedsentiencelabs.com}"
HEALTH_PATH="${HEALTH_PATH:-/sitemap.xml}"
HEALTH_URL="${PUBLIC_URL%/}${HEALTH_PATH}"
GIT_BRANCH="${GIT_BRANCH:-main}"

log() { printf '\n[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
trap 'fail "Deployment failed at line $LINENO."' ERR

cd "$REPO_DIR" 2>/dev/null || fail "Repository directory does not exist: $REPO_DIR"
command -v python3 >/dev/null 2>&1 || fail "python3 is not installed or not on PATH."
command -v systemctl >/dev/null 2>&1 || fail "systemctl is required for this deployment script."
test -f requirements.txt || fail "Missing requirements.txt"
test -f app.py || fail "Missing app.py"

HAS_GIT=0
if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  HAS_GIT=1
fi

restart_service() {
  log "Restarting $SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"
  systemctl is-active --quiet "$SERVICE_NAME" || {
    systemctl --no-pager --full status "$SERVICE_NAME" || true
    fail "$SERVICE_NAME is not active."
  }
}

if [ "$MODE" = "fast" ] || [ "$MODE" = "restart" ]; then
  restart_service
else
  BEFORE=''
  AFTER=''
  if [ "$HAS_GIT" -eq 1 ]; then
    log "Checking repository state"
    [ -z "$(git status --porcelain)" ] || fail "Working tree has uncommitted or untracked changes. Commit or stash them before deployment."
    BEFORE="$(git rev-parse HEAD)"
    log "Updating code"
    git pull --rebase origin "$GIT_BRANCH"
    AFTER="$(git rev-parse HEAD)"
  else
    log "No Git repository detected; using the files already installed in $REPO_DIR"
    AFTER='manual-deploy'
  fi

  if [ "$MODE" = "full" ] || [ "$BEFORE" != "$AFTER" ]; then
    if [ "$MODE" = "full" ]; then
      log "Recreating virtual environment"
      rm -rf "$VENV_DIR"
    else
      log "Code changed; updating Python dependencies"
    fi
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/python" -m pip install --upgrade pip
    "$VENV_DIR/bin/python" -m pip install -r requirements.txt
  else
    log "No repository changes detected; skipping dependency installation"
  fi

  log "Validating application syntax"
  "$VENV_DIR/bin/python" -m compileall -q app.py
  "$VENV_DIR/bin/python" -c "from app import app; client = app.test_client(); assert client.get('/').status_code == 200; response = client.get('/sitemap.xml'); assert response.status_code == 200 and response.content_type.startswith('application/xml'); print('application smoke test passed')"
  restart_service
fi

log "Checking public endpoint: $HEALTH_URL"
command -v curl >/dev/null 2>&1 || fail "curl is not installed or not on PATH."
curl --fail --silent --show-error --max-time 20 "$HEALTH_URL" >/dev/null

log "Deployment completed successfully"
