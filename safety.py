"""Command allow-list for the troubleshooting agent.

The agent's Bash tool can run ANY command on your machine. This module is the
guardrail: every command is checked here (via a PreToolUse hook) before it runs.

Design: deny by default. A command is allowed only if it is one of a few
read-only docker commands that target the lab container.
"""

from __future__ import annotations

import shlex

from pydantic import BaseModel

CONTAINER = "lab-server"

# Shell features that could chain, redirect, or inject extra commands.
FORBIDDEN_CHARS: tuple[str, ...] = (";", "&", "|", ">", "<", "`", "$", "\n", "\\", "(", ")", "{", "}", "*", "?")

# Read-only commands allowed INSIDE the container (after `docker exec lab-server`).
ALLOWED_INNER: frozenset[str] = frozenset(
    {
        # files, processes, disk
        "cat", "ls", "ps", "df", "du", "stat", "head", "tail", "grep", "find", "id", "whoami", "hostname",
        # CPU / memory / load
        "free", "uptime", "nproc", "vmstat", "top",
        # network
        "ss", "netstat", "curl", "wget",
        # apache
        "apachectl", "apache2ctl",
    }
)

# Per-command arguments that would make a "read-only" command dangerous or hang.
BLOCKED_ARGS: dict[str, frozenset[str]] = {
    "find": frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}),
    "tail": frozenset({"-f", "-F", "--follow"}),
    "curl": frozenset({"-o", "--output", "-O", "--remote-name", "-T", "--upload-file", "-d", "--data", "-X", "--request", "-K", "--config"}),
    "wget": frozenset({"-O", "--output-document", "-o", "--output-file", "-P", "--directory-prefix", "-i", "--input-file",
                       "-r", "--recursive", "-m", "--mirror", "-e", "--execute", "--post-data", "--post-file", "--method"}),
}

# apachectl: config test, vhost/module listing, version only. No start/stop/restart/graceful.
ALLOWED_APACHECTL_ARGS: frozenset[str] = frozenset({"-t", "-S", "-M", "-v", "-V", "configtest"})
ALLOWED_HTTP_HOSTS: tuple[str, ...] = ("http://localhost", "http://127.0.0.1")

# top must run once in batch mode, otherwise it is interactive and never exits.
ALLOWED_TOP_ARGS: frozenset[str] = frozenset({
    "-b -n 1", "-bn1", "-b -n1", "-bn 1",
    "-b -n 1 -o %CPU", "-bn1 -o %CPU", "-b -n 1 -o %MEM", "-bn1 -o %MEM",
})
# netstat flags only (no -c: continuous mode never exits).
NETSTAT_FLAG_CHARS: frozenset[str] = frozenset("tulnpaseirW")
VMSTAT_MAX_INTERVAL, VMSTAT_MAX_COUNT = 2, 5


class Decision(BaseModel):
    allowed: bool
    reason: str


def _deny(reason: str) -> Decision:
    return Decision(allowed=False, reason=reason)


def _check_inner(args: list[str]) -> Decision:
    """Check the command that will run inside the container."""
    if not args:
        return _deny("No command given after the container name.")

    cmd, rest = args[0], args[1:]
    if cmd not in ALLOWED_INNER:
        return _deny(f"'{cmd}' is not in the read-only allow-list: {sorted(ALLOWED_INNER)}.")

    blocked = BLOCKED_ARGS.get(cmd, frozenset())
    for arg in rest:
        if arg in blocked or any(arg.startswith(b + "=") for b in blocked if b.startswith("--")):
            return _deny(f"Argument '{arg}' is not allowed for '{cmd}'.")
        # Attached short-option values such as "-O/tmp/x" or "-ofile".
        if cmd == "wget" and any(arg.startswith(b) and len(arg) > len(b) for b in blocked if not b.startswith("--")):
            return _deny(f"Argument '{arg}' is not allowed for 'wget'.")

    if cmd == "top" and " ".join(rest) not in ALLOWED_TOP_ARGS:
        return _deny("Use 'top -b -n 1' (optionally '-o %CPU' or '-o %MEM'); interactive top never exits.")

    if cmd == "netstat":
        if not rest or any(not a.startswith("-") or a.startswith("--") or not set(a[1:]) <= NETSTAT_FLAG_CHARS for a in rest):
            return _deny("Use netstat with short flags only, e.g. 'netstat -tulnp', 'netstat -an', 'netstat -s'.")

    if cmd == "vmstat":
        if len(rest) > 2 or any(not a.isdigit() for a in rest):
            return _deny("Use 'vmstat' or 'vmstat <interval> <count>', e.g. 'vmstat 1 5'.")
        if len(rest) >= 1 and int(rest[0]) > VMSTAT_MAX_INTERVAL:
            return _deny(f"vmstat interval must be {VMSTAT_MAX_INTERVAL} seconds or less.")
        if len(rest) == 2 and int(rest[1]) > VMSTAT_MAX_COUNT:
            return _deny(f"vmstat count must be {VMSTAT_MAX_COUNT} or less.")

    if cmd == "nproc" and rest:
        return _deny("Use 'nproc' without arguments.")

    if cmd in {"apachectl", "apache2ctl"} and (not rest or any(a not in ALLOWED_APACHECTL_ARGS for a in rest)):
        return _deny(
            f"Only '{cmd} -t', '-S', '-M', '-v', '-V' or 'configtest' are allowed "
            "(no start, stop, restart or graceful)."
        )

    if cmd in {"curl", "wget"}:
        urls = [a for a in rest if "://" in a]
        values = [a for a in rest if not a.startswith("-") and "://" not in a]
        if not urls or any(not u.startswith(ALLOWED_HTTP_HOSTS) for u in urls):
            return _deny(f"{cmd} may only call http://localhost or http://127.0.0.1 inside the container.")
        if any(not v.isdigit() for v in values):
            return _deny(f"Unexpected {cmd} argument(s) {values}; only numeric option values (e.g. timeouts) are allowed.")
        if cmd == "wget" and "--spider" not in rest:
            return _deny("wget must use --spider (check only, never download). Example: 'wget -q -S --spider http://localhost'.")

    return Decision(allowed=True, reason="Read-only command inside lab container.")


def check_command(command: str) -> Decision:
    """Return whether the agent may run this shell command."""
    if not command.strip():
        return _deny("Empty command.")

    for ch in FORBIDDEN_CHARS:
        if ch in command:
            return _deny(
                f"Character {ch!r} is not allowed (no pipes, redirects, chaining, globs or substitution). "
                "Run one simple command at a time."
            )

    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return _deny(f"Could not parse command: {exc}")

    if argv[0] != "docker" or len(argv) < 2:
        return _deny(f"Only docker commands against '{CONTAINER}' are allowed.")

    sub = argv[1]

    if sub == "ps" and len(argv) == 2:
        return Decision(allowed=True, reason="List containers.")

    if sub in {"logs", "inspect"}:
        target = argv[-1]
        flags = argv[2:-1]
        if target != CONTAINER:
            return _deny(f"'docker {sub}' is only allowed for '{CONTAINER}'.")
        if sub == "logs" and any(f in {"-f", "--follow"} for f in flags):
            return _deny("Following logs would hang. Use 'docker logs --tail 100 lab-server'.")
        if sub == "inspect" and flags:
            return _deny("Use 'docker inspect lab-server' without extra flags.")
        return Decision(allowed=True, reason=f"Read-only 'docker {sub}'.")

    if sub == "stats":
        if argv[2:] == ["--no-stream", CONTAINER]:
            return Decision(allowed=True, reason="One-shot container CPU/memory usage.")
        return _deny(f"Use exactly 'docker stats --no-stream {CONTAINER}' (without --no-stream it never exits).")

    if sub == "exec":
        # Strict form: docker exec lab-server <cmd> ... (no -it, -u, -e, -w or other flags).
        if len(argv) < 3 or argv[2] != CONTAINER:
            return _deny(f"Use exactly 'docker exec {CONTAINER} <command>' with no extra docker flags.")
        return _check_inner(argv[3:])

    return _deny(f"'docker {sub}' is not allowed. Allowed: ps, logs, inspect, stats, exec (read-only).")
