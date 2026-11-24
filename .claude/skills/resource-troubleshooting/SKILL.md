---
name: resource-troubleshooting
description: Runbook for CPU, memory (RAM) and load problems on lab-server. Use when the server or website is slow, overloaded, hanging, running low on memory, or processes are being killed.
---

# CPU, memory and load troubleshooting runbook

All commands are read-only and run against the `lab-server` container. One command per call.
The container is limited to **1 CPU** and **512 MiB RAM**.

## Step 1: Overall picture (start here)
- `docker stats --no-stream lab-server`
  - `CPU %` near 100% means the single CPU is saturated.
  - `MEM USAGE / LIMIT` close to 512MiB means memory pressure.

## Step 2: CPU
- `docker exec lab-server uptime` and `docker exec lab-server cat /proc/loadavg`: load average.
  Compare with `docker exec lab-server nproc`. Load well above the CPU count means CPU contention.
- `docker exec lab-server ps aux --sort=-%cpu`: the top line is the biggest CPU user. Note its PID, user and command.
- `docker exec lab-server top -b -n 1 -o %CPU`: one-shot snapshot including CPU states (`us`, `sy`, `wa`).
- `docker exec lab-server vmstat 1 5`: `r` (run queue) high means CPU-bound; `wa` high means waiting on disk.

## Step 3: Memory
- `docker exec lab-server free -m`: look at `available`, not `free`.
- `docker exec lab-server ps aux --sort=-%mem`: the top line is the biggest memory user (`RSS` column, KB).
- `docker exec lab-server top -b -n 1 -o %MEM`: one-shot snapshot sorted by memory.
- `docker exec lab-server grep -n -i -e MemAvailable -e MemTotal /proc/meminfo`
- `docker inspect lab-server`: `"OOMKilled": true` in State means the kernel killed the container's main process for memory.

## Step 4: Decide the root cause
Report the specific process (PID, user, command, %CPU or RSS), not just "high CPU".

| Evidence | Likely cause |
|---|---|
| One process at ~100% CPU that is not apache2 | Runaway or unexpected process |
| Many apache2 workers each using CPU | Real traffic load, or a slow request pattern |
| One process with a very large RSS | Memory hog or memory leak |
| `available` memory near zero, OOMKilled true | Out of memory |
| High `wa` in vmstat | Disk I/O bottleneck rather than CPU |

## Fix guidance (for the human; never run these yourself)
- Confirm the process is not needed, then: `docker exec lab-server kill <PID>`.
- Verify: `docker stats --no-stream lab-server` shows CPU/memory back to normal, and
  `curl -I http://localhost:8080` returns 200.
- If load is legitimate traffic, the fix is capacity (more CPU/RAM), not killing processes.
