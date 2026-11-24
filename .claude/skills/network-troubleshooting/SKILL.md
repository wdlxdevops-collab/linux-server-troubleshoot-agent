---
name: network-troubleshooting
description: Runbook for HTTP and network checks on lab-server using curl, wget, netstat and ss. Use when the site does not respond, times out, refuses connections, returns unexpected HTTP codes, or a port problem is suspected.
---

# Network and HTTP troubleshooting runbook

All commands are read-only and run against the `lab-server` container. One command per call.
curl and wget may only call http://localhost or http://127.0.0.1 inside the container.

## Step 1: Is anything listening?
- `docker exec lab-server netstat -tulnp`: every listening TCP/UDP port with PID/program.
- `docker exec lab-server ss -ltnp`: the same, newer tool.

| What you see | Meaning |
|---|---|
| `0.0.0.0:80 ... apache2` | Apache is listening normally |
| Nothing on port 80 | No web server running (Apache down) |
| Port 80 owned by another program (e.g. `nc`) | Port conflict: Apache cannot bind |
| Apache on a different port (e.g. 8080) | `Listen` / `<VirtualHost>` port mismatch |

## Step 2: Does HTTP answer? (curl)
- Headers only: `docker exec lab-server curl -sI --max-time 5 http://localhost`
- Verbose (connection details + headers): `docker exec lab-server curl -sv --max-time 5 http://localhost`

| curl result | Meaning |
|---|---|
| `HTTP/1.1 200 OK` | Healthy |
| `HTTP/1.1 403` / `404` / `5xx` | Server answers but the request fails; see apache-troubleshooting |
| `Connection refused` (exit code 7) | Nothing listening on that port |
| `Operation timed out` (exit code 28) | Listening but too slow: check CPU/memory (resource-troubleshooting) |
| `Empty reply from server` (exit code 52) | Something accepted the connection but is not a web server (e.g. `nc`) |

## Step 3: Second opinion (wget)
- `docker exec lab-server wget -q -S --spider --timeout=5 http://localhost`
  `--spider` checks the page without downloading it; `-S` prints the server response headers.
- Use it to confirm a curl result, or when curl output is unclear.

## Step 4: Connection state (netstat)
- `docker exec lab-server netstat -an`: all sockets. Many `TIME_WAIT` or `SYN_RECV` entries on :80 suggest heavy or stuck traffic.
- `docker exec lab-server netstat -s`: protocol statistics (retransmissions, failed connection attempts).

## Step 5: From the host side (context only)
- The site is published on the host at http://localhost:8080 (container port 80).
- `docker ps` PORTS column should show `127.0.0.1:8080->80/tcp`.
- If the container works internally (curl inside returns 200) but the host cannot reach it, the problem is
  the port mapping, not Apache. You cannot run host-side curl; say so in the report.

## Fix guidance (for the human; never run these yourself)
- Port conflict: stop the process holding the port, then start Apache.
- Nothing listening: start Apache (`docker exec lab-server apachectl -k start`) after checking `apachectl -t`.
- Timeouts: investigate resources first; do not restart blindly.
