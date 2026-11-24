#!/usr/bin/env bash
# Build the lab image and start a fresh lab-server. Fails loudly unless Apache returns HTTP 200,
# so a scenario is never applied on top of an already-broken baseline.
set -euo pipefail

NAME="lab-server"
IMAGE="lab-server-img"
DIR="$(cd "$(dirname "$0")" && pwd)"

fail() { echo "SETUP FAILED: $*" >&2; exit 1; }

echo "[1/4] Building image..."
docker build -q -t "$IMAGE" "$DIR" >/dev/null \
  || fail "docker build failed. Check COPY paths and Dockerfile syntax in the error above."

echo "[2/4] Starting container..."
docker rm -f "$NAME" >/dev/null 2>&1 || true
# --cpus/--memory cap the lab so CPU and memory fault scenarios can never overload your host.
docker run -d --name "$NAME" -p 127.0.0.1:8080:80 --cpus 1 --memory 512m "$IMAGE" >/dev/null \
  || fail "container '$NAME' did not start."

echo "[3/4] Checking and starting Apache..."
docker exec "$NAME" apachectl -t \
  || fail "Apache config is invalid (see the error above)."
docker exec "$NAME" apachectl -k start \
  || fail "Apache did not start. Check: docker exec $NAME tail -n 20 /var/log/apache2/error.log"

echo "[4/4] Health check (expects HTTP 200 on http://localhost:80)..."
code="000"
for _ in $(seq 1 10); do
  code="$(docker exec "$NAME" curl -s -o /dev/null -w "%{http_code}" http://localhost || true)"
  if [ "$code" = "200" ]; then
    echo "lab-server healthy (HTTP 200)"
    exit 0
  fi
  sleep 1
done

case "$code" in
  000) hint="nothing answers on port 80. Check 'Listen' in ports.conf and '<VirtualHost *:PORT>'." ;;
  403) hint="permission denied. Check file permissions and the <Directory> 'Require' rule." ;;
  404) hint="page not found. Check the DocumentRoot path and that index.html was copied." ;;
  5*)  hint="server error. Check /var/log/apache2/error.log." ;;
  *)   hint="unexpected response." ;;
esac
fail "health check returned HTTP $code (expected 200): $hint"
