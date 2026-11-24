---
name: apache-troubleshooting
description: Runbook for Apache (apache2) problems on lab-server. Use when Apache is down, will not start or reload, has a config error, or the site returns HTTP 403, 404 or 5xx.
---

# Apache troubleshooting runbook

All commands are read-only and run against the `lab-server` container. One command per call.

## Step 1: Is Apache running?
- `docker exec lab-server ps aux --sort=-%cpu`. Look for `apache2` processes (one root parent plus `www-data` workers).
- No `apache2` processes means Apache is down. Go to step 2.

## Step 2: Is the configuration valid?
- `docker exec lab-server apachectl -t`
  - `Syntax OK` means the config is valid.
  - `AH00526: Syntax error on line N of <file>` gives the exact file and line.
- Show the bad line: `docker exec lab-server grep -n <word from the error> <file>` or `docker exec lab-server tail -n 20 <file>`.

## Step 3: Can Apache bind its port?
- `docker exec lab-server netstat -tulnp` (or `ss -ltnp`) shows who is listening on port 80.
- Port 80 held by a process that is not `apache2` (for example `nc`) is a port conflict.
- Confirm in the log: `docker exec lab-server tail -n 50 /var/log/apache2/error.log`, looking for
  `could not bind to address 0.0.0.0:80` / `Address already in use`.

## Step 4: Apache runs but the site fails (use the HTTP code)
- `docker exec lab-server curl -sI --max-time 5 http://localhost`

| Code | Meaning | Next check |
|---|---|---|
| 403 | Forbidden | `docker exec lab-server ls -l /var/www/html` (file mode, e.g. `----------`); `<Directory>` `Require` rule in the site config |
| 404 | Not found | `docker exec lab-server grep -n DocumentRoot /etc/apache2/sites-enabled/000-default.conf`, then `ls` that folder |
| 5xx | Server error | `docker exec lab-server tail -n 50 /var/log/apache2/error.log` |

## Step 5: Useful files
- Main config: /etc/apache2/apache2.conf
- Ports: /etc/apache2/ports.conf
- Site: /etc/apache2/sites-enabled/000-default.conf
- Logs: /var/log/apache2/error.log and access.log
- Virtual hosts summary: `docker exec lab-server apachectl -S`

## Fix guidance (for the human; never run these yourself)
- Config error: remove or correct the bad line, then `apachectl -t`, then `apachectl -k start` (or `-k graceful` if running).
- Port conflict: stop the process holding port 80, then `apachectl -k start`.
- 403: restore readable permissions (e.g. `chmod 644` on the file).
- 404: point DocumentRoot back to the correct folder, then `apachectl -k graceful`.
