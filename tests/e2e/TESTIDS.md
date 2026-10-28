# data-testid contract used by the Playwright suite (QA → frontend)

Tests look up `data-testid` first and fall back to the visible Chinese label in brackets, so either works —
but test ids make the suite stable. Page routes are discovered by clicking, not hard-coded.

| Area | data-testid | Fallback text / role | Notes |
|---|---|---|---|
| Home | `prompt-input` | textarea/input placeholder containing 一句话 / 主题 | world theme |
| Home | `generate-btn` | button 「造化」 | starts SSE generation |
| Home | `minor-mode-toggle` | 「未成年人模式」 | checkbox/switch |
| Home | `education-entry` | link/button 「教育模式」 | goes to education page |
| Generation | `generation-progress` | — | visible while progress events stream |
| Preview | `world-preview` | — | container |
| Preview | `world-map` | 「地图」 | map with location nodes |
| Preview | `character-list` | 「角色」 | each item `character-item` |
| Preview | `initial-conflict` | 「冲突」 | |
| Preview | `confirm-world-btn` | button 「进入世界」/「确认」 | |
| Preview | `regenerate-btn` | 「重新生成」 | |
| Preview | `world-detail-enriching` | — | v1.2 两步生成：细节补全中 |
| Preview | `refine-current` | — | 重新生成时的调整要求 |
| Play | `narration` | — | the narration log; latest turn `narration-latest` |
| Play | `option-btn` | — | every current option button |
| Play | `free-input` | textarea placeholder containing 行动/输入 | |
| Play | `send-btn` | button 「发送」/「行动」 | |
| Play | `thinking-indicator` | — | visible while streaming |
| Play | `retry-btn` | 「重试」 | |
| Play | `offscreen-panel` | 「场外」 | off-screen events, items `offscreen-event` |
| Play | `illustration` | `img` | scene illustration |
| Play | `audio-player` | `audio` | narration TTS |
| Play | `genui` | — | generative UI area; each panel `ui-<type>` e.g. `ui-status_panel`, `ui-relationship_graph`, `ui-inventory`, `ui-map` |
| Play | `ai-label` | 「内容由AI生成」 | AI content marker — only rendered when built with `NEXT_PUBLIC_ZM_SHOW_AI_LABEL=1` (hidden by default per user request; run e2e with `ZM_SHOW_AI_LABEL=1` to assert it) |
| Play | `report-btn` | 「举报」 | opens report dialog; submit `report-submit` |
| Play | `safety-notice` | — | blocked/crisis message |
| Memory | `memory-query-input` / `memory-query-btn` / `memory-answer` / `citation` | 「回忆」/「记忆」 | F4 query |
| Memory | `memory-loading` / `memory-error` | — | 提问进行中 / 失败提示（中文） |
| God | `god-view-btn` | 「上帝视角」 | |
| God | `npc-card` | — | one per NPC, contains `npc-trajectory` |
| God | `inject-input` / `inject-btn` | 「插入事件」 | |
| Save | `export-btn` | 「导出存档」 | downloads JSON |
| Save | `import-input` | input[type=file] | |
| Share | `poster-btn` / `poster` | 「海报」 | `poster-download` optional |
| Share | `video-btn` | 「短视频」 | ending short video export (webm/mp4) |
| Edu | `edu-source-input` / `edu-generate-btn` | 「课文」/「生成」 | |
| Edu | `knowledge-card` | 「知识卡」 | |
| Edu | `edu-summary-btn` / `edu-summary` | 「学习小结」/「小结」 | |
| Edu | `edu-summary-pending` | — | v1.2 先显示的本地小结，随后替换为 AI 版 |
| Edu | `edu-summary-loading` / `edu-summary-error` / `edu-summary-retry` | 「重试」 | 小结加载中 / 失败 / 重试（BUG-007） |

## 账号（feat/auth，前端已实现的 testid）
| Area | data-testid | Notes |
|---|---|---|
| Register | `register-form` / `register-username` / `register-nickname` / `register-password` / `register-confirm` / `register-submit` / `register-error` | `/register` |
| Login | `login-form` / `login-username` / `login-password` / `login-submit` / `login-error` | `/login?next=` |
| Header | `user-menu-btn` / `user-nickname` / `user-avatar` / `user-menu` / `user-menu-profile` / `user-menu-logout` / `auth-login-link` / `auth-register-link` | 未登录显示登录/注册链接 |
| Me | `me-page` / `me-nickname` / `me-tab-<overview|profile|security|works|learning|prefs>` / `me-panel-<tab>` | `/me?tab=works` 直达 |
| Works | `works-list` / `work-item` / `works-loading` / `works-empty` | 我的作品 |
