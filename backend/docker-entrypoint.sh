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
# 账号系统：空值视为未设置 → 后端自动生成并持久化到数据卷（$ZM_DATA_DIR/jwt_secret、demo_password.txt，0600）；从不打印
[ -z "${ZM_JWT_SECRET:-}" ] && unset ZM_JWT_SECRET
[ -z "${ZM_DEMO_PASSWORD:-}" ] && unset ZM_DEMO_PASSWORD
[ -z "${ZM_AUTH_REQUIRED:-}" ] && unset ZM_AUTH_REQUIRED
echo "[entrypoint] 账号系统：ZM_AUTH_REQUIRED=${ZM_AUTH_REQUIRED:-0}，JWT 密钥$( [ -n "${ZM_JWT_SECRET:-}" ] && echo '取自环境变量' || echo '自动生成/沿用数据卷中的文件')"
mkdir -p "${ZM_DATA_DIR:-/data}/assets" "${ZM_DATA_DIR:-/data}/chroma" "${ZM_DATA_DIR:-/data}/avatars"
exec "$@"
