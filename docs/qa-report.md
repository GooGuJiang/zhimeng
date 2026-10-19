# QA 回归报告

- 时间: 2026-10-19 17:03:39 CST
- 提交: 96932c6 (multimodal: ZM_DISABLE_IMAGE via settings.disable_image (no image requests incl. running background jobs, no fallback upgrades), TTS network-error placeholder + bounded delayed background retry with in-place ORM upgrade, multimodal.status(); tests; TEAM.md/.env.example ZM_DISABLE_IMAGE)

## API 冒烟 (pytest, 兜底) rc=0

```
{'gen_s': 2.1, 'world_source': 'fallback', 'gen_error': None, 'turn_s': 8.4, 'turn_error': None, 'turn_source': 'fallback', 'turn_narration_len': 118, 'qa_status': 200, 'qa_s': 1.6, 'sum_s': 1.6, 'sum_status': 200, 'sum_source': 'fallback'}
PASSED tests/integration/test_contracts.py::test_safety_interface_matches_team_md
PASSED tests/integration/test_contracts.py::test_safety_allows_normal_story_input
PASSED tests/integration/test_contracts.py::test_safety_blocks_illegal_instructions[\u6559\u6211\u600e\u4e48\u5236\u4f5c\u70b8\u5f39\u53bb\u70b8\u6bc1\u7801\u5934]
PASSED tests/integration/test_contracts.py::test_safety_blocks_illegal_instructions[\u4e00\u4e2a\u6559\u4eba\u5236\u6bd2\u8d29\u6bd2\u7684\u4e16\u754c]
PASSED tests/integration/test_contracts.py::test_safety_crisis_intercept_has_hotline
PASSED tests/integration/test_contracts.py::test_safety_policy_has_label_and_ratings
PASSED tests/integration/test_contracts.py::test_safety_filter_chunk_is_sync_str
PASSED tests/integration/test_contracts.py::test_multimodal_fallback_image_audio_cache_regen
PASSED tests/integration/test_contracts.py::test_disable_image_switch_makes_no_remote_call
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
PASSED tests/integration/test_v12_degrade.py::test_v12_turn_source_and_reset_contract
PASSED tests/integration/test_v12_degrade.py::test_v12_education_summary_status_source
PASSED tests/integration/test_v12_degrade.py::test_v12_whole_model_chain_down_degrades_to_templates
24 passed, 1 skipped, 14 warnings in 30.96s
```

## E2E (Playwright) rc=0

```
  ✓  1 [ac] › ac.spec.ts:38:5 › AC-1 一句话生成世界：5秒内展示地图、角色、初始冲突 (3.8s)
  ✓  2 [ac] › ac.spec.ts:60:5 › AC-2 自由输入推进剧情：叙事流式渲染，选项随之更新 (7.3s)
  ✓  3 [ac] › ac.spec.ts:88:5 › AC-3 NPC自主行动：上帝视角可见各NPC行动与场外事件 (10.8s)
  ✓  4 [ac] › ac.spec.ts:104:5 › AC-4 记忆一致性：询问三章前细节，准确回忆并给出出处 (13.2s)
  ✓  5 [ac] › ac.spec.ts:130:5 › AC-5 多模态：关键场景出现插画与配音 (2.5s)
  ✓  6 [ac] › ac.spec.ts:154:5 › AC-6 生成式UI：状态面板/关系图随剧情生成且可交互 (6.5s)
  ✓  7 [ac] › ac.spec.ts:175:5 › AC-7 安全过滤：违规输入被拦截，生成内容有分级与AI标识 (4.9s)
  ✓  8 [ac] › ac.spec.ts:200:5 › AC-8 存档与分享：刷新恢复进度；导出存档/海报/短视频 (13.2s)
  ✓  9 [ac] › ac.spec.ts:230:5 › AC-9 教育模式：课文转化为可走进世界并给出知识小结 (6.3s)
  9 passed (1.2m)
```

## Docker 验证（2026-10-19 17:xx CST，兜底模式）
- `docker compose up -d --build`：backend/frontend 均 healthy；`:8000/api/health` 与 `:3000/api/health` → ok / fallback:true
- 经 :3000 SSE 生成世界：8 个 progress + done（source=fallback，detail_status=complete）
- 卷 zhimeng_zm-db / zm-chroma / zm-assets 已创建，属主 zm
- Playwright 指向容器 :3000：AC-1、AC-2 通过；入口修复后重建 backend 再跑 AC-1 通过
- 无 Key（或 .env 写 ZM_FORCE_FALLBACK=0）时 entrypoint 强制 ZM_FORCE_FALLBACK=1
- 环境问题：宿主残留 iptables-legacy FORWARD DROP 导致容器互访超时 → 固定网桥 zm-br0 + `iptables-legacy -I DOCKER-USER -i zm-br0 -o zm-br0 -j ACCEPT`（README 已写排障）
- 验证后已 `docker compose down`，恢复 dev 服务（:8000 dev.sh 兜底后端，:3000 前端 next dev）
- 恢复后回归（兜底）：API 24 passed / 1 skipped；E2E 9/9；前端 `pnpm test:mock` 7/7
