#!/usr/bin/env bash
# QA 一键回归：API 冒烟 (pytest, 进程内兜底模式) + Playwright E2E (需应用已运行)
#   scripts/qa.sh            # 全部
#   scripts/qa.sh api        # 只跑 API 冒烟（兜底模式）
#   scripts/qa.sh api-real   # API 冒烟 + 契约测试走真实模型（DASHSCOPE_API_KEY 取自环境或 .env，输出中密钥一律打码）
#   scripts/qa.sh e2e        # 只跑 E2E（ZM_WEB / ZM_API 可覆盖地址）
# 结果写入 docs/qa-report.md
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
WHAT="${1:-all}"
REPORT=docs/qa-report.md
mkdir -p docs
{
  echo "# QA 回归报告"
  echo
  echo "- 时间: $(date '+%F %T %Z')"
  echo "- 提交: $(git rev-parse --short HEAD 2>/dev/null) ($(git log -1 --format=%s 2>/dev/null))"
} > "$REPORT"

# 控制成本：真实模型回归默认不调用图像生成（ZM_DISABLE_IMAGE=1，插画走占位）；可显式覆盖
export ZM_DISABLE_IMAGE="${ZM_DISABLE_IMAGE:-1}"

# 输出打码：任何形似密钥的串都替换掉
mask() { sed -E 's/sk-[A-Za-z0-9_-]{8,}/sk-***/g'; }

API_RC=0; E2E_RC=0
if [[ "$WHAT" == api-real ]]; then
  if [[ -z "${DASHSCOPE_API_KEY:-}" && -f .env ]]; then
    DASHSCOPE_API_KEY="$(grep -E '^DASHSCOPE_API_KEY=' .env | tail -1 | cut -d= -f2-)"; export DASHSCOPE_API_KEY
  fi
  if [[ -z "${DASHSCOPE_API_KEY:-}" ]]; then echo "未配置 DASHSCOPE_API_KEY，无法跑真实模型模式" >&2; exit 2; fi
  echo "== API smoke (real model, in-process) =="
  OUT=$(cd backend && ZM_QA_REAL=1 ZM_FORCE_FALLBACK=0 .venv/bin/python -m pytest tests/integration -q -rA --no-header -p no:cacheprovider 2>&1 | mask); API_RC=${PIPESTATUS[0]}
  echo "$OUT" | tail -40
  { echo; echo "## API 冒烟 (pytest, 真实模型) rc=$API_RC"; echo; echo '```'; echo "$OUT" | grep -E "^(PASSED|FAILED|ERROR)|passed|failed|error" | tail -40; echo '```'; } >> "$REPORT"
fi
if [[ "$WHAT" == all || "$WHAT" == api ]]; then
  echo "== API smoke (fallback, in-process) =="
  OUT=$(cd backend && ZM_FORCE_FALLBACK=1 .venv/bin/python -m pytest tests/integration -q -rA --no-header -p no:cacheprovider 2>&1 | mask); API_RC=${PIPESTATUS[0]}
  echo "$OUT" | tail -40
  { echo; echo "## API 冒烟 (pytest, 兜底) rc=$API_RC"; echo; echo '```'; echo "$OUT" | grep -E "^(PASSED|FAILED|ERROR)|passed|failed|error" | tail -40; echo '```'; } >> "$REPORT"
fi
if [[ "$WHAT" == all || "$WHAT" == e2e ]]; then
  WEB="${ZM_WEB:-http://localhost:3000}"
  if curl -fsS -o /dev/null "$WEB" && curl -fsS -o /dev/null "${ZM_API:-http://localhost:8000}/api/health"; then
    echo "== Playwright E2E =="
    OUT=$(cd tests/e2e && pnpm exec playwright test --project=ac --reporter=list 2>&1 | mask); E2E_RC=${PIPESTATUS[0]}
    echo "$OUT" | tail -60
    { echo; echo "## E2E (Playwright) rc=$E2E_RC"; echo; echo '```'; echo "$OUT" | grep -E "✓|✘|passed|failed|skipped|flaky" | tail -40; echo '```'; } >> "$REPORT"
  else
    echo "应用未运行（$WEB），跳过 E2E。先执行 scripts/dev.sh"
    { echo; echo "## E2E 跳过：应用未运行"; } >> "$REPORT"
  fi
fi
echo "报告: $REPORT"
exit $(( API_RC | E2E_RC ))
