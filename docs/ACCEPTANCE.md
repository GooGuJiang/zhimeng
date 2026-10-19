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
