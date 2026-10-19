#!/usr/bin/env bash
# 一键启动《织梦》开发环境：FastAPI 后端 (:8000) + Next.js 前端 (:3000)
#   scripts/dev.sh              # 读取 .env（不存在则从 .env.example 生成）
#   scripts/dev.sh --fallback   # 强制本地兜底模式（不调用远程模型）
#   scripts/dev.sh --prod       # 前端用 next build && next start
#   scripts/dev.sh --api-only   # 只启动后端；--web-only 只启动前端
# 环境变量里已有的 DASHSCOPE_API_KEY 优先于 .env；脚本永远不会打印密钥。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE_FALLBACK=0
FRONT_PROD=0
RUN_API=1
RUN_WEB=1
for arg in "$@"; do
  case "$arg" in
    --fallback) MODE_FALLBACK=1 ;;
    --prod) FRONT_PROD=1 ;;
    --api-only) RUN_WEB=0 ;;
    --web-only) RUN_API=0 ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

# ---------- .env handling ----------
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[dev] 已从 .env.example 生成 .env（可在其中填写 DASHSCOPE_API_KEY）"
fi
# 记住调用者环境中已有的 key（优先级高于 .env）
_PRESET_KEY="${DASHSCOPE_API_KEY:-}"
set -a
# shellcheck disable=SC1091
source <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' .env)
set +a
if [[ -n "$_PRESET_KEY" ]]; then export DASHSCOPE_API_KEY="$_PRESET_KEY"; fi
unset _PRESET_KEY
[[ -z "${DASHSCOPE_API_KEY:-}" ]] && unset DASHSCOPE_API_KEY
[[ $MODE_FALLBACK -eq 1 ]] && export ZM_FORCE_FALLBACK=1

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
export BACKEND_ORIGIN="${BACKEND_ORIGIN:-http://localhost:$BACKEND_PORT}"

if [[ "${ZM_FORCE_FALLBACK:-0}" =~ ^(1|true|yes)$ ]]; then
  echo "[dev] 模型模式: 本地兜底 (ZM_FORCE_FALLBACK=1)"
elif [[ -n "${DASHSCOPE_API_KEY:-}" ]]; then
  echo "[dev] 模型模式: 阿里云百炼 (DASHSCOPE_API_KEY 已配置)"
else
  echo "[dev] 模型模式: 本地兜底 (未配置 DASHSCOPE_API_KEY)"
fi

# ---------- preflight ----------
need() { command -v "$1" >/dev/null || { echo "[dev] 缺少命令: $1（$2）" >&2; exit 1; }; }
need curl "用于健康检查"
if [[ $RUN_API -eq 1 && ! -f backend/app/main.py ]]; then
  echo "[dev] 后端入口 backend/app/main.py 不存在（需要 app.main:app），后端尚未就绪；可先用 --web-only" >&2
  exit 1
fi
[[ $RUN_WEB -eq 1 ]] && need pnpm "npm i -g pnpm"

# ---------- dependencies ----------
if [[ $RUN_API -eq 1 && ! -x backend/.venv/bin/python ]]; then
  echo "[dev] 创建后端虚拟环境..."
  if command -v uv >/dev/null; then
    (cd backend && uv venv .venv --python 3.12 && \
      if [[ -f pyproject.toml ]]; then uv pip install --python .venv/bin/python -e .; \
      elif [[ -f requirements.txt ]]; then uv pip install --python .venv/bin/python -r requirements.txt; fi)
  else
    python3 -m venv backend/.venv
    if [[ -f backend/requirements.txt ]]; then backend/.venv/bin/pip install -r backend/requirements.txt; fi
  fi
fi
if [[ $RUN_WEB -eq 1 && ! -d frontend/node_modules ]]; then
  echo "[dev] 安装前端依赖 (pnpm install)..."
  (cd frontend && pnpm install)
fi

port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
PORTS=()
[[ $RUN_API -eq 1 ]] && PORTS+=("$BACKEND_PORT")
[[ $RUN_WEB -eq 1 ]] && PORTS+=("$FRONTEND_PORT")
for p in "${PORTS[@]}"; do
  if port_busy "$p"; then echo "[dev] 端口 $p 已被占用，请先停止占用进程" >&2; exit 1; fi
done

PIDS=()
cleanup() {
  echo; echo "[dev] 正在停止..."
  for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

prefix() { local tag="$1"; while IFS= read -r line; do printf '%s %s\n' "$tag" "$line"; done; }

# ---------- backend ----------
if [[ $RUN_API -eq 1 ]]; then
(
  cd backend
  exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" \
    ${ZM_RELOAD:+--reload}
) > >(prefix "[api]") 2>&1 &
PIDS+=($!)
fi

# ---------- frontend ----------
if [[ $RUN_WEB -eq 1 ]]; then
(
  cd frontend
  if [[ $FRONT_PROD -eq 1 ]]; then
    pnpm build && exec pnpm exec next start -p "$FRONTEND_PORT"
  else
    exec pnpm exec next dev -p "$FRONTEND_PORT"
  fi
) > >(prefix "[web]") 2>&1 &
PIDS+=($!)
fi

# ---------- wait for health ----------
wait_url() { # name url seconds
  for _ in $(seq 1 "$3"); do
    if curl -fsS -o /dev/null "$2" 2>/dev/null; then echo "[dev] $1就绪  $2"; return 0; fi
    sleep 1
  done
  echo "[dev] ⚠ $1在 $3 秒内未就绪：$2（查看上方 [api]/[web] 日志）" >&2
}
[[ $RUN_API -eq 1 ]] && wait_url 后端 "http://127.0.0.1:$BACKEND_PORT/api/health" 90
[[ $RUN_WEB -eq 1 ]] && wait_url 前端 "http://127.0.0.1:$FRONTEND_PORT/" 120

wait -n "${PIDS[@]}"
echo "[dev] 有进程退出，停止全部服务" >&2
