#!/usr/bin/env bash
# 只停止监听指定端口的进程（默认 8000 与 3000），绝不按进程名批量 kill（避免误杀其他同事的测试服务）
#   scripts/stop.sh            # 停 :8000 与 :3000
#   scripts/stop.sh 8000       # 只停后端
set -uo pipefail
PORTS=("$@"); [[ ${#PORTS[@]} -eq 0 ]] && PORTS=(8000 3000)
for p in "${PORTS[@]}"; do
  pids=$(ss -ltnpH "sport = :$p" 2>/dev/null | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u)
  if [[ -z "$pids" ]]; then echo "[stop] :$p 无监听进程"; continue; fi
  for pid in $pids; do
    echo "[stop] :$p → kill $pid ($(ps -o comm= -p "$pid" 2>/dev/null))"
    kill "$pid" 2>/dev/null || true
  done
  for _ in $(seq 1 20); do ss -ltnH "sport = :$p" | grep -q . || break; sleep 0.5; done
  ss -ltnH "sport = :$p" | grep -q . && echo "[stop] ⚠ :$p 仍在监听" >&2
done
exit 0
