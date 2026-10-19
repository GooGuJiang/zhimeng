#!/usr/bin/env bash
# QA 一键回归：API 冒烟 (pytest, 进程内兜底模式) + Playwright E2E (需应用已运行)
#   scripts/qa.sh            # 全部
#   scripts/qa.sh api        # 只跑 API 冒烟
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

API_RC=0; E2E_RC=0
if [[ "$WHAT" == all || "$WHAT" == api ]]; then
  echo "== API smoke (fallback, in-process) =="
  OUT=$(cd backend && ZM_FORCE_FALLBACK=1 .venv/bin/python -m pytest tests/integration -q -rA --no-header -p no:cacheprovider 2>&1); API_RC=$?
  echo "$OUT" | tail -40
  { echo; echo "## API 冒烟 (pytest) rc=$API_RC"; echo; echo '```'; echo "$OUT" | grep -E "^(PASSED|FAILED|ERROR)|passed|failed|error" | tail -40; echo '```'; } >> "$REPORT"
fi
if [[ "$WHAT" == all || "$WHAT" == e2e ]]; then
  WEB="${ZM_WEB:-http://localhost:3000}"
  if curl -fsS -o /dev/null "$WEB" && curl -fsS -o /dev/null "${ZM_API:-http://localhost:8000}/api/health"; then
    echo "== Playwright E2E =="
    OUT=$(cd tests/e2e && pnpm exec playwright test --project=ac --reporter=list 2>&1); E2E_RC=$?
    echo "$OUT" | tail -60
    { echo; echo "## E2E (Playwright) rc=$E2E_RC"; echo; echo '```'; echo "$OUT" | grep -E "✓|✘|passed|failed|skipped|flaky" | tail -40; echo '```'; } >> "$REPORT"
  else
    echo "应用未运行（$WEB），跳过 E2E。先执行 scripts/dev.sh"
    { echo; echo "## E2E 跳过：应用未运行"; } >> "$REPORT"
  fi
fi
echo "报告: $REPORT"
exit $(( API_RC | E2E_RC ))
