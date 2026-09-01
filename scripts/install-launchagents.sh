#!/usr/bin/env bash
# Install per-user LaunchAgents so the whole Note Master stack:
#   • starts automatically at login
#   • restarts automatically if a service crashes
#   • survives terminal/session closures
#
#   scripts/install-launchagents.sh          # write + load backend + frontend
#   scripts/install-launchagents.sh stop     # unload both
#
# Logs: /tmp/nm-backend.log /tmp/nm-frontend.log
# Manual control: launchctl kickstart -k gui/$UID/com.notemaster.backend

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LA_DIR="$HOME/Library/LaunchAgents"
LABEL_PREFIX="com.notemaster"

write_plist() {
  local label="$1" program="$2" workdir="$3" logfile="$4"
  mkdir -p "$LA_DIR"
  cat > "$LA_DIR/$label.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>-lc</string><string>$program</string>
  </array>
  <key>WorkingDirectory</key><string>$workdir</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$logfile</string>
  <key>StandardErrorPath</key><string>$logfile</string>
</dict></plist>
PLIST
}

if [ "${1:-install}" = "stop" ]; then
  for svc in backend frontend; do
    launchctl bootout gui/"$UID"/"$LABEL_PREFIX.$svc" 2>/dev/null || true
    echo "stopped $LABEL_PREFIX.$svc"
  done
  exit 0
fi

BACKEND_CMD="source \$HOME/.langfuse/keys 2>/dev/null; \
export LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY LANGFUSE_HOST; \
export MEMORY_ENABLED=1; \
exec \$(command -v uv) run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
write_plist "$LABEL_PREFIX.backend" "$BACKEND_CMD" "$ROOT/backend" /tmp/nm-backend.log

write_plist "$LABEL_PREFIX.frontend" "exec npm run dev" "$ROOT/frontend" /tmp/nm-frontend.log

for svc in backend frontend; do
  launchctl bootout gui/"$UID"/"$LABEL_PREFIX.$svc" 2>/dev/null || true   # reload config
  launchctl bootstrap gui/"$UID" "$LA_DIR/$LABEL_PREFIX.$svc.plist"
  launchctl kickstart gui/"$UID"/"$LABEL_PREFIX.$svc" 2>/dev/null || true
done

echo "waiting for services..."
ok=1
for port in 8000 3000; do
  up=0
  for i in $(seq 1 40); do nc -z 127.0.0.1 $port >/dev/null 2>&1 && up=1 && break; sleep 2; done
  [ "$up" = 1 ] && echo "  :$port ✅" || { echo "  :$port ❌"; ok=0; }
done
[ "$ok" = 1 ] && echo "LaunchAgents installed — stack auto-starts at login and self-heals." || echo "some services failed — check /tmp/nm-*.log"