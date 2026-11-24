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
    # CPU / memory / load
    "docker stats --no-stream lab-server",
    "docker exec lab-server top -b -n 1",
    "docker exec lab-server top -bn1 -o %MEM",
    "docker exec lab-server ps aux --sort=-%cpu",
    "docker exec lab-server free -m",
    "docker exec lab-server vmstat 1 5",
    "docker exec lab-server nproc",
    "docker exec lab-server cat /proc/loadavg",
    # network
    "docker exec lab-server netstat -tulnp",
    "docker exec lab-server netstat -an",
    "docker exec lab-server curl -sI --max-time 5 http://localhost",
    "docker exec lab-server wget -q -S --spider http://localhost",
    "docker exec lab-server wget --spider --timeout=5 http://127.0.0.1",
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
    # CPU / memory / load
    "docker stats lab-server",                               # streams forever
    "docker stats --no-stream other-container",              # wrong target
    "docker exec lab-server top",                            # interactive, never exits
    "docker exec lab-server vmstat 1 1000",                  # runs too long
    "docker exec lab-server vmstat 60",                      # interval too long
    "docker exec lab-server kill -9 1",                      # kill not allowed
    # network
    "docker exec lab-server netstat -c",                     # continuous, never exits
    "docker exec lab-server wget http://localhost",          # downloads a file
    "docker exec lab-server wget -O /tmp/x --spider http://localhost",  # writes a file
    "docker exec lab-server wget -O/tmp/x --spider http://localhost",   # attached -O value
    "docker exec lab-server wget --spider http://evil.example.com",     # external host
    "docker exec lab-server curl -sI http://localhost evil.example.com",  # extra target
]


@pytest.mark.parametrize("command", ALLOWED)
def test_allowed(command: str) -> None:
    decision = check_command(command)
    assert decision.allowed, decision.reason


@pytest.mark.parametrize("command", DENIED)
def test_denied(command: str) -> None:
    assert not check_command(command).allowed
