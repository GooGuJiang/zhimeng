#!/bin/sh
# 未配置 DASHSCOPE_API_KEY（为空）时强制本地兜底模式；从不打印密钥
set -e
if [ -z "${DASHSCOPE_API_KEY:-}" ]; then
  unset DASHSCOPE_API_KEY
  export ZM_FORCE_FALLBACK=1
  echo "[entrypoint] 未配置 DASHSCOPE_API_KEY → 本地兜底模式"
else
  echo "[entrypoint] DASHSCOPE_API_KEY 已配置 → 阿里云百炼模式（ZM_FORCE_FALLBACK=${ZM_FORCE_FALLBACK:-0}）"
fi
mkdir -p "${ZM_DATA_DIR:-/data}/assets" "${ZM_DATA_DIR:-/data}/chroma"
exec "$@"
