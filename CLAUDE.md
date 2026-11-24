# lab-server: environment facts and known issues (human-verified)

This file is loaded on every run, so keep it short. Detailed step-by-step checks live in the skills:
- `apache-troubleshooting`: Apache down, config errors, HTTP 403/404/5xx
- `resource-troubleshooting`: slow/overloaded server, high CPU, low memory
- `network-troubleshooting`: curl, wget, netstat, ss; no response, timeouts, port problems

Past incidents are hints, not answers: always confirm the cause with command output before concluding.

## Environment facts
- `lab-server` is a Docker container. Its main process is `sleep infinity`, not Apache.
- So `docker logs lab-server` is normally empty. Apache logs are in /var/log/apache2/.
- So after `docker start lab-server`, Apache does NOT start by itself.
- The site is published on the host at http://localhost:8080 (container port 80).
- The container is limited to 1 CPU and 512 MiB RAM.

## Incidents seen before (verified)
| Symptom | Root cause found | Key evidence |
|---|---|---|
| Apache down, will not start | Invalid line appended to /etc/apache2/apache2.conf | `apachectl -t` syntax error with line number |
| Apache will not start, port 80 answers | `nc` holding port 80 | `netstat -tulnp` shows `nc` on :80 |
| HTTP 403 | index.html mode 000 | `ls -l /var/www/html` |
| HTTP 404 | DocumentRoot points to a missing folder | `grep -n DocumentRoot` in 000-default.conf |
| No response at all (HTTP 000) | Container exited (code 137) | `docker inspect lab-server` State |
| Slow, overloaded | Shell busy-loops using all CPU | `docker stats`, `ps aux --sort=-%cpu` |
| Low memory | One process holding ~300 MB | `docker stats`, `ps aux --sort=-%mem` |

For a stopped container, the fix must include BOTH `docker start lab-server` AND
`docker exec lab-server apachectl -k start`.

<!-- How to add an entry:
1. A human verified the root cause.
2. Add one table row here. Put new step-by-step checks in the matching skill, not here.
3. Write general guidance, not "the answer is always X".
4. Re-run all scenarios to confirm nothing got worse. -->
