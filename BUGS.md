# BUGS（QA 维护）

格式：`ID | 状态 | Owner | 标题` + 复现 / 期望 / 实际。状态：OPEN → FIXED(待复测) → VERIFIED / WONTFIX。
Owner：`backend`（核心）、`frontend`、`safety-mm`（安全+多模态）、`qa`。

| ID | 状态 | Owner | 标题 |
|---|---|---|---|
| BUG-001 | VERIFIED | backend | 后端入口 `backend/app/main.py`（`app.main:app`）不存在，API 冒烟 12 项全部 ERROR，dev.sh 无法启动后端 |
| BUG-002 | VERIFIED | safety-mm（默认值在 backend `app/config.py`） | 真实模型模式配音失败：默认 `TTS_MODEL=qwen-tts` 返回 404 “Model not exist.”，自动降级为静音占位 |
| BUG-003 | VERIFIED | frontend | 首页 `GET /` 返回 500：`src/app/page.tsx` 仍是模板且 import 已删除的 `./page.module.css` |
| BUG-004 | VERIFIED | backend | API.md 写静态资源路径为 `/static/assets/<file>`，而 TEAM.md 与 `app/multimodal/assets.py` 实际为 `/api/static/assets/<file>` |
| BUG-005 | VERIFIED | safety-mm | 兜底模式下同一 prompt 多次 `illustrate()` 每次都新建一条 asset 行（文件复用），与 API.md「按 prompt hash 缓存」不一致，资产列表会膨胀 |
| BUG-007 | VERIFIED | frontend（+backend 时延） | 真实模型模式「学习小结」弹窗显示 `Internal Server Error`：`/education/summary` 耗时 >30s，Next 代理 `socket hang up`(ECONNRESET) |
| BUG-006 | VERIFIED | backend | 真实模型模式下 LLM 限流(429)/流中断时回合直接失败（`error` / 前端「本回合生成失败（LLMUnavailable）」），未自动降级到本地兜底模板 |

### BUG-001 后端入口缺失（阻塞全部 API / E2E）
- 复现：`scripts/qa.sh api` 或 `scripts/dev.sh --fallback`（2026-10-19 14:55 CST，HEAD 17a1cfa + 工作区）
- 实际：`ModuleNotFoundError: No module named 'app.main'`；dev.sh 预检提示入口不存在并退出
- 期望：`backend/app/main.py` 暴露 `app`，挂载 `/api/*` 路由、`/api/static/assets`，`GET /api/health` 快速返回（TEAM.md）
- 修复：提交 44028e0
- 复测（15:2x CST）：VERIFIED。`app.main:app` 可导入；兜底模式 API 冒烟 12/12 通过；`dev.sh --fallback` / `--prod` 前后端均就绪；`/api/health` 返回 `fallback` 字段

### BUG-002 qwen-tts 模型不存在
- 复现：`scripts/qa.sh api-real` → `test_contracts.py::test_multimodal_fallback_image_audio_cache_regen`；日志 `tts failed: InvalidParameter: Model not exist.`
  直接调用 `POST {dashscope}/services/aigc/multimodal-generation/generation`：`model=qwen-tts` → 404；`model=qwen3-tts-flash`（voice=Cherry）→ 200 并返回音频 URL
- 期望：真实模型模式下 `speak()` 返回 `source="dashscope"` 的音频。建议默认改为 `qwen3-tts-flash`，或失败时自动换模型重试
- 备注：同一轮 LLM 审核/调用出现 429 限流（`limit_requests`），关键词层仍能拦截；建议审核调用做限流退避
- 修复：提交 390085e（默认 qwen3-tts-flash）+ d7f688b（qwen-tts 别名映射 + “Model not exist” 自动重试）
- 复测（15:2x CST，ZM_QA_REAL=1，密钥未输出）：VERIFIED。`/api/health` models.tts=qwen3-tts-flash；契约测试 `speak()` 返回 source=dashscope；
  新增 `test_tts_legacy_model_name_still_works`：显式 `model="qwen-tts"` 仍拿到音频 → 通过

### BUG-003 首页 500（14:58 CST 复测：GET / → 200，已含 prompt-input/generate-btn 等 testid，VERIFIED）
- 复现：`scripts/dev.sh --fallback --web-only`，`curl -i http://localhost:3000/` → 500，`Module not found: Can't resolve './page.module.css'`
- 期望：首页渲染「造化」入口（`prompt-input` / `generate-btn`，见 tests/e2e/TESTIDS.md）

### BUG-004 静态资源路径文档不一致
- 期望：API.md 改为 `/api/static/assets/<file>`（前端代理 `/api/*` 与 `/static/*` 都可用，但契约应唯一）
- 修复：提交 ea88084
- 复测：VERIFIED。资产 url 以 `/api/static/assets/` 开头且可下载；旧 `/static/assets/` 别名返回 200（已加入 `test_ac5_multimodal_assets`）

### BUG-005 兜底插画不去重
- 复现：`multimodal.illustrate(wid, p)` 连续调用两次 → 两个不同 id、相同 url
- 期望：同一世界同一 prompt 返回同一 asset（或在 API.md 中说明兜底不缓存）
- 修复：d7f688b
- 复测：VERIFIED。兜底与真实模式下同一世界+同一 prompt 的 `illustrate`/`speak` 均返回同一 id，`list_assets` 无重复行（契约测试已收紧）；
  直接验证「兜底→有 Key 原地升级」：临时数据目录先兜底生成图+音，切到真实模式再调同 prompt → id 不变、source 变为 dashscope、行数仍为 2

### BUG-006 真实模型回合失败不降级
- 复现 1：`ZM_QA_REAL=1` 跑 `test_ac4_memory_recall_with_citation`（13 回合，15:0x–15:2x CST）：日志多次 `RateLimitError 429 limit_requests`、
  `APIConnectionError`、`httpx RemoteProtocolError: peer closed connection without sending complete message body`，`turn_graph.py:473 turn failed`；
  若干回合未提交 → `assert turns[-1]["chapter"] >= 3` 失败（实际 2）
- 复现 2：`scripts/dev.sh --prod`（真实模型）+ `ZM_MODE=real pnpm exec playwright test --project=ac`：AC-2 点选项后显示「本回合生成失败（LLMUnavailable），进度未受影响，请重试」
- 期望：plan.md 异常流程「模型超时/失败 → 提示重试**并提供本地兜底模板**」、非功能「单次生成失败自动重试 ≥1 次且不丢进度」：
  流式中断/限流时服务端至少自动重试一次，仍失败则用兜底模板完成本回合（`source=fallback`），而不是让回合失败
- 备注：同一个 Key 同时被多个代理/测试使用，限流更容易触发；QA 测试已按 API.md 在 `error` 时由客户端重发/点「重试」，并在报告中记录重试次数
- 修复：提交 c066acf（+ fdf6410 断流续写）。模型链全部失败 → 本地模板完成并提交（`done.turn.source="fallback"`）；已出 token 后断流先续写，续写用尽 →
  `progress{stage:"fallback",reset:true}` 后整段兜底重写（以 `done.turn.narration` 为准）；NPC/世界 Agent/记忆问答/章节摘要/抽取同样本地兜底。
  单测：backend/tests/core/test_bug006_007.py（模拟全链 429、首字后断流）

- 复测（16:3x–16:5x CST，HEAD bf5239a/cc2aa9e）：VERIFIED。
  - 新增黑盒用例 `test_v12_whole_model_chain_down_degrades_to_templates`：假 Key + 不可达 DashScope 地址（全链失败）→ 世界 `source=fallback`、回合无 `error` 且
    `done.turn.source="fallback"`、记忆问答 200、学习小结 200/fallback（回合 8.5s，小结 1.6s）
  - 真实模型 API 24/24 通过（含 13 回合 AC-4，此前因回合失败未达 3 章）；`scripts/ttft.py` 4 回合 `source` 全为 llm、无 reset
  - 真实模型 E2E 未再出现「本回合生成失败（LLMUnavailable）」；首字后断流重置（`progress{stage:"fallback",reset:true}`）本轮未自然触发，由后端单测覆盖

### BUG-007 真实模型学习小结经代理超时
- 复现：`scripts/dev.sh --prod`（真实模型）+ `ZM_MODE=real pnpm exec playwright test --project=ac -g AC-9`（15:47 CST）：点「学习小结」→ 弹窗内容 `Internal Server Error`
- 证据：web 日志 `Failed to proxy http://localhost:8000/api/worlds/<id>/education/summary Error: socket hang up (ECONNRESET)`；同时后端在 qwen-plus 连接错误后重试/切换模型；
  事后直接 `curl :8000/.../education/summary` → 200，耗时 19s（含 LLM），返回完整小结
- 期望：小结在真实模型下可用。前端：提高 Next rewrite 代理超时（如 `experimental.proxyTimeout`）或直连后端，错误时给出友好提示+重试而非原样显示 `Internal Server Error`；
  后端：小结结果按世界+回合缓存、LLM 超时后用兜底模板生成，保证 <30s
- 修复（后端）：提交 c066acf。`/education/summary` 最多约 8s 返回：LLM 版（快速模型+短输入）在后台任务生成并按世界+回合缓存，未就绪时先返回本地小结
  `status:"pending", source:"fallback"`，再 GET 得 `status:"complete"`（字段向后兼容）。非流式 LLM 调用统一 8s 总时限（SYNC_LLM_TIMEOUT_S），
  安全审核 6s 时限后走规则层。真实 Key 实测：首次 8.0s pending/fallback，约 10s 后 3.6s complete/llm。前端代理超时/友好提示属前端
- 修复（前端）：6a8a2db / 18f8638 / 943e9a1（`experimental.proxyTimeout` 180s，可用 `ZM_PROXY_TIMEOUT_MS` 调整；长请求 120s；`edu-summary-loading/error/retry`、中文错误文案）
- 复测：VERIFIED。真实模型 API `test_v12_education_summary_status_source` 通过（≤8s 返回，pending 后续 GET 变 complete）；真实模型 E2E AC-9 通过（重跑一次，见备注 R-2），未再出现 Internal Server Error

## 备注（非阻塞，按放宽后的验收口径记录）

| ID | Owner | 内容 | 实测 |
|---|---|---|---|
| R-1 | safety-mm / backend | 真实模型回合首字延迟高于 plan.md 目标 ≤2s；瓶颈为输入审核 LLM 调用（v1.3 已改为规则层通过即开始叙事 + 后台复审） | 16:2x：中位 4.01s（3.26–5.14s，5 回合，v1.3 前）；16:5x HEAD：中位 3.48s（3.27–3.76s，4 回合）。兜底模式 0.04s |
| R-2 | frontend（v1.2 适配，待观察） | 真实模型 E2E AC-9 首跑：教育世界预览页点「进入世界」后 30s 内未进入游玩页，后端无 `/confirm` 请求（当时该世界仍在 `enriching`，后台补全约 108s）；单独重跑通过 | 16:49 首跑失败、16:57 重跑通过；按「429/网络类先重跑」口径未立为 bug |
| R-3 | backend / safety-mm | AC-1 真实模型预览时间 2.7–4.5s（两步生成骨架），细节补全在后台 60–110s | 达标；补全期间预览页显示 `world-detail-enriching` |
