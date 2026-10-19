# QA 回归报告

- 时间：2026-10-19 16:20–16:58 CST
- 代码：HEAD bf5239a（frontend v1.3）/ cc2aa9e（backend v1.3 + KEY_SCENE_MEDIA_DEADLINE_S）
- 验收口径：见 docs/ACCEPTANCE.md（外部时延类指标记为「通过（备注）」）

## 兜底模式（ZM_FORCE_FALLBACK=1，确定性）
- API 冒烟 + 契约 + v1.2 降级：**23 通过 / 1 跳过**（跳过项仅真实模式运行）
- E2E AC-1~AC-9（`scripts/dev.sh --fallback --api-only` + 前端 :3000）：**9/9 通过**（1.2m）
- 演示截图（独立 prod 构建 :3100，无 dev 浮层）：2/2 通过，`docs/screens/01-home.png` ~ `13-education-summary.png`

## 真实模型模式（DASHSCOPE_API_KEY 来自环境，输出打码；Key 与其他代理共用）
- API（`ZM_QA_REAL=1`）：**24/24 通过**（11m14s）；AC-1 预览 3.22s
- E2E（prod :3100 → 后端 :8000 真实模型）：首跑 7/9；AC-5 因 v1.3 pending 占位（测试未适配）失败 → 测试改为 `?wait=` 长轮询后通过；
  AC-9 首跑进入世界未生效 → 单独重跑通过（备注 R-2）。**最终 9/9**
- 首字延迟（`scripts/ttft.py`）：v1.3 前中位 4.01s（3.26–5.14）；HEAD 中位 **3.48s**（3.27–3.76），目标 ≤2s → 备注 R-1
- 世界预览：2.70s / 4.50s；回合总时长 16–23s（最长一次 61.7s，含首回合关键场景）

## Bug
- BUG-006、BUG-007：VERIFIED（详见 BUGS.md）；新增非阻塞备注 R-1~R-3
