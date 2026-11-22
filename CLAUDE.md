# lab-server: known issues (human-verified)

This file is the agent's long-term memory. Only add entries a human has verified.
Past incidents are hints, not answers: always confirm the cause with command output before concluding.

## Environment facts
- `lab-server` is a Docker container. Its main process is `sleep infinity`, not Apache.
- So `docker logs lab-server` is normally empty. Apache logs are in /var/log/apache2/.
- So after `docker start lab-server`, Apache does NOT start by itself.
- The site is published on the host at http://localhost:8080 (container port 80).

## Apache will not start
- First check: `docker exec lab-server apachectl -t` (shows syntax errors with file and line number).
- Seen before: an invalid line appended to /etc/apache2/apache2.conf.
- Seen before: port 80 already used by another process. Check `docker exec lab-server ss -ltnp`.

## Site does not respond at all (HTTP 000)
- First check: `docker inspect lab-server` (State.Status, ExitCode, OOMKilled, FinishedAt).
- Seen before: container exited with code 137 (killed, e.g. `docker stop`).
- The fix must include BOTH:
  1. `docker start lab-server`
  2. `docker exec lab-server apachectl -k start`

## HTTP 403 Forbidden
- Check file permissions: `docker exec lab-server ls -l /var/www/html`.
- Seen before: index.html set to mode 000, so the www-data user cannot read it.

## HTTP 404 Not Found
- Check DocumentRoot: `docker exec lab-server grep -n DocumentRoot /etc/apache2/sites-enabled/000-default.conf`.
- Seen before: DocumentRoot pointing to a folder that does not exist.

<!-- How to add an entry:
1. The agent's report was verified correct by a human (or a human found the real cause).
2. Add: symptom -> first check -> cause seen before -> fix.
3. Write general guidance, not "the answer is always X".
4. Re-run all scenarios to confirm nothing got worse. -->
