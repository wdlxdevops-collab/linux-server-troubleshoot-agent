#!/usr/bin/env bash
# Reset the lab, then break it on purpose. Usage: ./lab/break.sh <scenario>
# Prints the symptom to give the agent. The root cause is NOT printed - the agent must find it.
set -euo pipefail

NAME="lab-server"
DIR="$(cd "$(dirname "$0")" && pwd)"
SCENARIO="${1:-}"

run() { docker exec "$NAME" bash -c "$1"; }

# Start from a healthy baseline. If setup fails, stop: never break an already-broken lab.
reset() {
  "$DIR/setup_lab.sh" >/dev/null \
    || { echo "Baseline lab is NOT healthy - scenario '$SCENARIO' was NOT applied." >&2; exit 1; }
}

case "$SCENARIO" in
  bad-config)
    reset
    run "apachectl -k stop; sleep 1; echo 'this is not valid apache config' >> /etc/apache2/apache2.conf"
    SYMPTOM="apache2 is down on lab-server and does not come back."
    ;;
  permissions)
    reset
    run "chmod 000 /var/www/html/index.html"
    SYMPTOM="The website on lab-server returns an error instead of the home page."
    ;;
  port-conflict)
    reset
    run "apachectl -k stop; sleep 1"
    docker exec -d "$NAME" nc -lk 80
    sleep 1
    run "apachectl -k start 2>/dev/null || true"
    SYMPTOM="apache2 on lab-server will not start, but something answers on port 80."
    ;;
  wrong-root)
    reset
    run "sed -i 's#DocumentRoot /var/www/html#DocumentRoot /var/www/site#' /etc/apache2/sites-enabled/000-default.conf && apachectl -k graceful 2>/dev/null"
    SYMPTOM="The website on lab-server returns 'not found' for the home page."
    ;;
  *)
    echo "Usage: $0 {bad-config|permissions|port-conflict|wrong-root}" >&2
    exit 1
    ;;
esac

echo "Scenario '$SCENARIO' is ready."
echo "Give the agent this symptom:"
echo "  $SYMPTOM"
