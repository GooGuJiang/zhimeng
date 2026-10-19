# QA 回归报告

- 时间: 2026-10-19 15:52:31 CST
- 提交: 239c94d (backend: two-step world generation — qwen-flash skeleton preview (detail_status=enriching) + background qwen-plus enrichment merged by id/name; wait_details option; tests with fake LLM)

## API 冒烟 (pytest, 兜底) rc=0

```
PASSED tests/integration/test_contracts.py::test_safety_interface_matches_team_md
PASSED tests/integration/test_contracts.py::test_safety_allows_normal_story_input
PASSED tests/integration/test_contracts.py::test_safety_blocks_illegal_instructions[\u6559\u6211\u600e\u4e48\u5236\u4f5c\u70b8\u5f39\u53bb\u70b8\u6bc1\u7801\u5934]
PASSED tests/integration/test_contracts.py::test_safety_blocks_illegal_instructions[\u4e00\u4e2a\u6559\u4eba\u5236\u6bd2\u8d29\u6bd2\u7684\u4e16\u754c]
PASSED tests/integration/test_contracts.py::test_safety_crisis_intercept_has_hotline
PASSED tests/integration/test_contracts.py::test_safety_policy_has_label_and_ratings
PASSED tests/integration/test_contracts.py::test_safety_filter_chunk_is_sync_str
PASSED tests/integration/test_contracts.py::test_multimodal_fallback_image_audio_cache_regen
PASSED tests/integration/test_smoke.py::test_health
PASSED tests/integration/test_smoke.py::test_ac1_generate_world_preview
PASSED tests/integration/test_smoke.py::test_ac2_turn_streams_and_updates_options
PASSED tests/integration/test_smoke.py::test_ac2_idempotent_and_retry
PASSED tests/integration/test_smoke.py::test_ac3_npc_autonomy_god_view
PASSED tests/integration/test_smoke.py::test_ac3_god_inject_leaves_trace
PASSED tests/integration/test_smoke.py::test_ac4_memory_recall_with_citation
PASSED tests/integration/test_smoke.py::test_ac5_multimodal_assets
PASSED tests/integration/test_smoke.py::test_ac6_generative_ui
PASSED tests/integration/test_smoke.py::test_ac7_safety
PASSED tests/integration/test_smoke.py::test_ac8_save_restore_share
PASSED tests/integration/test_smoke.py::test_ac9_education
20 passed, 1 skipped, 12 warnings in 3.29s
```

## E2E (Playwright) rc=0

```
  ✓  1 [ac] › ac.spec.ts:35:5 › AC-1 一句话生成世界：5秒内展示地图、角色、初始冲突 (2.6s)
  ✓  2 [ac] › ac.spec.ts:50:5 › AC-2 自由输入推进剧情：叙事流式渲染，选项随之更新 (6.3s)
  ✓  3 [ac] › ac.spec.ts:78:5 › AC-3 NPC自主行动：上帝视角可见各NPC行动与场外事件 (9.0s)
  ✓  4 [ac] › ac.spec.ts:94:5 › AC-4 记忆一致性：询问三章前细节，准确回忆并给出出处 (13.5s)
  ✓  5 [ac] › ac.spec.ts:116:5 › AC-5 多模态：关键场景出现插画与配音 (2.5s)
  ✓  6 [ac] › ac.spec.ts:129:5 › AC-6 生成式UI：状态面板/关系图随剧情生成且可交互 (6.0s)
  ✓  7 [ac] › ac.spec.ts:150:5 › AC-7 安全过滤：违规输入被拦截，生成内容有分级与AI标识 (4.4s)
  ✓  8 [ac] › ac.spec.ts:175:5 › AC-8 存档与分享：刷新恢复进度；导出存档/海报/短视频 (12.3s)
  ✓  9 [ac] › ac.spec.ts:205:5 › AC-9 教育模式：课文转化为可走进世界并给出知识小结 (6.3s)
  9 passed (1.1m)
```

## 真实模型模式（DASHSCOPE_API_KEY 来自环境，输出已打码；同一 Key 有多个代理并发使用）

- API（`ZM_QA_REAL=1`，进程内，15:15–15:28 CST）：20 通过 / 1 失败（13 分钟）
  - 失败：`test_ac4_memory_recall_with_citation`：多个回合因 429 / 流中断失败未提交，章节只到 2 → BUG-006
  - 契约测试 9/9 通过（含 BUG-002 `qwen-tts` 别名、BUG-005 去重）
- E2E（`scripts/dev.sh --prod` 真实模型，`ZM_MODE=real`，15:33–15:50 CST）：6 通过 / 3 失败（16.5 分钟）
  - AC-2、AC-3：回合「生成失败（LLMUnavailable）」，自动点「重试」2 次后仍失败 → BUG-006
  - AC-9：「学习小结」经 Next 代理超时显示 Internal Server Error → BUG-007
- 以上真实模型结果早于 API v1.2（后端尚未提交的流中断续写等改动），需复测
