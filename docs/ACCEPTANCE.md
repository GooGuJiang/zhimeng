# 验收用例 ↔ 测试映射（AC-1 ~ AC-10）

API 冒烟：`backend/tests/integration/test_smoke.py`（需 `app.main`）；包级契约：`backend/tests/integration/test_contracts.py`（不需路由）；
E2E：`tests/e2e/ac.spec.ts`；演示截图：`tests/e2e/demo.spec.ts`。运行方式见 README「测试」。

| AC | 验收点 | API / 契约测试 | E2E |
|---|---|---|---|
| AC-1 | 一句话 5 秒内出世界预览（地图/角色/冲突） | `test_ac1_generate_world_preview`（兜底模式断言 <5s） | `AC-1 …` |
| AC-2 | 自由输入推进，流式叙事，选项更新 | `test_ac2_turn_streams_and_updates_options`、`test_ac2_idempotent_and_retry` | `AC-2 …` |
| AC-3 | NPC 自主行动、场外事件、上帝视角 | `test_ac3_npc_autonomy_god_view`、`test_ac3_god_inject_leaves_trace` | `AC-3 …` |
| AC-4 | 三章前细节准确回忆并给出处 | `test_ac4_memory_recall_with_citation` | `AC-4 …` |
| AC-5 | 关键场景插画与配音 | `test_ac5_multimodal_assets`、`test_multimodal_fallback_image_audio_cache_regen` | `AC-5 …` |
| AC-6 | 生成式 UI 状态面板/关系图可交互 | `test_ac6_generative_ui` | `AC-6 …` |
| AC-7 | 违规拦截、危机热线、分级与 AI 标识、举报 | `test_ac7_safety`、`test_safety_*`（6 项） | `AC-7 …` |
| AC-8 | 刷新恢复、存档导入导出、海报/短视频 | `test_ac8_save_restore_share` | `AC-8 …` |
| AC-9 | 课文 → 可走进的世界 + 知识小结 | `test_ac9_education` | `AC-9 …` |
| AC-10 | 公网可用、评审账号 | 本轮跳过（部署不在当前范围） | — |

最新一次运行结果见 `docs/qa-report.md`，已知问题见 `BUGS.md`。
