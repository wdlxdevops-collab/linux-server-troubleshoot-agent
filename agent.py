"""Linux troubleshooting agent (first version: one agent, one tool, strong guardrails).

Usage:
    python agent.py "apache2 is down on lab-server and does not come back."
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    SystemMessage,
    UserMessage,
    query,
)

from safety import check_command

BASE_DIR = Path(__file__).resolve().parent
AUDIT_LOG = BASE_DIR / "audit.jsonl"
REPORTS_DIR = BASE_DIR / "reports"

MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-5-5")
MAX_TURNS = int(os.getenv("AGENT_MAX_TURNS", "25"))
MAX_BUDGET_USD = float(os.getenv("AGENT_MAX_BUDGET_USD", "0.50"))

# Only our own reviewed runbooks in .claude/skills/. Bundled/other skills are not allowed.
SKILLS: list[str] = ["apache-troubleshooting", "resource-troubleshooting", "network-troubleshooting"]

SYSTEM_PROMPT = """You are a senior Linux SRE investigating a problem on a server called `lab-server`.
The server is a Docker container. You reach it only through these commands:
- docker ps
- docker logs --tail 100 lab-server
- docker inspect lab-server
- docker exec lab-server <read-only command>
- docker stats --no-stream lab-server   (container CPU % and memory use vs limit)
  Allowed inner commands:
  files/processes: cat, ls, ps (e.g. `ps aux --sort=-%cpu`, `ps aux --sort=-%mem`), df, du, stat,
                   head, tail, grep, find (no -exec/-delete), id, whoami, hostname
  CPU/memory/load: free -m, uptime, nproc, vmstat [interval<=2] [count<=5], top -b -n 1 [-o %CPU|%MEM],
                   cat /proc/loadavg, cat /proc/meminfo
  network:         ss -ltnp, netstat -tulnp / -an / -s, curl http://localhost..., wget --spider http://localhost...
  apache:          apachectl -t/-S/-M/-v/-V/configtest
  Apache files: /etc/apache2/ (apache2.conf, sites-enabled/, ports.conf), logs in /var/log/apache2/,
  web root normally /var/www/html.
  Note: `docker logs lab-server` is normally empty here (the container's main process is not Apache).
  Apache's own logs are in /var/log/apache2/.

Runbooks (skills): apache-troubleshooting, resource-troubleshooting, network-troubleshooting.
Load the skill that matches the symptom FIRST and follow its steps. Load another skill if the evidence points there.

Rules:
1. You are READ-ONLY. Never try to fix, restart, edit, or delete anything.
2. One simple command per call. No pipes, redirects, ';', '&&', '$', globs or subshells.
3. If a command is blocked, read the reason and choose an allowed alternative. Do not retry the same command.
4. Never run the same command twice.
5. Prefer `tail -n`, `head -n` or `grep -n` over `cat` for large files such as apache2.conf and logs.
6. When a service will not start, validate its configuration early (for Apache: `apachectl -t`).
   When the server is slow or unstable, check resources early: `docker stats --no-stream lab-server`,
   then find the top process with `ps aux --sort=-%cpu` or `ps aux --sort=-%mem`.
7. Base every conclusion on command output you actually saw. If evidence is missing, say so.
8. Be efficient: stop investigating once the root cause is confirmed.

Your FINAL message must be ONLY this report in Markdown (no other text):
## Symptom
## Evidence
(the key commands you ran and the important lines of output)
## Root cause
## Fix
(exact commands a human should run; you must NOT run them)
## Verify
(commands that prove the fix worked)
"""


def audit(event: dict[str, Any]) -> None:
    """Append one JSON line per security-relevant event."""
    event = {"ts": datetime.now(timezone.utc).isoformat(), **event}
    with AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def _decision(allow: bool, reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow" if allow else "deny",
            "permissionDecisionReason": reason,
        }
    }


async def guard_tools(input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
    """PreToolUse hook: runs before EVERY tool call. Deny by default."""
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {}) or {}

    if tool_name == "Skill":
        # Skills only add read-only instructions; still allow only our own reviewed runbooks.
        raw = tool_input.get("skill") or tool_input.get("name") or tool_input.get("command") or ""
        skill = str(raw).lstrip("/").split()[0] if raw else ""
        allowed = skill in SKILLS
        audit({"tool": "Skill", "skill": skill, "input": tool_input, "allowed": allowed})
        if allowed:
            return _decision(True, f"Loading runbook '{skill}'.")
        return _decision(False, f"Skill '{skill}' is not permitted. Allowed: {SKILLS}.")

    if tool_name != "Bash":
        audit({"tool": tool_name, "allowed": False, "reason": "tool not permitted"})
        return _decision(False, f"Tool '{tool_name}' is not permitted. Use Bash with read-only docker commands.")

    if tool_input.get("run_in_background"):
        audit({"tool": "Bash", "command": tool_input.get("command"), "allowed": False, "reason": "background"})
        return _decision(False, "Background commands are not allowed.")

    command = str(tool_input.get("command", ""))
    decision = check_command(command)
    audit({"tool": "Bash", "command": command, "allowed": decision.allowed, "reason": decision.reason})
    return _decision(decision.allowed, decision.reason)


def build_options() -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        tools=["Bash", "Skill"],        # the ONLY tools the model can see
        allowed_tools=["Bash", "Skill"],  # no interactive prompt; the hook decides
        skills=SKILLS,                  # only our runbooks in .claude/skills/
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[guard_tools])]},  # None = every tool
        max_turns=MAX_TURNS,
        max_budget_usd=MAX_BUDGET_USD,  # hard cost cap per run
        setting_sources=["project"],    # load ./CLAUDE.md (human-verified incidents); ignore ~/.claude user settings
        env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"},  # no self-written memory: only what humans put in CLAUDE.md
        cwd=str(BASE_DIR),              # CLAUDE.md is read from this folder
    )


def save_report(report: str, symptom: str, model: str, turns: int, cost: float | None) -> Path:
    """Save the final report as a Markdown file and return its path."""
    REPORTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = REPORTS_DIR / f"report-{stamp}.md"
    cost_text = f"${cost:.4f}" if cost is not None else "n/a"
    header = (
        f"<!-- symptom: {symptom} | model: {model} | turns: {turns} | est. cost: {cost_text} -->\n\n"
    )
    path.write_text(header + report.strip() + "\n", encoding="utf-8")
    return path


def _short(text: str, limit: int = 400) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + " ...[truncated]"


async def run(symptom: str) -> int:
    memory_file = BASE_DIR / "CLAUDE.md"
    memory_info = f"CLAUDE.md loaded ({len(memory_file.read_text(encoding='utf-8').splitlines())} lines)" \
        if memory_file.exists() else "no CLAUDE.md found"
    print(f"Model: {MODEL} | max turns: {MAX_TURNS} | budget: ${MAX_BUDGET_USD:.2f} | memory: {memory_info}\n")
    audit({"event": "run_start", "symptom": symptom, "model": MODEL, "memory": memory_info})

    exit_code = 1
    async for message in query(prompt=f"Investigate this problem: {symptom}", options=build_options()):
        if isinstance(message, SystemMessage) and message.subtype == "init":
            names = {s if isinstance(s, str) else str(s.get("name", "")) for s in message.data.get("skills", [])}
            loaded = sorted(names & set(SKILLS))
            missing = sorted(set(SKILLS) - set(loaded))
            print(f"Skills loaded: {loaded or 'none'}" + (f" | MISSING: {missing}" if missing else ""))
            audit({"event": "skills_loaded", "loaded": loaded, "missing": missing})
        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    if block.name == "Skill":
                        print(f"\n[skill] {block.input}")
                    else:
                        print(f"\n$ {block.input.get('command', block.input)}")
                elif isinstance(block, TextBlock) and block.text.strip():
                    # Progress notes only; the full final report is printed once at the end.
                    print(f"\n[agent] {_short(block.text, 300)}")
        elif isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    content = block.content if isinstance(block.content, str) else json.dumps(block.content)
                    label = "BLOCKED/ERROR" if block.is_error else "output"
                    print(f"  ({label}) {_short(content or '')}")
        elif isinstance(message, ResultMessage):
            cost = f"${message.total_cost_usd:.4f}" if message.total_cost_usd is not None else "n/a"
            report_path: Path | None = None

            print("\n" + "=" * 70)
            if message.subtype == "success" and message.result:
                print("FINAL REPORT\n" + "=" * 70)
                print(message.result.strip())
                report_path = save_report(message.result, symptom, MODEL, message.num_turns, message.total_cost_usd)
            else:
                print(f"No report: the run ended with '{message.subtype}'.")
                if message.subtype == "error_max_turns":
                    print("Increase AGENT_MAX_TURNS and run again.")
                elif message.subtype == "error_max_budget_usd":
                    print("Increase AGENT_MAX_BUDGET_USD and run again.")

            print("=" * 70)
            print(f"Result: {message.subtype} | turns: {message.num_turns} | est. cost: {cost}")
            if report_path:
                print(f"Report saved to: {report_path.relative_to(BASE_DIR)}")
            audit({
                "event": "run_end",
                "subtype": message.subtype,
                "turns": message.num_turns,
                "cost_usd": message.total_cost_usd,
                "report": str(report_path.relative_to(BASE_DIR)) if report_path else None,
            })
            exit_code = 0 if message.subtype == "success" else 1

    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Linux troubleshooting agent")
    parser.add_argument("symptom", help="What is wrong, e.g. 'apache2 is down on lab-server'")
    args = parser.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set. Run: set -a && source .env && set +a")

    sys.exit(asyncio.run(run(args.symptom)))


if __name__ == "__main__":
    main()
