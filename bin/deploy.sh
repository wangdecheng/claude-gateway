#!/usr/bin/env bash
# bin/deploy.sh — Sync cloude-gateway code to 47.103.206.6 and restart services.
#
# Run from anywhere — the script locates the repo root by looking for
# backend/ and frontend/ near the script (or in $PWD).
#
# Usage:
#   bin/deploy.sh                  # full deploy: sync + install + migrate + build + restart
#   bin/deploy.sh --backend        # backend only
#   bin/deploy.sh --frontend       # frontend only
#   bin/deploy.sh --skip-build     # don't rebuild frontend .next/
#   bin/deploy.sh --no-restart     # sync + install + migrate + build, but skip restarts
#   bin/deploy.sh --dry-run        # print what would happen, change nothing
#
# Override defaults via env vars:
#   DEPLOY_REMOTE             ssh destination (default root@47.103.206.6)
#   DEPLOY_SSH_KEY            path to SSH key (default $HOME/ai/aliyun-ai01.pem)
#   DEPLOY_REMOTE_DIR         remote install path (default /opt/cloude-gateway)
#   DEPLOY_BACKEND_SERVICE    systemd unit (default cloude-backend.service)
#   DEPLOY_FRONTEND_SERVICE   systemd unit (default cloude-frontend.service)

set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────
REMOTE_HOST="${DEPLOY_REMOTE:-root@47.103.206.6}"
SSH_KEY="${DEPLOY_SSH_KEY:-$HOME/ai/aliyun-ai01.pem}"
REMOTE_DIR="${DEPLOY_REMOTE_DIR:-/opt/cloude-gateway}"
BACKEND_SVC="${DEPLOY_BACKEND_SERVICE:-cloude-backend.service}"
FRONTEND_SVC="${DEPLOY_FRONTEND_SERVICE:-cloude-frontend.service}"

# ── Locate repo root ────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if   [ -d "$SCRIPT_DIR/../backend" ] && [ -d "$SCRIPT_DIR/../frontend" ]; then
  REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
elif [ -d "$PWD/backend" ] && [ -d "$PWD/frontend" ]; then
  REPO_ROOT="$PWD"
else
  printf '\033[31mERROR\033[0m: cannot locate repo root (looked for backend/ + frontend/)\n' >&2
  exit 1
fi

# ── Args ─────────────────────────────────────────────────────────────
BACKEND=1; FRONTEND=1
SKIP_BUILD=0; DRY_RUN=0; NO_RESTART=0
print_help() {
  sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}
for arg in "$@"; do
  case "$arg" in
    --backend)      FRONTEND=0 ;;
    --frontend)     BACKEND=0 ;;
    --skip-build)   SKIP_BUILD=1 ;;
    --no-restart)   NO_RESTART=1 ;;
    --dry-run)      DRY_RUN=1 ;;
    -h|--help)      print_help 0 ;;
    *)              printf '\033[31mERROR\033[0m: unknown arg: %s\n' "$arg" >&2; print_help 1 ;;
  esac
done

# ── Pretty output ───────────────────────────────────────────────────
if [ "$DRY_RUN" = 1 ]; then
  C_TAG='[dry-run]'
else
  C_TAG='▶'
fi
say() { printf '\033[36m%s\033[0m %s\n' "$C_TAG" "$*"; }
warn() { printf '\033[33m⚠\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31m✖\033[0m %s\n' "$*" >&2; exit 1; }

# ── Pre-flight ──────────────────────────────────────────────────────
# Helpers used by the pre-flight checks.
RSYNC_SSH=( -e "ssh -i $SSH_KEY -o BatchMode=yes -o ConnectTimeout=10" )
SSH=( ssh -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=10 "$REMOTE_HOST" )

[ -f "$SSH_KEY" ] || die "SSH key not found: $SSH_KEY (set DEPLOY_SSH_KEY to override)"
command -v rsync >/dev/null 2>&1 || die "rsync not installed locally"
say "repo root: $REPO_ROOT"
say "remote:    $REMOTE_HOST -> $REMOTE_DIR"
say "ssh key:   $SSH_KEY"

# Ensure rsync is on the remote; install via the appropriate package
# manager (apt-get for Debian/Ubuntu, dnf/yum for RHEL/Alma/Anolis).
if [ "$DRY_RUN" = 1 ]; then
  say "[dry-run] would check rsync on remote (and install via apt/dnf/yum if missing)"
else
  if ! "${SSH[@]}" 'command -v rsync >/dev/null 2>&1'; then
    warn "rsync not on remote; installing via system package manager"
    "${SSH[@]}" 'if command -v apt-get >/dev/null 2>&1; then
        DEBIAN_FRONTEND=noninteractive apt-get update -qq && \
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq rsync
      elif command -v dnf >/dev/null 2>&1; then
        dnf install -y -q rsync
      elif command -v yum >/dev/null 2>&1; then
        yum install -y -q rsync
      else
        echo "ERROR: no supported package manager (apt-get/dnf/yum) found" >&2
        exit 1
      fi'
  fi
fi
echo

# ── Helpers ──────────────────────────────────────────────────────────

# Common exclusions for backend/ and frontend/ — keep secrets, build artifacts,
# caches, and the local .env on the remote untouched.
common_excludes=(
  --exclude '.git/'
  --exclude '.venv/' --exclude 'venv/' --exclude 'env/'
  --exclude 'node_modules/' --exclude '.next/'
  --exclude '__pycache__/' --exclude '*.py[cod]' --exclude '*.egg-info/'
  --exclude '.env' --exclude '.env.*.local' --exclude '.env.production'
  --exclude '.env.local' --exclude '.env.development'
  --exclude '.pytest_cache/' --exclude '.mypy_cache/' --exclude '.ruff_cache/'
  --exclude '.cache/' --exclude '.npm/' --exclude '.next/cache/'
  --exclude 'htmlcov/' --exclude 'coverage/' --exclude 'dist/' --exclude 'build/'
  --exclude '*.log' --exclude '*.tmp' --exclude '*.bak' --exclude '*.bak-*'
  --exclude '.DS_Store' --exclude '*.tsbuildinfo'
  --exclude '.codegraph/' --exclude '.understand-anything/'
  --exclude 'secrets/'  # remote-generated JWT keys; never overwrite from local
)

backend_extras=(
  --exclude 'tests/'  # runtime doesn't need tests; sync manually if you must
  --exclude '*.db' --exclude 'test.db'
  --exclude 'alembic/versions/__pycache__/'
)

frontend_extras=(
  --exclude '.turbo/'  # turbopack cache (if used)
  --exclude 'tests/'   # tests aren't needed at runtime
  --exclude 'playwright-report/'
  --exclude 'test-results/'
)

# ── Step 1: rsync backend ───────────────────────────────────────────
# Extract "--exclude 'PATTERN'" pairs from $@ and print patterns, one per
# line.  Used by both the real rsync invocation and the dry-run find sim.
extract_patterns() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --exclude) shift; printf '%s\n' "$1" ;;
      *) shift ;;
    esac
  done
}

# Build a find predicate that prunes the same patterns rsync would.
# rsync's pattern is matched anywhere in the path; to mirror that with
# find we add both -path '*/PATTERN/*' (skip contents of matching dirs)
# and -name 'PATTERN' (skip the matching entry itself).
# Glob patterns like "*.pyc" get the -name branch only; -path would not
# match them usefully.
build_predicate() {
  predicate=()
  while IFS= read -r pat; do
    [ -z "$pat" ] && continue
    case "$pat" in
      \**)
        # Glob — match by basename only
        predicate+=( -name "$pat" -o ) ;;
      *)
        # Directory / exact name — match both the entry and anything inside it
        # Strip any trailing slash for the -name test
        trimmed="${pat%/}"
        predicate+=( -name "$trimmed" -o -path "*/$pat" -o -path "*/$trimmed" -o )
        ;;
    esac
  done
  # Drop the trailing -o
  if [ ${#predicate[@]} -gt 0 ]; then
    unset 'predicate[${#predicate[@]}-1]'
  fi
}

if [ "$BACKEND" = 1 ]; then
  say "syncing backend/ → $REMOTE_HOST:$REMOTE_DIR/backend/"
  extract_patterns "${common_excludes[@]}" "${backend_extras[@]}" > /tmp/.deploy-pats
  if [ "$DRY_RUN" = 1 ]; then
    build_predicate < /tmp/.deploy-pats
    if [ ${#predicate[@]} -gt 0 ]; then
      count=$(find "$REPO_ROOT/backend" \( "${predicate[@]}" \) -prune -o -type f -print | wc -l | tr -d ' ')
      say "  (dry-run) would transfer $count files; first 40:"
      find "$REPO_ROOT/backend" \( "${predicate[@]}" \) -prune -o -type f -print \
        | sed "s|^$REPO_ROOT/backend/||" | head -40 | sed 's/^/    /'
    else
      say "  (dry-run) no excludes; would transfer everything in backend/"
    fi
  else
    rsync -a --delete \
      "${common_excludes[@]}" "${backend_extras[@]}" \
      "${RSYNC_SSH[@]}" \
      "$REPO_ROOT/backend/" "$REMOTE_HOST:$REMOTE_DIR/backend/"
  fi
  echo
fi

# ── Step 2: rsync frontend ──────────────────────────────────────────
if [ "$FRONTEND" = 1 ]; then
  say "syncing frontend/ → $REMOTE_HOST:$REMOTE_DIR/frontend/"
  extract_patterns "${common_excludes[@]}" "${frontend_extras[@]}" > /tmp/.deploy-pats
  if [ "$DRY_RUN" = 1 ]; then
    build_predicate < /tmp/.deploy-pats
    if [ ${#predicate[@]} -gt 0 ]; then
      count=$(find "$REPO_ROOT/frontend" \( "${predicate[@]}" \) -prune -o -type f -print | wc -l | tr -d ' ')
      say "  (dry-run) would transfer $count files; first 40:"
      find "$REPO_ROOT/frontend" \( "${predicate[@]}" \) -prune -o -type f -print \
        | sed "s|^$REPO_ROOT/frontend/||" | head -40 | sed 's/^/    /'
    else
      say "  (dry-run) no excludes; would transfer everything in frontend/"
    fi
  else
    rsync -a --delete \
      "${common_excludes[@]}" "${frontend_extras[@]}" \
      "${RSYNC_SSH[@]}" \
      "$REPO_ROOT/frontend/" "$REMOTE_HOST:$REMOTE_DIR/frontend/"
  fi
  echo
fi

# ── Step 2.5: rsync bin/ (deploy tooling + runtime config) ────────
# bin/ holds deploy.sh itself (local-only orchestrator) plus runtime
# config that lives next to the deployer — currently the systemd
# unit files for cloude-cleanup.{service,timer}. Skip deploy.sh so
# we never overwrite the script that's currently running.
bin_excludes=(
  --exclude 'deploy.sh'
)
if [ "$DRY_RUN" = 1 ]; then
  say "syncing bin/ → $REMOTE_HOST:$REMOTE_DIR/bin/  (skip deploy.sh)"
  extract_patterns "${common_excludes[@]}" "${bin_excludes[@]}" > /tmp/.deploy-pats
  build_predicate < /tmp/.deploy-pats
  if [ ${#predicate[@]} -gt 0 ]; then
    count=$(find "$REPO_ROOT/bin" \( "${predicate[@]}" \) -prune -o -type f -print | wc -l | tr -d ' ')
    say "  (dry-run) would transfer $count files; first 40:"
    find "$REPO_ROOT/bin" \( "${predicate[@]}" \) -prune -o -type f -print \
      | sed "s|^$REPO_ROOT/bin/||" | head -40 | sed 's/^/    /'
  else
    say "  (dry-run) no excludes; would transfer everything in bin/"
  fi
else
  rsync -a --delete \
    "${common_excludes[@]}" "${bin_excludes[@]}" \
    "${RSYNC_SSH[@]}" \
    "$REPO_ROOT/bin/" "$REMOTE_HOST:$REMOTE_DIR/bin/"
fi
echo

# ── Step 3: remote post-sync commands ───────────────────────────────
if [ "$DRY_RUN" = 1 ]; then
  say "DRY-RUN: skipping remote install / migrate / build / restart"
  exit 0
fi

if [ "$BACKEND" = 1 ]; then
  say "[remote] backend: uv sync + alembic upgrade head"
  "${SSH[@]}" bash -s -- "$REMOTE_DIR" <<'REMOTE'
set -e
REMOTE_DIR="$1"
cd "$REMOTE_DIR/backend"
# `uv` lives at /usr/local/bin/uv or /root/.local/bin/uv on the remote; both
# are in the default PATH of an interactive SSH session.
uv sync --quiet
.venv/bin/python3 -m alembic upgrade head
REMOTE
fi

if [ "$FRONTEND" = 1 ]; then
  # Sync the backend's JWT public key into the frontend's EnvironmentFile.
  # The frontend Next.js middleware (frontend/middleware.ts) needs JWT_PUBLIC_KEY
  # at runtime to verify session cookies. The public key is non-sensitive
  # (only used to verify signatures) and lives in backend/.env; the frontend
  # .env.production is the systemd EnvironmentFile for cloude-frontend.
  # Without this step, an old variable name (e.g. JWT_PUBLIC_KEY_B64) or a
  # missing line makes the middleware fail open, redirecting every login
  # back to /login. See git history: "fix: align frontend env var with backend".
  say "[remote] frontend: sync JWT public key → .env.production"
  "${SSH[@]}" bash -s -- "$REMOTE_DIR" <<'REMOTE'
set -e
REMOTE_DIR="$1"
BACKEND_ENV="$REMOTE_DIR/backend/.env"
FRONTEND_ENV="$REMOTE_DIR/frontend/.env.production"
# Pick the canonical public key (same name backend config/settings.py reads).
JWT_KEY=$(grep -E '^JWT_PUBLIC_KEY=' "$BACKEND_ENV" | head -1 || true)
if [ -z "$JWT_KEY" ]; then
  echo "  warning: $BACKEND_ENV has no JWT_PUBLIC_KEY; skipping sync" >&2
else
  [ -f "$FRONTEND_ENV" ] || { echo "  (creating empty $FRONTEND_ENV)"; touch "$FRONTEND_ENV"; }
  if grep -qE '^JWT_PUBLIC_KEY=' "$FRONTEND_ENV"; then
    sed -i "s|^JWT_PUBLIC_KEY=.*|$JWT_KEY|" "$FRONTEND_ENV"
    echo "  updated JWT_PUBLIC_KEY in $FRONTEND_ENV"
  elif grep -qE '^JWT_PUBLIC_KEY_B64=' "$FRONTEND_ENV"; then
    # Migrate the legacy _B64 key: drop the old line, append the new one.
    sed -i '/^JWT_PUBLIC_KEY_B64=/d' "$FRONTEND_ENV"
    printf '%s\n' "$JWT_KEY" >> "$FRONTEND_ENV"
    echo "  migrated JWT_PUBLIC_KEY_B64 -> JWT_PUBLIC_KEY in $FRONTEND_ENV"
  else
    printf '%s\n' "$JWT_KEY" >> "$FRONTEND_ENV"
    echo "  appended JWT_PUBLIC_KEY to $FRONTEND_ENV"
  fi
fi
REMOTE
  echo
  say "[remote] frontend: npm ci + next build"
  "${SSH[@]}" bash -s -- "$REMOTE_DIR" "$SKIP_BUILD" <<'REMOTE'
set -e
REMOTE_DIR="$1"; SKIP_BUILD="$2"
cd "$REMOTE_DIR/frontend"
npm ci --no-audit --no-fund --silent
if [ "$SKIP_BUILD" = "1" ]; then
  echo "  (skip-build flag set; leaving existing .next/ in place)"
else
  npm run build
fi
REMOTE
fi

# ── Step 4: restart services ────────────────────────────────────────
if [ "$NO_RESTART" = 1 ]; then
  say "no-restart flag set; services not restarted"
  exit 0
fi

restart_svc() {
  local svc="$1"
  say "[remote] systemctl restart $svc"
  "${SSH[@]}" bash -s -- "$svc" <<'REMOTE'
set -e
svc="$1"
systemctl restart "$svc"
for i in 1 2 3 4 5 6 7 8 9 10; do
  if systemctl is-active --quiet "$svc"; then
    echo "  $svc active (after ${i}s)"
    exit 0
  fi
  sleep 1
done
echo "ERROR: $svc did not become active" >&2
systemctl status "$svc" --no-pager | tail -20 >&2
exit 1
REMOTE
}

if [ "$BACKEND" = 1 ]; then
  restart_svc "$BACKEND_SVC"
fi
if [ "$FRONTEND" = 1 ]; then
  restart_svc "$FRONTEND_SVC"
fi

# ── Step 5: health check ────────────────────────────────────────────
say "[remote] health checks"
"${SSH[@]}" bash -s -- <<'REMOTE'
backend_ok=0
for i in 1 2 3 4 5 6 7 8 9 10; do
  out=$(curl -sS -m 3 -w " HTTP=%{http_code}" http://127.0.0.1:8082/api/health 2>/dev/null || true)
  if echo "$out" | grep -q "200"; then
    echo "  backend  /api/health: $out"
    backend_ok=1; break
  fi
  sleep 1
done
[ "$backend_ok" = 1 ] || { echo "  backend  /api/health: DOWN"; exit 1; }

frontend_ok=0
for i in 1 2 3 4 5 6 7 8 9 10; do
  out=$(curl -sS -m 3 -w " HTTP=%{http_code}" http://127.0.0.1:3000/ 2>/dev/null || true)
  if echo "$out" | grep -qE "(200|307|308|404)"; then
    echo "  frontend /         : $out"
    frontend_ok=1; break
  fi
  sleep 1
done
[ "$frontend_ok" = 1 ] || { echo "  frontend /         : DOWN"; exit 1; }
REMOTE

echo
say "deploy complete ✓"
