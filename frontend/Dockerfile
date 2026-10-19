# 《织梦》前端：Next.js standalone，多阶段构建，监听 3000
# 注意：Next 的 rewrites 目标在构建期写入 → BACKEND_ORIGIN 作为构建参数（compose 内为 http://backend:8000）
FROM node:22-slim AS base
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH NEXT_TELEMETRY_DISABLED=1
RUN corepack enable && corepack prepare pnpm@10.31.0 --activate
WORKDIR /app

FROM base AS deps
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

FROM base AS build
ARG BACKEND_ORIGIN=http://backend:8000
ARG ZM_PROXY_TIMEOUT_MS=180000
ENV BACKEND_ORIGIN=$BACKEND_ORIGIN ZM_PROXY_TIMEOUT_MS=$ZM_PROXY_TIMEOUT_MS NEXT_OUTPUT=standalone
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm exec next build

FROM node:22-slim AS runner
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /app
RUN useradd -r -u 10001 zm
COPY --from=build --chown=zm /app/.next/standalone ./
COPY --from=build --chown=zm /app/.next/static ./.next/static
COPY --from=build --chown=zm /app/public ./public
USER zm
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.js"]
