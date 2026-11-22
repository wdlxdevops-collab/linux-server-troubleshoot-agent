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
        "cat", "ls", "ps", "df", "du", "free", "uptime", "ss", "stat",
        "head", "tail", "grep", "id", "whoami", "hostname", "apachectl", "apache2ctl", "curl", "find",
    }
)

# Per-command arguments that would make a "read-only" command dangerous or hang.
BLOCKED_ARGS: dict[str, frozenset[str]] = {
    "find": frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}),
    "tail": frozenset({"-f", "-F", "--follow"}),
    "curl": frozenset({"-o", "--output", "-O", "--remote-name", "-T", "--upload-file", "-d", "--data", "-X", "--request", "-K", "--config"}),
}

# apachectl: config test, vhost/module listing, version only. No start/stop/restart/graceful.
ALLOWED_APACHECTL_ARGS: frozenset[str] = frozenset({"-t", "-S", "-M", "-v", "-V", "configtest"})
ALLOWED_CURL_HOSTS: tuple[str, ...] = ("http://localhost", "http://127.0.0.1")


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

    if cmd in {"apachectl", "apache2ctl"} and (not rest or any(a not in ALLOWED_APACHECTL_ARGS for a in rest)):
        return _deny(
            f"Only '{cmd} -t', '-S', '-M', '-v', '-V' or 'configtest' are allowed "
            "(no start, stop, restart or graceful)."
        )

    if cmd == "curl":
        urls = [a for a in rest if not a.startswith("-")]
        if not urls or any(not u.startswith(ALLOWED_CURL_HOSTS) for u in urls):
            return _deny("curl may only call http://localhost or http://127.0.0.1 inside the container.")

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

    if sub == "exec":
        # Strict form: docker exec lab-server <cmd> ... (no -it, -u, -e, -w or other flags).
        if len(argv) < 3 or argv[2] != CONTAINER:
            return _deny(f"Use exactly 'docker exec {CONTAINER} <command>' with no extra docker flags.")
        return _check_inner(argv[3:])

    return _deny(f"'docker {sub}' is not allowed. Allowed: ps, logs, inspect, exec (read-only).")
