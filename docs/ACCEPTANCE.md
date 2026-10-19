# 验收用例 ↔ 测试映射与结果（AC-1 ~ AC-10）

验收口径（2026-10-19 放宽）：受外部条件限制的指标（AC-1 的 5 秒、首字 ≤2s、百炼/DashScope 429 波动）——
**功能可用、降级合理、体验可接受即通过**，记为「通过（备注）」并记录实测数字与差距。取舍说明见 README「实际取舍」。

测试：API 冒烟 `backend/tests/integration/test_smoke.py`、包级契约 `test_contracts.py`、v1.2 降级 `test_v12_degrade.py`；
E2E `tests/e2e/ac.spec.ts`；演示截图 `tests/e2e/demo.spec.ts`；首字延迟 `scripts/ttft.py`。

## 结果（HEAD bf5239a / cc2aa9e，16:2x–16:5x CST）

| AC | 测试 | 兜底模式 API / E2E | 真实模型 API / E2E | 结论 | 实测 / 差距 |
|---|---|---|---|---|---|
| AC-1 | `test_ac1_generate_world_preview`；e2e AC-1 | 通过 / 通过 | 通过 / 通过 | 通过（备注） | 预览：兜底 <0.1s；真实 2.7–4.5s（两步生成骨架，达标），细节后台补全 60–110s |
| AC-2 | `test_ac2_*`、`test_v12_turn_source_and_reset_contract`；e2e AC-2 | 通过 / 通过 | 通过 / 通过 | 通过（备注） | 首字：兜底 0.04s；真实中位 3.48s（3.27–3.76s），目标 ≤2s 未达（备注 R-1）；回合总时长 16–23s |
| AC-3 | `test_ac3_*`；e2e AC-3 | 通过 / 通过 | 通过 / 通过 | 通过 | — |
| AC-4 | `test_ac4_memory_recall_with_citation`；e2e AC-4 | 通过 / 通过 | 通过 / 通过 | 通过 | 13 回合跨 3 章后准确回忆并给出处 |
| AC-5 | `test_ac5_multimodal_assets`、契约测试；e2e AC-5 | 通过 / 通过 | 通过 / 通过（修订后） | 通过（备注） | v1.3 关键场景先 pending 占位（≤3s），后台原地升级为 DashScope 图/音；测试按 `?wait=` 长轮询 |
| AC-6 | `test_ac6_generative_ui`；e2e AC-6 | 通过 / 通过 | 通过 / 通过 | 通过 | — |
| AC-7 | `test_ac7_safety`、`test_safety_*`；e2e AC-7 | 通过 / 通过 | 通过 / 通过 | 通过 | 举报列表按 world_id（API v1.2） |
| AC-8 | `test_ac8_save_restore_share`；e2e AC-8 | 通过 / 通过 | 通过 / 通过 | 通过 | — |
| AC-9 | `test_ac9_education`、`test_v12_education_summary_status_source`；e2e AC-9 | 通过 / 通过 | 通过 / 通过（重跑一次） | 通过（备注） | 小结 ≤8s（pending→complete）；首跑一次进入世界未生效（备注 R-2） |
| AC-10 | — | — | — | 跳过 | 公网部署不在本轮范围；提供 `docker compose` 一键部署 |

另：BUG-006 降级（模型全链不可用 → 本地模板，`source=fallback`）由 `test_v12_whole_model_chain_down_degrades_to_templates` 黑盒验证。

## 变更：可见 AI 标识默认隐藏（2026-10-19，用户要求）
- 用户要求移除界面上所有**可见**的 AI 生成标识（「内容由AI生成」徽标、插画角「AI 生成」、面板「AI 编排/AI 数据/本地生成」、占位插画「内容由AI生成 · 插画占位」、海报弹窗说明行、海报与短视频上印的标识文字）。
- 实现为单一开关：前端 `NEXT_PUBLIC_ZM_SHOW_AI_LABEL`（构建期，默认关 → 不渲染、无空位），后端 `ZM_SHOW_AI_LABEL`（占位 SVG 角标、万相 watermark 默认跟随；`ZM_IMAGE_WATERMARK` 可单独覆盖）。compose 用同一个 `ZM_SHOW_AI_LABEL` 驱动两者。
- 未改动：接口 `ai_generated` / `ai_label` / `safety_label` 字段、`ai_meta`、PNG iTXt 隐式元数据。
- AC-7 验收调整：e2e 仍校验接口标识字段；可见徽标仅在 `ZM_SHOW_AI_LABEL=1`（并以 `NEXT_PUBLIC_ZM_SHOW_AI_LABEL=1` 构建前端）时断言可见，默认断言 `[data-testid^=ai-label]` 数量为 0。后端单测 `test_placeholder_visible_label_switch` 覆盖两种状态。
- 合规提示：对外公开上线时，《人工智能生成合成内容标识办法》要求显式标识，届时应设 `ZM_SHOW_AI_LABEL=1`。
