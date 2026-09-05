# XEYO 三方设计对比研究 —— DSH × Codex × XEYO

> 产出背景：P0 收官后的系统性对比复盘。七张对比表（工具层 / 整体系统 / 企业级结构 / 设计深水区 / 待比清单 / 逐工具）+ 总判断。
> 方法：以本仓代码事实为准（XEYO 列全部可溯源到具体文件/任务编号），DSH/Codex 列基于其公开行为与可观察面。
> 更新：本轮（九节）已对 DSH/Codex 列做源码级取证修正（Codex=codex-rs 源码；DSH=npm 包可按读 `.d.ts`/README，bundle 内控制流不可见者如实标 ⚠️/⛔），并落实 XEYO 列「待确认」项——在 9.4 的实质影响中说明，详见「九、源码核实修正记录」。
> 日期：P0 批完成后（T25–T39、T1–T6、T12、T27/T28 全部 ✅，回归 285 passed + tsc 0）。
>
> **图例**：状态列——✅ 已完成/优势保持（附任务号）/ 🔶 部分完成 / ❌ 未做；优先级列——**P1**=下一批（P1 结构批任务号）/ **P2**=P2 立项候选 / **P3**=记录性、暂不立项 / **—**=优势保持，无需动作。

---

## 一、工具层对比

| 维度 | 状态 | 优先级 | DSH（DeepSeek Harness） | Codex Harness | XEYO（你的项目） | 谁更好 | XEYO 值得借鉴 | 差距在哪 |
|---|---|---|---|---|---|---|---|---|
| **工具输出经济** | ✅ P0·T1（bash 另有 cmd_compact 命令族语义压缩，**领先两家**——本次核实修正） | P2（诊断日志通道/API 级 token 计数） | spill seam + registry 预算截断 | 模型可见输出/诊断日志分离，per-tool 预算 | 16k 预算+spill+per-tool 豁免+bash 30k 中段截断全量落盘+**cmd_compact 语义压缩** | **XEYO 最细（唯一有语义压缩层）** | 还可抄**诊断日志独立通道** | Read 的 token 计数是 chars/4 粗估（TODO API 级）；语义压缩仅覆盖 bash 命令族 |
| **重复调用治理** | ✅ P0·T6 | P2（豁免配置化） | repeat-tool-reminder：只提醒、不拒执行（非模型工具，`dsh-repeat-tool-reminder/README.md:5`），默认 `[3,5,8]` 递进（`:13`），经 post-execute `additionalContexts` 注入为 `user/message`（`:35`） | 分级提示 + 豁免清单（合法重试显式声明） | 已吸收：[3,5,8] 递进、block 删除、denied 也计数 | DSH 语义更优 | T_now 注入已抄；可再抄**豁免声明进工具 schema** | 豁免还是「分页签名」隐式判定，Codex 显式配置化 |
| **审批协议** | ✅ P0·T3 | P1（服务端提醒帧接线）/ P2（decision latency 审计） | 四值结果 + intent 分面板 + Esc 恒=Cancel + 成对审计 | turn 结束自动 resolve + 过期即拒绝 | 已吸收：TTL 分级（60/180/∞）、三态文案、intent 渲染、成对审计 | DSH 更完整 | 已基本抄齐；可再抄**审批耗时进审计** | 30s 提醒是客户端倒计时，服务端帧未接线（on_event 无消费方，已知债务） |
| **并发模型** | ✅ P0·T2+T39 | P2（工具级超时隔离/跨进程互斥） | 状态机闸门（双闸、turn 守卫） | 工具编排层 RWLock（写优先）+ 取消归一 | 两者都要了：RW 锁进 orchestration，状态机闸进 query_engine | 互补 | 可再抄 Codex **工具级超时与兄弟隔离** | 多进程靠「单 worker 硬约束」回避 |
| **崩溃恢复** | ✅ P0·T4 | P2（恢复自动汇报） | checkpoint-policy 双时机 + 未闭合合成 | 配对合成 + 风险分级（NOT_STARTED vs OUTCOME_UNKNOWN） | hydrate 合成 + 双时机刷盘 | Codex 分级更细 | 已抄齐；可再抄**恢复后自动汇报** | 刷盘失败「跳过+合成兜底」比 fail-closed 宽松 |
| **会话标题** | ✅ P0·T5 | P3（全局搜索索引） | session-title 三态 | instant+enhance+pin | sidecar 持久化、pinned 圣旨、SSE title 帧 | 持平 | 已抄齐 | Codex 标题进全局索引，XEYO 只服务列表 |
| **错误呈现** | ✅ P0·T34 | P3（白名单式构造） | friendly_error 过滤+人话+可展开 | 人话 + 原始错误折叠 | 过滤器+safe_error+GUI 边界组件 | 持平 | 已抄齐 | 正则黑名单会漏新痕迹类型 |
| **扩展生态** | ❌ | **P1·T11** | skill 系统：SKILL.md 渐进加载+manifest | MCP+rules+hooks+automations 最富 | 骨架有（extension/ 统一发现单元），默认关闭 | **Codex 大幅领先** | rules 与 hooks 进 P2 | 设计完未通电：无运行时验证、无插件沙箱 |
| **多 Agent** | 🔶 | **P1·T14**（P2·workflow 编排） | 子 agent 会话树 + 结构化报告跨轮 | subagents + workflow 脚本编排 | WriteStore 单写者队列 + agent 工具；通知归因/角色文件缺 | Codex 表达力最强 | workflow 脚本化编排值得 P2 立项 | 稳定性未经实战（子代理曾连败） |
| **Goal/长任务** | ❌ | **P1·T9** | goal 状态机（blocked 需 3 轮证据+轮次帽） | thread_goals 落盘 + automations | 无 | DSH 最完整 | **DSH goal 状态机是 P1 最高性价比单笔** | 长任务=手动续 prompt，断线丢上下文 |
| **记忆/上下文管理** | ✅ 领先 | —（P2·T_now 注册表） | T_now 注入 + compaction | compaction + MEMORY.md + rules | C1/C2 双层压缩 + proj_cache 增量 + KV 前缀保序（原创优势区） | **XEYO 领先** | 反向输出：KV 前缀字节稳定 | DSH 查重清单制度化 vs XEYO 口头约定 |
| **工程卫生** | ❌ | **P1·T35** | CI 矩阵、gen 文件 diff 门禁 | lint/format/coverage 全齐 | 手工 pytest+tsc，无 CI | Codex 领先 | gen 漂移门禁直接抄 | T12/T26 语义可能被静默破坏 |
| **可观测性** | 🔶 | **P1·T13** | 审计 JSONL + read API | correlation id + trace | 审计 JSONL + ActivityLog，无 id 串联 | Codex 领先 | correlation id 贯穿 | 排障靠人工 tail 拼时间线 |
| **交付体验** | ❌ | **P1·T32**（P2·遥测） | — | installers/自动更新/遥测 | Tauri 手工打包 | Codex 领先 | 自动更新通道 | 装机/升级成本高 |

> **表一·证据等级**：✍️ 已源码证实的 DSH/Codex 断言——审批四值+policy（`dsh-user-approval/types.d.ts:23`、`index.d.ts:81`）、job 工具集（`dsh-tool-jobs/index.d.ts:2-7`）、goal 状态机（`dsh-goal/types.d.ts:37`、`domain.d.ts:12`）、repeat-reminder 不拒执行（`dsh-repeat-tool-reminder/README.md:5,13`）、subagent/fork/workflow/ralph（`dsh-tool-*` 包存在）、execpolicy 规则引擎（`codex-rs/execpolicy/src/decision.rs:9-16`）、shell 沙箱三级（`core/src/config/mod.rs:491,503`）、automations（`tools/handlers/tool_search.rs:366` + `Feature::InAppLocalAutomation`）。⚠️ 未能源码钉死、如实在 §9 降级——Codex「installers/自动更新/遥测」「friendly_error 过滤」为客户端/分发行为（需 `codex-cli`/安装器，未取证）；「checkpoint 双时机」见 §9 待核。⚠️ DSH「session-title 三态」「friendly_error」「CI 矩阵」「gen 文件 diff 门禁」未获 zsh/字符串命中，标 ⛔（bundle 内）或未取证。

---

## 二、整体 Agent 系统对比

| 系统层 | 状态 | 优先级 | DSH | Codex | XEYO | 谁更好 | XEYO 值得借鉴 | 差距在哪 |
|---|---|---|---|---|---|---|---|---|
| **总体架构** | ✅ 保持 | — | 单 harness 进程 | CLI 优先 + 云端 Automations，多入口共享 thread | 三入口严格分层，**系统提示词只在 Python 后端** | 理念 XEYO 更干净，广度 Codex 更大 | 保持「共 manifest 不共运行时」防双头漂移 | Codex 多入口共享存储=随处续聊 |
| **主循环** | ✅ 领先 | —（P3·循环拆分重构，慎动） | 逐轮 + compaction checkpoint | 循环 + plan mode + 回溯 | query_loop：分区并发、早执行、强制 wrap-up、预算硬顶、xml 兜底 | **XEYO 防御密度最高** | 反向输出 | 1490 行单文件=维护风险 |
| **上下文管理** | ✅ 领先 | —（P2·T_now 注册表） | T_now + compaction | compaction + MEMORY.md + rules | KV 前缀稳定投影 + proj_cache + T_now + 旁白门控 | **XEYO 领先** | 反向输出 | 查重清单未制度化 |
| **工具系统** | ✅ P0 | **P1·T11** | 内置 + skill 目录 | 工具 + MCP + rules/hooks | ToolRegistry 统一门禁 + catalog 启动自检 | 执行层 XEYO 最严谨 | MCP/rules/hooks | 内核强、外延窄 |
| **权限/安全** | ✅ P0·T12/T26/T33 | P2（OS 级沙箱兜底） | 沙箱分级 + 审批 | sandbox + approval + rules 固化 | 独立 policy 引擎：三态+保护元数据+bash 分级+单向性 | 精细 XEYO 最高，工程化 Codex 最稳 | 纵深防御：补强制隔离（P2） | 策略层之上无 OS 级强制 |
| **事件流/协议** | 🔶 | **P1·T29** | GUI 直连内部状态 | CLI 文本流为主 | OpenAI 兼容 + xeyo 扩展帧（9 种帧型） | 协议设计 XEYO 最完整 | 反向输出 | 只有 GUI 一个消费者；断流 reattach 未做 |
| **子代理/多 Agent** | 🔶 | **P1·T14**（P2·workflow） | subagent/fork/workflow/ralph | subagents + Automations | 单写者队列 + Agent 工具 + peer presence | 编排 Codex 强，收敛 XEYO 讲究 | workflow 脚本化 | 缺通知归因/角色配置 |
| **持久化/恢复** | ✅ 领先 | — | checkpoint | thread 落盘 | JSONL+blob+轮转+sidecar+**rewind（turn 粒度）** | **恢复深度 XEYO 最强** | 反向输出 | Codex 跨入口同存储略优 |
| **记忆系统** | ✅ 领先 | —（P2·aging 回收） | compaction + AGENTS.md | MEMORY.md + rules | memdir 分层+治理三态+索引注入+写路径门禁 | **XEYO 最完整** | 反向输出 | aging 关闭后过期回收未启用 |
| **长任务/Goal** | ❌ | **P1·T9** | goal 状态机最完整 | thread_goals + Automations | 无 | DSH 最完整 | 抄 DSH | 断线丢上下文 |
| **扩展生态** | ❌ | **P1·T11** | 技能目录 | **最富**：MCP+rules+hooks+市场 | plugin.json 统一发现+优先级+防同名覆盖，默认关闭 | Codex 断层领先 | MCP+rules | 设计完未通电 |
| **配置系统** | 🔶 | **P1·T16** | env + 会话级 | config + 项目 rules | 三文件分职责+env；profile 未做 | 分文件职责清晰 | 三级合并语义 | 无 feature flag 注册表——「半成品开关」根因 |
| **可观测性** | 🔶 | **P1·T13** | 审计+job 日志 | trace/telemetry 较全 | 审计 JSONL+ActivityLog+rewind 证据链 | 有深度缺广度 | correlation id | 人工拼时间线 |
| **测试/CI** | ❌ | **P1·T35** | 内建自测 | CI 门禁最全 | 285 pytest 手工+tsc，无 CI | Codex 领先 | gen 漂移门禁 | T12/T26 无 CI 保护 |
| **交付/分发** | ❌ | **P1·T30/T32** | 本地起服 | 安装器/自动更新 | bat+Tauri 手工打包 | Codex 领先 | 自动更新+端口健康 | 升级靠重拉仓库 |

> **表二·证据等级**：✍️ 已证实——Codex 总架构多入口共享 thread（`state/src/model/thread_metadata.rs`、`app-server-protocol/v2.rs`）、自动化（`tool_search.rs:366`）、扩展最富 MCP/rules/hooks/市场（`handlers/mcp.rs:695`、`request_plugin_install.rs`、`skills`）、记忆 MEMORY.md 自动（`memories/write/src/workspace.rs:58`、`README.md:136`）、工具经 MCP `filesystem` 提供（`mcp.rs:695`）。⚠️ 未钉死：DSH「GUI 直连内部状态」「checkpoint-policy 双时机」「审计+read API」「env+会话级配置」（多为 UI/分发面，bundle 内不可见，标 ⛔）；Codex「trace/telemetry」「correlation id」「SDK 即契约」「installers」未取证。

---

## 三、企业级项目结构对比

| 企业级维度 | 状态 | 优先级 | DSH | Codex | XEYO | 谁更好 | XEYO 值得借鉴 | 差距在哪 |
|---|---|---|---|---|---|---|---|---|
| **仓库形态** | ✅ 保持 | —（P2·workspace 统一编排） | npm 单包 + 内部 monorepo | 多仓多制品 + 安装器 | 三语言 monorepo + docs 编号文档 | 边界清晰度 XEYO 最好 | 保持三入口分层 | 跨包 codegen 靠人记得 |
| **模块分层** | ✅ 保持 | —（P2·import 边界 lint） | 内核/UI 分离 | 内核/CLI/SDK/云端四层 | engine/tools/permissions/session/server/… 极细分 | **XEYO 分层最细** | 反向输出 | 无显式依赖规则，会腐烂 |
| **API 契约** | 🔶 | P2（帧 schema 单源+契约测试） | 内部直连无契约 | SDK 即契约 | OpenAI 兼容+xeyo 帧+REST+slashManifest codegen | 契约意识有雏形 | Codex 契约测试进 T35 | 扩展帧无 schema 单源，GUI/后端各写一份 |
| **配置管理** | 🔶 | **P1·T16** | env+会话级 | 分层 config+rules | 三文件分职责+env | 职责清晰 | 三级合并语义 | 无 schema 校验、无 feature flag 注册表 |
| **测试体系** | 🔶 | **P1·T35** | 内建自测 | 单元/集成/契约/coverage | 285 pytest+集成+vitest+tsc，conftest 隔离 | Codex 断层领先 | 金字塔分家/坏测试 skip 机制化 | 无 CI；两坏测试靠口头约定 |
| **CI/CD** | ❌ | **P1·T35** | npm 流水线 | 最全 | **无** | Codex 领先 | 最小三 job 起步 | 回归保护为零 |
| **可观测性** | 🔶 | **P1·T13** | 审计+job 日志 | trace 云端聚合 | 审计 JSONL（append-only+锁+redact） | 有深度缺广度 | correlation id+按天轮转 | 审计单文件无限增长 |
| **安全合规** | ✅ P0·T12/T26/T33 | P1（数据静态加密）/ P2（OS 沙箱） | 沙箱+审批审计 | SSO/RBAC/合规全套 | 策略引擎+硬 DENY+bash 分级+审计脱敏+围栏+token 门禁 | 精细 XEYO 最高 | 纵深防御 | transcript/spill 明文含源码——企业第一颗雷 |
| **部署形态** | 🔶 | **P1·T29/T30/T32** | 本地单用户 | 本地+云端+自动更新 | 单机 bat+单 worker 硬约束 | 单机正确性已锁（T39） | 版本化升级通道 | 无安装器/无更新/无多用户 |
| **文档体系** | ✅ 留痕强 | P2（使用者文档） | AGENTS.md | 官方文档站+SDK docs | 编号设计文档+红线+融合计划 v1–v4 演进留痕 | **演进留痕 XEYO 独有** | 反向输出 | 无快速开始/API 参考/排障手册 |
| **版本与发布** | ❌ | **P1**（semver+CHANGELOG，半天级） | semver npm | semver+changelog+自动更新 | 无版本号、大批量未提交 | Codex 领先 | 引擎版本进 port 文件（T29）顺势建立 | 无法回滚、无法二分 |
| **依赖与供应链** | 🔶 | P2（venv 锁定/插件沙箱随 T11） | npm lockfile+签名 | lockfile+市场审核 | 基础管理+插件优先级/防同名覆盖设计 | 插件信任模型有意识 | lockfile 全覆盖+审计 | 全局 py 环境无锁定文档化；插件无沙箱 |
| **错误处理规范** | ✅ P0·T34 | P3（错误 schema 统一） | friendly error | 分层错误 | common/errors.py 集中+全路径接入+GUI 边界 | **集中度 XEYO 最好** | 反向输出 | 黑名单正则会漏；API/audit 格式未统一 |
| **团队协作假设** | ❌ | P2（贡献指南） | 单主体 | 团队/企业级 | 单开发者+AI；AGENTS.md 唯一契约 | Codex 为多人设计 | AGENTS.md 升级为贡献指南 | 无 CODEOWNERS/分支/PR 流程 |

> **表三·证据等级**：✍️ 已证实——Codex 多仓多制品+插件市场审核（`request_plugin_install.rs`、`list_available_plugins_to_install.rs`、`has_skills`）、分层 config（`core/src/config/config_loader_tests.rs:2845`）与项目 rules/记忆（`memories/`、`agents_md.rs`）。⚠️ 未钉死：DSH「npm 单包+内部 monorepo」「env+会话级配置」「审计+job 日志」「内建自测」「friendly error」「semver npm」——多数为分发/build 面（bundle 内不可见），标 ⛔；Codex「SSO/RBAC/合规全套」「trace 云端聚合」「installers/自动更新」「lockfile+市场审核」未取证。

---

## 四、设计深水区对比

| 设计维度 | 状态 | 优先级 | DSH | Codex | XEYO | 谁更好 | XEYO 值得借鉴 | 差距在哪 |
|---|---|---|---|---|---|---|---|---|
| **提示词分层架构** | ✅ 领先 | —（P2·T_now 注册表） | system+T_now（借鉴来源） | rules/MEMORY.md 分层 | 三层仓（system 左段→Skill→T_now，三条判定标准） | **XEYO 判定标准最明确** | 已互抄完 | 候选清单只在文档里，未注册表化 |
| **状态机显式性** | 🔶 | **P1·T9 顺带** | goal 状态机显式（revision 乐观锁） | thread 隐式 | turn 内 TaskStateEvent，turn/会话级隐式布尔 | DSH 最显式 | turn 生命周期显式化 | 非法迁移靠防御代码非类型系统 |
| **中断传播设计** | ✅ P0·T2 | P2（子 agent 精细中断） | interrupt 精确到 agent/turn | Esc 全链 | AbortController+LinkedAbort+取消归一（三态区分） | **XEYO 语义最细** | 已抄齐 | 「只停当前 turn、保留队列」是 DSH 独有 |
| **决策点经济学** | 🔶 | **P1·T10**（P2·频次度量） | 审批+计划模式 | approval+auto-approve+记忆式授权 | 三态+TTL 分级+peer 三选+计划确认+rewind 确认 | XEYO 最丰富、**疲劳管理最弱** | grant store=T10；批量审批 | 「一天点多少次允许」无数字 |
| **旁路请求治理** | ✅ 领先 | —（P2·统一配额闸） | 子代理结构化报告 | 旁路摘要 | purpose 标签+关 thinking+审计前置+开关不继承+静默降级 | **XEYO 治理最系统** | 反向输出 | 标题+压缩+子代理可同时打 API，无闸 |
| **模块通信模式** | ✅ 保持 | —（P2·contextvar 注册表） | 工具调用+消息 | 事件+hooks | contextvar 请求态（4 个）+同步调用 | 小库最轻 vs hooks 可扩展 | hooks 挂点做 P2 | 隐式全局态接近临界点 |
| **单一事实源与漂移防御** | 🔶 | P2（帧类型 schema 单源） | — | — | slashManifest codegen+ENABLED 自检拒启+meta 漂移断言 | **XEYO 领先** | 反向输出 | codegen 只覆盖 slash；msgtypes/GUI 双写（T3 实操三处同步） |
| **预算即一等公民** | ✅ 领先 | —（P2·预算配置文件+观测） | T_NOW_EXTRA_BUDGET | context 窗口管理 | 全栈预算网（turn/tool_call/输出/spill/旁白/T_now） | **XEYO 最密** | 反向输出 | 数值散落，触发分布无数据 |
| **失败哲学矩阵** | 🔶 | P2（写进 AGENTS.md，零代码） | 审批 fail-closed | sandbox fail-closed | 逐子系统显式（hydrate 合成/flush 跳过/journal 告警） | **唯一逐子系统显式化的** | 矩阵文档化 | 语义散在代码注释里 |
| **会话数据模型演进** | ✅ 保持 | —（P2·schema version 字段） | checkpoint 隐式 | 云端 schema 演进 | 默认值加字段+sidecar 版本+.old 轮转+blob 外置 | 本地演进最完整 | 反向输出 | 无显式 schema version，跨大版本无迁移器 |
| **多会话互斥** | ✅ 领先 | —（P3·统一 lease 语义） | 单会话模型 | 云端隔离 | peer presence+busy 表+ProcessWorkspaceLock+三选 ASK+热文件冲突 | **单机多会话 XEYO 领先**（原创区） | 反向输出 | 内存表跨进程失效是已知取舍 |
| **编码与本地化工程** | ✅ 领先 | —（P3·i18n） | POSIX 优先 | POSIX 优先 | UTF-8 字节安全截断+normcase+GBK 兼容 | **Windows/CJK 独有正确性** | 反向输出 | 文案硬编码中文，出海硬伤 |
| **测试替身设计** | ✅ 领先 | —（P2·chaos fake 并入 T35） | 内部 | SDK mock | FakeModelClient 规则引擎+fake builder+conftest 全隔离 | **产品级测试替身** | 反向输出 | fake 只覆盖快乐路径 |
| **Agent 身份与角色体系** | 🔶 | **P1·T14** | 继承/隔离两种 | subagents+角色 | SUBAGENT_APPEND+worker bash 沙箱（只读白名单永不 ASK） | 权限继承 XEYO 最严 | 反向输出 | 角色不可配置、通知不可归因 |

> **表四·证据等级**：✍️ 已证实——Codex 状态机显式性、多会话云端隔离（`state/`、`app-server`）、工具编排（`tools/orchestrator.rs`）、execpolicy fail-closed（`decision.rs:9-16` 注释 `approval_policy="never"`）、subagents/roles（`tools/handlers/multi_agents*.rs`）、记忆/上下文（`memories/`、`context/`、`compact.rs`）。⚠️ 未钉死：DSH「goal 状态机 revision 乐观锁」（已验证 revision=CAS ✅，见 §9.2）、「审批 fail-closed」「checkpoint 隐式」「POSIX 优先」「内部测试替身」——部分为行为面；「诊断日志独立通道」「read API」在 bundle 内不可见，标 ⛔。Codex「云端 schema 演进」「SDK mock」「内部」未取证。

---

## 五、待对比维度清单（下一轮立项用）

| 维度 | 状态 | 优先级 | 具体比什么 | 为什么重要（预判差距方向） |
|---|---|---|---|---|
| **① 弱模型适配层** | ❌ 未比 | **P2**（最小成本先做） | 同任务集小/大模型跑：xml 兜底、forced wrap-up、旁白门控、repeat guard、脱轨恢复 | **XEYO 最可能的反超点**：唯一系统性为弱模型设防，但从未量化证明 |
| **② 评测体系（Evals）** | ❌ 未比 | **P2**（P2 立项候选） | 任务基准集、回归评测、模型升级 A/B、失败率 | 三者全没有；fake 后端是现成底座 |
| **③ 对抗性输入（prompt injection）** | ❌ 未比 | **P2**（企业安全必答题） | WebFetch/MCP/工具输出藏指令的隔离手段 | 三者都弱；XEYO 归属声明是部分防御 |
| **④ 成本计量与配额** | ❌ 未比 | **P2**（与 T10 同层） | usage 归因聚合、金额硬顶、超限降级 | 三者都只有 turn 级预算 |
| **⑤ 数据生命周期** | ❌ 未比 | **P1~P2**（评估是否插队 P1） | 保留/GC/删除权、静态加密、单文件无限增长 | 合规一票否决项；spill 7 天是唯一 retention |
| **⑥ 多 Provider 抽象** | ❌ 未比 | P2 | 换模型改动面、流式协议吸收层、usage 口径 | XEYO 四后端好底子，比接口隔离度 |
| **⑦ 性能与规模上限** | ❌ 未比 | P2 | 千轮加载、cache 命中率、首 token 延迟 | 有增量 cache 但零基准数字 |
| **⑧ 混沌/故障注入** | ❌ 未比 | **P2**（并入 T35 CI） | kill -9、磁盘满、端口占用、闪断的恢复断言 | T4/T39 场景未沉淀成套件 |
| **⑨ 三入口行为一致性** | ❌ 未比 | **P2**（T29/T31 顺手对表） | 中断/审批/Esc/rewind/标题跨 GUI/TUI/API | 协议一致但交互语义各自实现 |
| **⑩ 审计不可抵赖性** | ❌ 未比 | P3 | hash 链/签名/SIEM 对接 | 离「可取证」只差一行 hash |
| **⑪ 插件/技能开发者体验** | ❌ 未比 | P3（T11 之后） | skill 从零到生效几步、脚手架/校验/调试 | 生态冷启动卡在 DX 不在运行时 |
| **⑫ 离线与本地自治** | ❌ 未比 | P3（写进文档即得分） | 断网可用性、本地模型全链路、围栏降级 | XEYO local backend+围栏意识最好 |

---

## 六、总判断与路线图影响

### 三层结论

1. **内核层（循环/上下文/记忆/恢复/权限判定/多会话互斥）**：XEYO 领先或独有——KV 前缀稳定投影、rewind 三段式、记忆治理三态、peer presence、全栈预算网、单一事实源三件套。这部分是优势，P1 改造时**禁止被"重构"破坏**。
2. **执行外壳（生态/编排/长任务/CI/可观测）**：差距真实且集中在「有骨架未通电」。抄的方向明确：**T9 goal 抄 DSH、T11 MCP + T35 CI 门禁抄 Codex、T10 grant store 抄 Codex 记忆式授权**。
3. **形态差异是定位差异**：DSH=自举开发 harness；Codex=产品化全家桶；XEYO=**内核精致、外壳待装**的单机 agent 工程。P1 的本质是补外壳短板，不是动内核。

### 设计层判断（第四节）

- **该制度化的三件事**（零代码或接近零代码）：T_now 块注册表、失败哲学矩阵写进 AGENTS.md、contextvar 注册表。
- **该量化的两件事**：决策点频次（用户一天点多少次允许）、预算触发分布（哪层预算最常截断）——各加一条审计事件即可拿到数据。
- **该警惕的一件事**：codegen/单一事实源只覆盖了 slash 一处，msgtypes 事件与 GUI 类型双写已经在 T3 实操中造成三处同步修改——若不扩 schema 单源，每加一个事件帧都要人肉三写。

### 对 P1 排序的影响建议

1. **T9（goal）提优先级**：它是「断线可续」的唯一解，且设计可直接抄 DSH（blocked 语义 + 轮次帽），收益/成本比最高。
2. **T35（CI）拆出一个最小前置**：先上「pytest + tsc + codegen 漂移」三 job（半天工作量），其余 T35 内容后置——P0 的 285 项资产不能继续裸奔。
3. **⑤ 数据生命周期**评估是否插队 P1：transcript 明文含源码 + 审计无限增长，若目标用户含企业，这是比 T30 端口健康更靠前的合规项。
4. **弱模型评测（待比清单①）**用最小成本先做：拿现有 fake 后端 + 20 个任务跑一次小模型基线——结果无论好坏都改变叙事（好→产品卖点；差→补适配层的任务清单）。
5. **版本纪律**（表三「版本与发布」）：当天事当天提交、按任务拆 commit——这是所有对比项里成本最低、风险消除最大的一件，可立即执行。

---

## 七、逐工具对比（Read / Glob / Grep / Edit / Bash / …）

> XEYO 工具清单已核实 `tools/catalog.py` ENABLED_TOOL_ENTRIES（21 个）：getTime、Glob、Grep、Read、Write、Edit、Bash、TodoWrite、Screenshot、SendToWeChat、Memory、AskUserQuestion、JournalQuery、Skill、Agent、Diagnostics、Git、NotebookEdit、WebFetch、WebSearch、XeyoUI。

| 工具 | 状态 | 优先级 | DSH | Codex | XEYO | 谁更好 | XEYO 值得借鉴 | 差距在哪 |
|---|---|---|---|---|---|---|---|---|
| **清单与接入治理** | ✅ 领先 | — | 固定内置+skill 渐进加载 | 内置+MCP+rules/hooks 双门 | 21 工具经唯一入口 `ToolRegistry.run`：策略→审计→spill→RW 锁→repeat guard；meta 漂移拒启 | **门禁密度 XEYO 第一，生态广度 Codex 第一** | 反向输出：统一 registry 门禁 | 无 MCP 运行时，第三方工具进不来（T11） |
| **Read** | ✅ 等价偏强（本次核实修正） | —（P3·API 级 token 计数） | read：行号+offset/limit；read_image 校验+降采样进上下文 | read_file：范围+分页；图像可进上下文 | ReadTool：行号+分段+ReadFileState 状态机+**25k token 预算**（chars/4 估）+0.25MiB 大小门+**符号感知预算读取**（callee/caller 签名预算封顶）+**vision 读图**（8MiB 磁盘帽/2048px 送模帽/1.5M 编码帽） | **预算与符号感知 XEYO 最强** | 反向输出：token 预算+符号感知读取两家都没有 | token 计数是粗估；符号索引构建成本待测 |
| **Glob** | ✅ 等价 | —（P3·gitignore 联动确认） | glob：只返回文件、隐藏/ignored 含、modtime 排序、100 上限落盘 | glob：常见语义 | GlobTool（526 行）：匹配+排序+上限 | 三家等价 | 反向输出：「大结果落盘报位置」 | 已联动 `.gitignore/.ignore` + 另挂 `.agentignore`（`glob_tool.py:4-5`）；但 XEYO 上限 120 截断、不落盘（与 DSH 100 上限落盘不同） |
| **Grep** | ✅ 偏强（核实修正） | —（P3·negation/上下文行） | ripgrep 语法、250 上限落盘、**无分页** | ripgrep+结构化输出 | GrepTool：ripgrep+**head_limit/offset 分页**+分页提示语+--max-columns 500+符号扫描帽 200k | **XEYO 分页迭代搜索更强** | 反向输出：截断清单可发现性 | 无负向过滤（`-A/-B/-C/context` 已完整暴露，`grep_tool.py:409-423,852-855`） |
| **Edit** | 🔶 | **P2**（patch 式多 hunk——最该抄的一笔） | edit：字面 old→new、先读后改强制、沙箱升级重试 | apply_patch：**unified diff 多 hunk 一次提交**，支持移动/删除（`apply-patch/src/lib.rs:897-949,1073-74`)——但**整补丁非原子**（逐 hunk 落盘，写失败可留残，`lib.rs:488-491`） | EditTool：字面替换+ReadFileState 校验+journal 证据尾行（T28） | **Codex patch 模式最强**（多 hunk 一次提交；原子性需 XEYO 自建） | ①patch 式多 hunk ②编辑摘要（+x/-y 行） | ❌ 多 hunk 要多次调用；无 diff 预览回显 |
| **Write** | ✅ P0·T12/T28 | —（P3·写前 diff 预览） | write：整文件替换、已存在须先读 | apply_patch Add File | WriteTool：整替换+journal 证据+notice+保护元数据硬 DENY | 持平，XEYO 门禁最厚 | 反向输出：写入即留证据 | 单代理 Write 非原子（`fileio/text.py:75-76` 直接 open/w）；仅子代理 WriteStore 原子（`write_store.py:351-370`） |
| **Bash / Shell** | ✅ 领先（输出经济也领先——核实修正） | —（P3·跨平台抽象，隐形债务） | pwsh：沙箱三态+后台 job+超时 | shell：跨平台+sandbox+approval | BashTool：六层纵深（黑名单→密钥→保护→peer→白名单→写证明）+30k **中段截断**+全量落盘+**cmd_compact 命令族语义压缩**（压噪声保信号，两家都没有）+presence 追踪+后台日志 7 天 TTL | **安全纵深与输出经济双第一** | 反向输出：写目标证明+语义压缩 | 绑死 Windows PowerShell 语义；后台无流式部分输出 |
| **后台任务** | ❌ | **P2**（统一 job 抽象） | job 系统：`run_in_background` + `job_output` 流式 + `job_kill` + 完成通知（`dsh-tool-jobs/index.d.ts:2-7,19,22-27`） | 后台 shell+automations | Bash 后台模式+子代理后台；无统一 job 抽象 | DSH 最完整 | 「后台 job 是一等工具」 | ❌ 长命令只能等通知，模型无法主动轮询/终止 |
| **WebFetch / WebSearch** | ✅ 持平 | —（P2·browser；注入隔离见待比③） | web_search（1–4 查询合并） | web_search + **browser 浏览器运行时回退**（无独立 browser 模型工具；仅 `browser_use/computer_use` 配置需求，`config/src/config_requirements.rs:2454`） | WebFetchTool+WebSearchTool，输出走 spill/预算 | WebSearch 持平；**Codex 无独立 browser 交互工具**（browser 独家不成立） | browser 做 P2（自研，非抄 Codex） | 无 browser 交互；注入隔离三家都弱 |
| **NotebookEdit** | ✅ 独有 | — | — | — | NotebookEditTool（ipynb 单元级） | XEYO 独有 | 反向输出 | — |
| **Todo / 计划** | ✅ 等价 | —（P3·计划执行对照） | todo_write+exit_plan_mode 闭环最显式 | update_plan+plan mode | TodoWriteTool+计划确认（T_now Approved Plan） | 三家同构 | 已抄齐 | 批准后无执行对照检查 |
| **AskUserQuestion** | ✅ 等价 | —（P3·答案持久化） | 结构化问题+选项+多选 | 交互提示+审批 UI | 结构化选项+**interactive TTL=∞**（T3） | 三家同构 | 已抄齐 | 关 GUI 答案即丢 |
| **Memory** | ✅ 领先 | —（P2·aging 回收/语义检索） | compaction+AGENTS.md（无写工具） | MEMORY.md 自动记忆 | memdir 分层写+写路径门禁+治理三态+JournalQuery 查询端 | **XEYO 最完整**（写/查/治） | 反向输出 | 关键字匹配非语义检索 |
| **Git** | ✅ 独有 | —（P2·高危操作拦截覆盖面） | 无专用（走 shell） | 无专用（走 shell） | **GitTool 只读专用**：写一律 `WRITE_REJECT`（`git_tool.py:74-75`）；git 写走 Bash 六层纵深（保护/写证明/拦截） | XEYO 独有且必要 | 反向输出：写冲突检测应归 WriteStore 而非 GitTool | rebase/cherry-pick 作为写被直接拒绝（非"拦截询问"）；高危拦截由 Bash 层承担 |
| **图像** | ✅ 等价（本次核实修正） | — | read_image：校验+降采样+进上下文 | 独立 `view_image` 工具（`core/src/tools/handlers/view_image.rs:73`） | **Read 的 vision 路径**（8MiB 磁盘帽/2048px 送模帽/1.5M 编码帽）+ ScreenshotTool 截图取证 | 持平（双帽设计更严） | 反向输出 | GUI 多模态展示链路已确认（上传 + markdown `data:image` + ImageReaderDialog 预览） |
| **Skill** | 🔶 | P2（作者工具链，随 T11 之后） | skill：渐进加载+查重+强制 load | create-skill 全套作者工具+市场 | SkillTool：SKILL.md 按需加载+同名防覆盖 | Codex 生态最强 | 作者工具链（脚手架+校验） | 有运行时无作者工具、无市场 |
| **Agent / 子代理** | 🔶 | **P1·T14**（P2·workflow） | subagent/fork/workflow/ralph | subagents+Automations | AgentTool 派发+WriteStore 单写者收敛 | 编排 Codex 强，收敛 XEYO 讲究 | workflow 脚本化编排 | 缺通知归因/角色文件；稳定性存疑 |
| **XEYO 独有四件** | ✅ 保持 | — | — | — | ①XeyoUI（agent 操控 GUI）②SendToWeChat（微信触达）③JournalQuery（rewind 证据查询）④Diagnostics+getTime | **XEYO 定位独有** | 反向输出：个人 agent vs 编程 agent 的分野 | 测试深度与文档化不足 |
| **横切：输出治理** | ✅ P0·T1 | —（P3·registry 层通用语义折叠） | spill+retention | 模型可见/诊断分离 | spill+per-tool output_budget+bash 30k 中段截断+**cmd_compact 语义压缩**+grep 分页 | **XEYO 粒度最细且含语义压缩** | 反向输出 | 语义压缩目前仅 bash 命令族；其他工具无通用折叠 |
| **横切：证据与审计** | ✅ P0 | **P1·T13**（correlation id） | 审批审计 | trace | tool.started/finished 成对+spill 事件+journal 尾行+permission 成对+title.enhance | **XEYO 覆盖面最全** | 反向输出 | 无 correlation id 串联 |

### 逐工具层结论

1. **基础设施五件套（Read/Glob/Grep/Edit/Write）三家功能等价**，差异在工程细节：XEYO 的 read-state 跟踪与证据尾行是独有的严谨；Codex 的 apply_patch 多 hunk 一次提交是 XEYO 最该抄的一笔（大文件重构从 N 次往返变 1 次）——**但 Codex 整补丁并不可靠原子**（逐 hunk 落盘可留残），XEYO 抄时须自建「全补丁预校验 + 失败整体回滚」。
2. **Bash 是三家差距最大的单工具**：XEYO 的安全纵深（黑名单→密钥→保护→peer→白名单→写证明）远超两者的 sandbox 模式——但代价是绑死 Windows PowerShell 语义，跨平台是隐形债务。
3. **XEYO 真实缺位（本次核实修正后）**：统一后台 job 抽象（模型可轮询/终止）是唯一硬缺位；此前记的「无读图」「缺语义折叠」经核实**不成立**——Read 自带 vision 路径（8MiB/2048px 双帽）、bash 自带 cmd_compact 命令族语义压缩。新增待办：Read 的 API 级 token 计数（替换 chars/4 粗估）。
4. **XEYO 四个独有工具（XeyoUI/SendToWeChat/JournalQuery/Diagnostics）是定位宣言**：这不是「另一个 coding agent」，是桌面管家——对比中唯一不该向另外两家看齐的部分。

---

## 八、工具缺口清单（DSH/Codex 有、XEYO 无）——添加建议

> 按「复用现有基建的程度」排优先级：基建已存在的只差工具面，成本最低收益最快。

| 缺口工具 | 来源 | XEYO 现状 | 建议优先级 | 添加思路（尽量复用现有基建） |
|---|---|---|---|---|
| **JobList / JobOutput / JobKill（后台 job 一等工具）** | DSH job 系统 | `bash_tool/background.py` 已有全套基建（后台执行、日志落盘、7 天 TTL 清理），但**模型无法轮询/终止**，只能被动等通知 | **P2 首位**（可搭 P1 顺风车） | 三个薄工具封装 background.py：列表（状态+存活）、按 job_id 读输出（走 spill/预算）、终止；审计 job 事件 |
| **apply_patch 多 hunk 补丁编辑** | Codex | Edit 逐次字面替换，大改文件 N 次往返 | **P2**（编辑效率最大单笔） | file_edit_tool 加 patch 模式（unified diff 解析器），保留 ReadFileState 校验+journal 证据尾行；**失败整体回滚须自建**（Codex 自身整补丁非原子，逐 hunk 落盘可留残，`apply-patch/src/lib.rs:488-491`） |
| **goal 状态机工具族** | DSH | 无 | **P1·T9**（已在计划） | 抄 DSH：create/edit/pause/resume/blocked；blocked 需连续 3 轮同因证据；轮次帽防失控；仅人工可改目标 |
| **MCP stdio client** | Codex | 扩展层骨架有 mcp_servers 声明位 | **P1·T11**（已在计划） | plugin.json mcp_servers→stdio client→动态注册进 ToolRegistry，**默认 outbound_ask**（红线：必经三态门禁） |
| **automations 定时/触发任务** | Codex | 无 | **P2**（与桌面管家定位最契合） | cron/事件触发的受限会话：定时微信摘要、目录巡检、日志清理——XeyoUI+SendToWeChat 是天然执行端 |
| **workflow 多 agent 编排** | DSH | AgentTool 单发派 | P2（T14 之后） | 声明式 phase/pipeline 脚本+并发帽；WriteStore 单写者收敛已就绪 |
| **exit_plan_mode 计划审批闭环** | DSH | 计划走 T_now 文本（Approved Plan 块已有） | P3 | 工具化「计划→显式批准→执行对照」（TodoWrite 联动勾稽） |
| **browser 可交互网页** | Codex（**源码仅 web_search 浏览器回退 + browser_use/computer_use 配置需求，无独立 browser 工具**） | WebFetchTool 静态抓取 | P3 | 会话态浏览器需**自研**；**prompt injection 隔离先行**（待比清单③） |
| **canvas 实时分析画布** | Codex（**源码无此实现**） | XeyoUI 已有 GUI 操控底子 | P3 | agent 生成临时 HTML/React 工件在 GUI 旁路打开——与 XeyoUI 天然契合的差异化亮点（Codex 全仓无 canvas 工具，仅 TUI ratatui `Canvas`/内联可视化 `<canvas>`；本项非 Codex 现成能力，需自研） |
| **hooks 事件脚本挂点** | Codex | 无（但审计事件 taxonomy 已备好挂点） | P3（rules 化 P2） | tool.started/finished 审计事件→外部脚本回调；strict 白名单+超时 |

**落地顺序建议**：JobQuery/JobKill（基建现成，一周内）→ apply_patch（编辑体验跃升）→ automations（差异化：只有 XEYO 的定位能用好它）→ 其余随 T9/T11/T14 顺带。**不建议添加**：ralph 式 fresh-agent 循环（与 T9 goal 语义重叠）、todo 变体（已等价）。

### 修正记录（本轮核实）

- ❌→✅ 「XEYO 无读图」**不成立**：`file_read_tool/vision_media.py` 支持 text+image 双模式（8MiB/2048px/1.5M 编码三帽）。
- ❌→✅ 「XEYO 缺语义折叠」**不成立**：`bash_tool/cmd_compact.py` 在 truncate 前做命令族识别、压噪声保信号——这是 DSH/Codex 都没有的层。
- ⬆ Read/Grep/Bash 三件工具的输出经济经核实为**三家最强**：Read（25k token 预算+符号感知读取+vision）、Grep（head_limit/offset 分页+分页提示）、Bash（中段截断+语义压缩+全量落盘）。

---

## 九、源码核实修正记录（本轮：对 DSH/Codex 列逐条源码取证 + XEYO 待确认落实）

> 本轮对第 1/2/7/8 节的 DSH、Codex 断言逐条做了源码级取证；XEYO 列的「待确认/待核实」项也已读本仓源码落实。
> **证据图例**：✅ 源码证实（附行号）｜⚠️ 部分证实（字符串/类型命中但逻辑不可见）｜❌ 证伪（源码与文档矛盾，附实际）｜⛔ 不可验证（grep 无命中/压缩包不可见，如实标，不脑补）。
> DSH 为 npm 压缩分发，只能查可按读的 `*.d.ts` 类型与 README（源码逻辑在 minified bundle 内，单 bundle 未整读——凡逻辑应在 bundle 内者一律降为 ⚠️ 或 ⛔）。

### 9.1 Codex 断言取证（`D:\lea\XenYon code\.tmp\codex-src\codex-rs\`）

| 文档断言（源行） | 判定 | 证据/修正 |
|---|---|---|
| apply_patch：unified diff **多 hunk 一次提交**（§一/§七 Edit 行 149） | ✅ | `apply-patch/src/lib.rs:897,943-949`（`*** Add/Delete/Update File`）、`:1162` 注释「a single `Update File` hunk with multiple change chunks」；`:274 append` 多 hunk 累加 |
| apply_patch 支持**移动/删除**（行 149） | ✅ | `apply-patch/src/lib.rs:897-949`（Add/Delete）、`:1073-1074`（`*** Move to`）、`:1123` 测试 |
| apply_patch 整体**原子**（§一 Edit「最该抄的一笔」=一次往返非N次；§八 182「失败整体回滚保证原子性」系 XEYO 侧建议） | ❌ | Codex 自身**非整补丁原子**：`apply-patch/src/lib.rs:488-491` 注释「A failed write can still have modified the target before surfacing an error… delta.exact = false」（逐 hunk 落盘，写失败可留部分修改）。→ 建议抄时需自加「先校验全部 hunk、再落盘 / 整体回滚」 |
| execpolicy **规则引擎**（§一/§四） | ✅ | `execpolicy/src/rule.rs:64-82`（`PrefixRuleMatch`/`HeuristicsRuleMatch`）、`decision.rs:9-16`（`Decision = Allow/Prompt/Forbidden`；`Prompt`=请求批准，`approval_policy="never"` 时径直拒绝, comment line 12） |
| shell 沙箱**分级**（§一百 51） | ✅ | `core/src/config/mod.rs:491,503`、`config_loader_tests.rs:2463`（`SandboxPolicy::ReadOnly/WorkspaceWrite/DangerFullAccess`） |
| 工具全集：核心原生工具（§7 逐工具） | ✅ | 核心工具为 **`exec_command`·`apply_patch`·`shell`·`update_plan`·`plan`·`view_image`·`sleep`·`web_search`·`tool_search`·`request_user_input`·`current_time`·`multi_agents`·`automation_update`**（见 `core/src/tools/handlers/*`）；`read_file/glob/grep/write_file` **并非核心原生工具**，由内置 **MCP `filesystem` server** 提供（`core/src/tools/handlers/mcp.rs:695` `tool_info("filesystem","filesystem","read_file")`） |
| **browser 独家可交互网页**（§7 WebFetch 行 153；§8 188） | ⚠️→降级 | 无核心 `browser` 模型工具；仅存在 `browser_use`/`computer_use` **配置需求**（`config/src/config_requirements.rs:2454,613`）与 web_search 的**浏览器运行时回退**（`core/src/tools/spec_plan_tests.rs:3113`）。「Codex 有独立 browser 交互工具」**未能证实** |
| **canvas 实时分析画布**（§8 189） | ❌ | 全仓无 `canvas` 工具；仅 TUI 内 ratatui `Canvas` 渲染与内联可视化 HTML `<canvas>`（`tui/src/inline_visualization_tests.rs:211`）。「Codex 有 canvas 工具」不成立 |
| automations 定时/触发（§7/§8 185、边 22） | ✅（⚠️feature-gated） | `core/src/tools/handlers/tool_search.rs:366`「Create, update, view, or delete recurring automations.」（`automation_update` 动态工具，`codex_app` 命名空间）；`config/config_tests.rs:11206` `Feature::InAppLocalAutomation` |
| 扩展生态最富（MCP+rules+hooks+automations，边 22/160/185） | ✅ | `mcp.rs`、`hook_*.rs`、`automation_update` + **插件市场**（`request_plugin_install.rs`/`list_available_plugins_to_install.rs`、`has_skills`）+ skills 经插件（`events.rs:114`）。「断层领先」成立 |
| plan mode / update_plan（§7 Todo 行 155） | ✅ | `core/src/tools/handlers/plan_spec.rs:30,43`、`plan.rs:50`（`update_plan` 工具）、`tool_search` 下 `plan` |
| 图像输入支持（§7 图像行 159） | ⚠️ | 核心有 **`view_image`** 工具（与 Read 分离，`view_image.rs:73`）；「图像可进上下文」依赖 `view_image`/`image_preparation.rs` 而非 read_file 返回 base64。文档表述宜改为「Codex 用独立 `view_image` 工具」 |

### 9.2 DSH 断言取证（`E:\nodejs\node_modules\@deepseek-ai\dsh\node_modules\@deepseek-ai\`）

| 文档断言（源行） | 判定 | 证据/修正 |
|---|---|---|
| 审批**四值结果**（§1 审批行 17） | ✅ | `dsh-user-approval/lib/types/types.d.ts:23`：`ApprovalOutcome = 'allowed-once' \| 'rejected' \| 'cancelled' \| 'unavailable'`；`dsh-sandbox/.../escalation.d.ts:68` 同四值；`dsh-host-apiproxy/.../approvals.d.ts:10-11`（客户端仅报 allowed-once/rejected，cancelled/unavailable 属宿主侧） |
| 审批 policy（行 17） | ✅ | `dsh-user-approval/.../index.d.ts:81` `ApprovalPolicy = 'ask' \| 'never'` |
| Esc 恒=Cancel | ⚠️ | `cancelled` 结果值确认；「Esc 键恒=Cancel」为 UI 绑定，逻辑在 minified bundle/web-frontend（`dsh-client-ui-*`），仅类型面见 `ask.cancelled`（locale）、`ApprovalPanel`——密钥语义**未证实** |
| job 系统：run_in_background+job_output 流式+job_kill+完成通知（§7 后台任务行 152） | ✅ | `dsh-tool-jobs/lib/types/index.d.ts:2-7`「Model-facing `job_output`/`job_list`/`job_kill` tools over `ctx.jobs`」；`:22-27` wait/timeout；`:19,27` 完成通知 `completionDelivery: 'wakeup'\|'quiet'` |
| goal 状态机（blocked 需 3 轮证据+轮次帽；§1/§2/§4/§8 行 24、183） | ✅ | `dsh-goal/lib/types/types.d.ts:37` `GoalPhase='active'\|'paused'\|'blocked'\|'complete'`；`domain.d.ts:12` `GoalOperation='create'\|'edit'\|'pause'\|'resume'\|'complete'\|'block'\|'clear'`；`types.d.ts:19-20` `revision`（CAS 乐观锁）；`types.d.ts:53,61` 轮次帽 `roundsStarted`+`maxGoalRounds`；`dsh-tool-goal/.../authority.d.ts:17-42` 完成权 `'direct-human'\|'goal-round'`（仅人工/精确轮可完成） |
| **blocked 需连续 3 轮同因证据**（行 24） | ⚠️ | 状态机/block op/轮次帽/权威均已证实；**具体的「≥3 轮同因」min-round 阈值是 bundle 内策略常量，`dsh-goal` 的 `*.d.ts` 类型面不可见**——如实标 ⚠️，不宣称证实 |
| repeat-tool-reminder：只提醒、不拒执行、T_now 注入（§1 重复调用行 16） | ✅ | `dsh-repeat-tool-reminder/README.md:5`「advisory loop-breaker… never appears in the tool list, never vetoes or rewrites a call」；`:13` 默认 `thresholds:[3,5,8]`（与 XEYO 已吸收的 [3,5,8] 一致）；`README.md:35`/`index.js:181-187` 经 post-execute `additionalContexts`（`{kind:'plugin',plugin:'repeat-tool-reminder'}`）注入为 `user/message` |
| T_now 注入 / T_NOW_EXTRA_BUDGET（§1 记忆行 25；§4「借鉴来源」行 79） | ⚠️ | DSH 确实有**按请求/持久上下文注入**架构：`dsh-system-prompt/lib/index.js:142-144`（prompt section/context/variable 注册表）、`dsh-agent-instructions`/`dsh-tool-skill` → `<system-reminder>` + `enter` 决策、repeat/schedule 的 `user/message` 注入。但 **DSH 无语面「T_now」字面、无「T_NOW_EXTRA_BUDGET」常量**（后者系 XEYO 自有命名）。概念属实、命名自家 |
| subagent 会话树+fork/workflow/ralph+结构化报告（§7 Agent 行 161；§1 多 Agent 行 23） | ✅ | 包目录齐全：`dsh-tool-subagent`（+`-control`/`-report`）、`dsh-subagent-fork-in-process`（README:38 继承历史）、`dsh-tool-workflow`/`dsh-workflow`、`dsh-tool-ralph`；`dsh-subagent-report` 结构化报告 |
| 工具名全集（§7 清单行 145） | ✅ | 包目录证实工具族：`dsh-tool-fs`（read/write/edit/image/sandbox）、`fs-search`（glob/grep）、`pwsh`（+背景）、`pwsh-persistent`、`bash`、`todo`、`goal`、`jobs`、`subagent`、`ralph`、`workflow`、`skill`、`str-replace-editor`、`web`（web_search/fetch） |

### 9.3 XEYO「待确认/待核实」落实（`D:\lea\XenYon code\python\`）

| 文档断言（源行） | 判定 | 证据/修正 |
|---|---|---|
| Write **原子写方式待确认**（§7 行 150） | ⚠️→❌（非全原子） | **默认单 agent 直通 `write_text_file` 非原子**：`tools/fileio/text.py:75-76` `open(path,"w")` 直接写；**子 Agent 经 WriteStore 才原子**：`engine/write_store.py:351-370`（tmp+`os.replace`）。→「原子写」仅覆盖子代理写路径，单代理默认为非原子（应补 temp+rename） |
| Grep **-A/-B/-C 暴露度待确认**（§7 行 148） | ✅（比预期更强） | `tools/grep_tool/grep_tool.py:409-423` schema 已暴露 `-B`/`-A`/`-C`/`context`，`:852-855` 解析；`head_limit`/`offset` 分页（`:317-324`）；context=`-C`。（文档「暴露度待确认」→ 已完整暴露） |
| Git **rebase/cherry-pick 拦截覆盖面待查**（§7 行 158） | ❌（修正「peer 写冲突检测（三选 ASK）」） | `tools/git_tool/git_tool.py:74-75`：任何写 action（commit/push/add/reset/checkout/merge/rebase/pull，`:13-15`）都 `return WRITE_REJECT`——GitTool **完全只读**（`is_read_only=True` 行 28-30），**不执行写、故无 ASK 拦截面**。rebase/cherry-pick 非「被拦截」而是「被拒绝」。→ 文档称 GitTool 有「写冲突三选 ASK」不成立；git 写冲突检测应属 WriteTool/WriteStore 而非 GitTool |
| Glob **ignore 规则联动待确认**（§7 行 147） | ✅ | `tools/glob_tool/glob_tool.py:4-5`：ripgrep 默认尊重 `.gitignore/.ignore`，另挂 `.agentignore`（`--ignore-file`）；`:37` 引 `agentignore_args`。→ 已联动 gitignore + agentignore；且 `head_limit` 硬上限 120（`:42-46`），**不落盘**（与 DSH 100 上限「落盘报位置」不同） |
| GUI **多模态展示链路待验证**（§7 图像行 159） | ✅ | 链路存在：`gui/src/components/Composer.tsx:223-655`（图片上传/`mediaRef`→`uploadMedia`）、`MessageList.chat.test.tsx:101-116`（发送气泡渲染 `/v1/media/$digest`）、`XyStreamdown.tsx:283`（`data:image\/` markdown 渲染）、`MessageBubble.tsx:94`/`ImageReader.tsx`（大图预览）、`lib/api.ts:345`（`kind:'image'` 内容块）。→ 上传+模型 markdown 图片均能显示 |
| 后台任务**模型无法轮询/终止**（§7 行 152；§8 181） | ✅ | 文档 XEYO 侧的「无统一 job 抽象、模型无法 poll/kill」属实：`bash_tool/background.py` 有后台执行+落盘+TTL，但 catalog 无对模型的 job list/read/kill 工具（`tools/catalog.py` 21 入口无 job 工具）。与 9.2 DSH job 工具集对照成立 |

### 9.4 修正后对结论的实质影响

1. **「Codex patch 模式最强、最该抄」（§七 Edit & 前提 168、§八 182）——方向对但细节改**：多 hunk 一次提交、move/delete 属实；但**整体原子性 Codex 也未做到**（逐 hunk 落盘）。XEYO 抄时务必加「全补丁预校验+失败整体回滚」，否则写一半留下脏文件。
2. **「Codex 有 browser 交互、canvas 分析画布」两个"独有/可抄项"（§7 行 153、§8 188-189）被削弱**：browser 无独立模型工具（仅配置需求+web_search 浏览器回退）；canvas 全仓无实现。→ §8 的「browser」「canvas」两行应降为 P3 候选但**不是抄 Codex 现成能力**，需自研；「Codex 生态最富」仍成立但集中在 MCP/rules/hooks/market/automations，不含图形化 browser/canvas。
3. **「DSH goal 状态机是 P1 最高性价比单笔」（§1/§6 行 24、120、131）——成立，可放心抄**：phases/ops/revision(CAS)/轮次帽/完成权威(仅人工或精确轮) 全部源码证实；唯「≥3 轮同因」阈值 bundle 不可见，抄时按 XEYO 现有 [3,5,8] 习惯自定即可。
4. **「XEYO 原子写」缺口成立但仅一半**：Write 默认为**非原子**（直接 open/w），只有子代理 WriteStore 路径原子。若愿把单代理写也改为 temp+os.replace（write_store.py 已有现成 `_atomic_write`），一行成本即补齐——比 §8 180（apply_patch 原子性）更便宜。
5. **XEYO Git 工具的真实形态要改写**：GitTool 是**只读**（写一律 WRITE_REJECT），并非「写冲突三选 ASK」；git 写操作实际走 Bash（六层纵深），其高危拦截由 Bash 的写证明/保护层承担。→ §7 行 158「peer 写冲突检测」应改述为「GitTool 只读；git 写经 Bash 走六层纵深/拦截」。

> **本节承诺**：凡标 ⚠️ 或 ⛔ 的行，均为「类型/字符串命中但控制流不可见」或「grep 无命中」而如实降级，未用任何印象补全。DSH 全部结论限于可按读的 `.d.ts`/README 面；bundle 内控制流一律未整读、未推断。

---

## 十、多 Agent 记忆体系对照与综合设计（DSH × Codex × XEYO）

> 定位：把「子代理 」（§1/§6 T14）与「记忆」（§1/§2 L4）两件事合起来看——**子代理的价值有一半在「记忆怎么在 agent 之间共享/隔离/收敛」**。本对照把四套设计并排：用户自己在 `docs/设计/28-多Agent协同设计.md` 与 `docs/设计/10-完整记忆体系.md §5` 的多 agent 记忆设计、DSH 记忆面、Codex 记忆面、XEYO 当前实现；最后给「取其精华去其糟粕」的综合方案。每条带 `file:line` 证据（✅ 源码证实 / ⚠️ 类型/字符串命中 / ⛔ 不可见）。

### 10.1 四方记忆架构速览

| 维度 | **DSH**（指令派） | **Codex**（自动归一派） | **XEYO 当前实现**（治理派） | **用户设计**（§10/§5·目标态） |
|---|---|---|---|---|
| 长期事实记忆 | **无**（只有指令层） | **有**：`MEMORY.md`(注册表)+`memory_summary.md`(索引)+`skills/`+`rollout_summaries`(详情) | **有**：memdir `topics/*.md`+`MEMORY.md` 导航索引 | 同左，6 层（L1–L6） |
| 记忆写入口（模型） | ⚠️ 未见模型记忆写工具（指令层只读注入） | **有**：`add_ad_hoc_note`/`list`/`read`/`search`（`ext/memories/src/tools/mod.rs:28`，`tests.rs:111-144`） | **有**：Memory 工具（经 `write_policy` 门禁）+JournalQuery 读 | Memory 写 + `MemoryCandidate` 回传主会话确认 |
| 自动收敛 | **无**（靠 compaction 会话摘要） | **有**：后台 job `memory_stage1`/`memory_consolidate_global`（`state/runtime/memories.rs:19,45`） | **部分**：NightShift 离线重塑（`nightshift.py`）；缺"会话/任务结束自动升级" | NightShift + 任务结束自动升级候选 |
| 读/检索 | 指令 `<system-reminder>` 注入 + 技能目录 | `memory_search`/`memory_read`（`tools/search.rs`/`read.rs`）+ citation | `MEMORY.md` 索引注入（`runtime.py:472-508`）+ search.py + JournalQuery | 同左 + citation |
| 作用域 | 项目（`$DSH_HOME`→`cwd`，目录候选） | 项目级 `memory_root`（`memories/write/src/workspace.rs:58`）、per-role `memory_tool=false`（`core/src/agent/role_tests.rs:419`） | 三层：workspace `project` 记忆 + 用户级 `user`（`agent_scope.py`） | 同左 |
| 子代理记忆隔离 | 依赖角色/无 | 角色可关 memory 工具 | **`agent_scope.py`**：子代理 `can_write_memdir=False`/`can_write_session_md=False`/`share_kv_prefix=False` + 工具裁剪（`:91-99`） | 同左（设计即此） |
| 写门禁（防污染） | 无（只读） | 弱（靠模型） | **强**：`write_policy.refuse_reason`（`write_policy.py:32-59`）拒目录树/一次性计划 | 同左 |

### 10.2 按 XEYO 六层对照（谁强 / 谁有 / 谁缺）

| 层 | DSH | Codex | XEYO 当前 | 源（职责要点） |
|---|---|---|---|---|
| L1 指令 | **强**：AGENTS.md 增量 diff/digest、项目作用域、`<system-reminder>` durable、SHA-1 内容身份、无 watcher/触摸驱动、tombstone（`dsh-agent-instructions/README.md:9,45,53,72,110`） | 规则/记忆分离（`agents_md.rs`、roles） | L1 读 XEYO.md | 既有 L1 已足，可抄 DSH 的 **digest 增量 + 内容身份 + 触摸驱动** 精确更新 |
| L2 短期 | 会话内 | 会话内 | 主 JSONL 权威 + **子代理侧链 JSONL**（`agent_scope.py`、`subagent_memory.py`） | **XEYO 最需要护**：侧链隔离，禁止 append 主历史 |
| L3 工作 | — | — | `agent_id` 快照 + TodoStore `key=agent_id` | 同左 |
| L4 长期 | **弱（无）** | **强但治理弱**（自动归一） | **强且治理强**（memdir+门禁+索引原子化） | XEYO 门禁（`write_policy`、`index` 原子化 `memdir.py:222-224`、单写者 `journal.py`/`nightshift.py`）是独有的 | 
| L5 摘要 | compaction | rollout 摘要+`memory_summary.md` | 主 `session.md`+cursor；子代理只回传单条 | 可抄 Codex 三级（详情/索引） |
| L6 休眠 | — | — | NightShift（`nightshift.py` 单写者） | 子代理禁止投递；补"任务结束自动升级" |

### 10.3 关键差异：三家的"精"与"糟"

- **Codex 的精**：①**自动收敛**（后台 job 把会话沉淀进 `MEMORY.md`/`memory_summary.md`/`skills/`，`state/runtime/memories.rs:19,45`）；②**模型记忆工具**（`add_ad_hoc_note`/`search`/`read`，`tools/`）；③**三级 + citation 溯源**（`read_path.md:22-37`：`MEMORY.md`=可检索注册表、`memory_summary.md`=紧凑全局索引、`skills/rollout_summaries` =渐进披露详情；citation `path:lines|note`）。
- **Codex 的糟**：自动收敛**治理弱**（靠模型 + 摘要，缺 XEYO 的 `write_policy` 门禁与「仅主会话确认」）；**全局单一 `memory_root`** 跨任务可能互相污染（`memory_import.rs:20-31` 靠"project scope"缓解但无 per-agent 写门禁）；每轮再索引 `memory_summary` 有成本。
- **DSH 的精**：指令层 **增量 diff/digest + SHA-1 内容身份 + 无 watcher/触摸驱动 + tombstone**（`dsh-agent-instructions/README.md:45,53,110`）——精确、稳、省。
- **DSH 的糟**：**无长期事实记忆、无模型记忆写工具**——子代理发现的事实无法留档（指令层只读注入），跨任务知识积累缺位。
- **XEYO 的精（必须护住，别抄丢）**：六层隔离 + **单写者收敛 + `MemoryCandidate` 仅主会话确认门禁**（`agent_scope.py:33-37`、`subagent_memory.py:17-21`）+ KV 默认隔离（`share_kv_prefix=False`）+ 工具裁剪剔除子代理 Memory（`agent_scope.py:91-99`）+ 原子索引重写（`memdir.py:222-224`）。这是 DSH/Codex 都没有的**治理强度**。
- **用户设计的精髓（§10 §5.1-5.6 / §28 §2）**：三工人（主/任务子Agent/系统fork）+ 六层"谁共享谁隔离" + **主历史只加一条回传** + **写冲突单写者事务 store 无锁化（`§28 §2.5.2` per-file 单写者 + content-hash 版本校验）** + `drift_check` 交接信任。→ 已经比 DSH/Codex 更完整，落在 §5.5/§28。

### 10.4「取其精华去其糟粕」：多 Agent 记忆综合方案

**护住（XEYO 固有，务必保留）**
1. 六层隔离 + `agent_scope` 工具裁剪 + 单写者 + `MemoryCandidate` 主会话确认 + KV 隔离 + 原子索引 + `write_policy` 门禁。（`agent_scope.py`、`subagent_memory.py`、`memdir.py`、`write_policy.py`）
2. XEYO.md / `session.md` / 主 JSONL / `compact_cursor` 只归主会话（`agent_scope.py:28`）——子代理绝不写。

**抄回（从 Codex 补 XEYO 缺口）**
3. **自动收敛线**：仿 Codex 后台 `memory_stage1/consolidate_global` job，但落到 **XEYO 门禁**——子代理结束（`SubagentHandoff.memories`）→ 主会话确认 → 后台/归宿写入 memdir；NightShift 已是离线重塑，补"会话/任务结束自动升级候选"。（借 `state/runtime/memories.rs:19,45` 的**异步 job** 思想；门禁用 XEYO 自有 `write_policy`）
4. **模型记忆检索 + citation**：已有 `search.py`/JournalQuery，补 Codex `memory_search`/`memory_read` 的**检索+引用溯源**（`path:lines|note`）（借 `tools/search.rs`、`read_path.md` 的 citation 形态）。
5. **三级内容**：`MEMORY.md`(导航) + 摘要 + `topics/*`(详情) + citation——抄 Codex 分层，但 `MEMORY.md` **仍只做导航索引**（护 XEYO 低成本，`memdir.py:198` index_line 无叙事）。

**抄精（DSH 指令层精确化）**
6. L1 指令用 DSH 的 **digest 增量 + SHA-1 内容身份 + 触摸驱动 + tombstone**（`dsh-agent-instructions/README.md:45,53,110`），替换"整段重注入"为精确增量。

**去糟（避免踩坑）**
7. **别照抄 Codex 自动收敛的"弱治理"**：自动沉淀必须过 `write_policy` 门禁 + 仅主会话确认，否则子代理猜测/一次性计划沉进长期记忆（这正是 XEYO `write_policy` 拒目录树/临时计划的原因）。
8. **别照抄 DSH 的"无事实记忆"**：子代理发现的知识必须留档（candidate→主确认→memdir），否则多 Agent 等于 N 个失忆工人。
9. **别把全局单一 `memory_root` 当默认**：坚持 workspace `project` + 用户 `user` 分层（`agent_scope`），子代理默认隔离（`share_kv_prefix=False`），少数需要再显式继承——避免 Codex 式跨任务污染。

**落地句式**：子代理 = **只读记忆 + 侧链上下文 + 回传一条摘要 + `MemoryCandidate[]` 过主会话门禁 + 工具剔除 Memory**；主会话 = **唯一写者（memdir/session.md/索引）+ 唯一权威 L2/L5/L6**；收敛 = **异步 job 自动沉淀候选 + NightShift 离线重塑**；检索 = **`MEMORY.md` 导航 + `search` + citation 溯源**。→ 这套把 DSH 的指令精确、Codex 的自动收敛/检索/三级、XEYO 的治理/隔离/门禁三者的**精华**缝在一起，同时去掉了三家的**糟**（DSH 无事实记忆、Codex 弱治理+全局污染、XEYO 缺自动收敛+缺 citation）。

### 10.5 证据清单（本节能追溯项）

- **XEYO 当前**：`python/memory/agent_scope.py:27-63,81-99`；`python/memory/subagent_memory.py:17-21,143-151`；`python/memory/governance.py:57`；`python/memory/write_policy.py:32-59`；`python/memory/memdir.py:192-224,227`；`python/memory/journal.py:53-60,143-160`；`python/memory/nightshift.py:56-57`；`python/memory/runtime.py:472-508`；`python/tests/test_agent_scope.py:24-31`。
- **用户设计**：`docs/设计/10-完整记忆体系.md§5(1130-1216),§3.4.7(480),§2.6`；`docs/设计/28-多Agent协同设计.md §2.1-2.5(47-209),§5.5 写冲突`。
- **DSH**：`node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-agent-instructions/README.md:5,9,17,45,53,72,86,110`；`dsh-tool-skill/README.md:11,13`；`dsh-compaction`（包存在）。
- **Codex**：`codex-rs/ext/memories/src/tools/mod.rs:28`、`tools/{add_ad_hoc_note,list,read,search}.rs`、`src/tests.rs:111-144`；`codex-rs/state/runtime/memories.rs:19,45,2840`；`codex-rs/memories/write/src/workspace.rs:58`、`memories/README.md:136`、`memories/write/templates/*/consolidation.md`、`ext/memories/templates/memories/read_path.md:22-37`；`codex-rs/memories/read/src/usage.rs:47`/`citations.rs`；`codex-rs/external-agent-migration/src/memory_import.rs:20-31`；`codex-rs/core/src/agent/role_tests.rs:419`；`codex-rs/core/src/stream_events_utils.rs`（citation）。

---

## 十一、全量记忆体系对照与取舍结论（DSH × Codex × XEYO）

> §十 聚焦"多 Agent 记忆"。本节把范围扩到**整套记忆**（不只子代理）做三方并排，给出**明确取舍结论**：XEYO 现状是骨架、三家精华只补 3 处、糟粕明确去。

### 11.1 三家全量记忆对照（按 XEYO 六层映射）

| 六层 | DSH | Codex | XEYO 当前 |
|---|---|---|---|
| L1 指令 | **强**：AGENTS.md 增量 diff/digest+内容身份+无 watcher/触摸驱动+tombstone（`dsh-agent-instructions/README.md:45,53,110`） | 规则/记忆分离 + roles | XEYO.md（读）；`instruction_maintain.py` 维护规则块 |
| L2 短期 | 会话内 | 会话内 | 主 JSONL 权威 + 子代理侧链（`agent_scope.py`） |
| L3 工作 | — | — | `agent_id` 快照 + TodoStore key=agent_id |
| L4 长期 | **无**（只有指令，无事实库、无模型写工具） | **自动归一**：MEMORY.md 注册表 + memory_summary 索引 + skills/rollout_summaries（`memories/write/src/workspace.rs:58`） | **强+治理强**：memdir topics + MEMORY.md 导航 + 门禁 + 原子索引 |
| L5 摘要 | compaction 会话摘要 | rollouts + memory_summary.md | 主 session.md+cursor；C1/C2 双层压缩（`summarize.py`、`session_md.py`） |
| L6 休眠 | —（无） | —（无对应） | NightShift 离线重塑（`nightshift.py`，单写者） |
| KV/费用 | 指令+compaction | 自动归一（每轮可能动 memory） | **KV 前缀稳定 + proj_cache 增量 + 分层动手**（`cache_profile.py`、设计 §2.6/§4.7）——三家唯一把"KV/命中 vs 变笨"做成计算模型的 |
| 读/检索 | 指令 `<system-reminder>` 注入 + 技能目录（`dsh-tool-skill/README.md:11,13`） | **模型记忆工具**：`list/read/search` + citation（`ext/memories/src/tools/*`、`read_path.md:22-37`） | MEMORY.md 索引注入（`runtime.py:472-508`）+ `search.py` + JournalQuery |

### 11.2 XEYO 现状的"精"（必须护，别弄丢）

1. **治理派独一档**：六层隔离 + 单写者收敛 + `MemoryCandidate` 仅主会话确认 + KV 默认隔离 + 子代理剔除 Memory 工具 + 原子索引重写 + `write_policy` 内容门禁（`agent_scope.py`、`governance.py`、`memdir.py:205-224`、`write_policy.py:32-59`）——DSH/Codex **都没有**这套写治理。
2. **KV 经济学独有**：把"KV 命中 vs 变笨"做成计算公式（§4.7 v6.1）+ 前缀稳定 + proj_cache 增量——这是 Codex/DSH 没有的成本-效果模型。
3. **已吸收不少精华**：L1/L5/L6 + 隔离 + 门禁 + 检索雏形，整体已是 9 分。

### 11.3 那 3 处"取其精华"（补短板，不重构）

| # | 抄谁 | 抄什么 | 落点 | 成本 | 优先级 |
|---|---|---|---|---|---|
| 1 | **Codex** | **自动收敛线**（异步 job 把会话/子代理沉淀进 memdir）——但**过 XEYO 门禁 + 仅主会话确认** | `docs/设计/39-多Agent记忆自动收敛设计.md` | 中 | T14·P0 先行（自动是唯一真缺口） |
| 2 | **Codex** | **模型检索 + citation 溯源**（`memory_search/read` + `path:lines\|note`） | 读端补 `search.py`/JournalQuery 引用 | 低 | P2 |
| 3 | **DSH** | **L1 指令 digest 增量 + 内容身份 + 触摸驱动 + tombstone**（替整段重注入） | `instruction_maintain.py` | 低 | P2 |

### 11.4 明确"去糟"（别踩的坑）

| 糟 | 为何该去 | XEYO 对策 |
|---|---|---|
| **Codex 自动收敛"弱治理"** | 靠模型+摘要，无写门禁 → 子代理猜测/一次性计划会沉进长期记忆 | 保留 XEYO `write_policy` 门禁 + 仅主会话确认（§39 设计已含） |
| **Codex 全局单一 `memory_root`** | 跨任务/跨会话可能互相污染 | 保留 workspace `project` + 用户 `user` 分层 + 子代理默认隔离（`share_kv_prefix=False`） |
| **DSH 无事实记忆** | 只有指令层，跨任务知识不积累 | XEYO 已有 L4 事实库，**不退**回去 |
| **Codex 每轮再索引 memory_summary** | 重、动 KV | XEYO `MEMORY.md` 只做导航索引（`memdir.py:198` index_line 无叙事），`memory_summary` 级索引可选、别每轮跑 |
| **DSH compaction 会话摘要为主** | 丢"为什么/坑"等事实 | XEYO 的 L4+journal 已补，别只用摘要 |

### 11.5 结论（一句话）

**保持 XEYO 当前记忆体系为骨架（9 分、不重写），只按"取其精华"补 3 处低成本短板——自动收敛线（T14/P0）、模型检索+想 citation 溯源（P2）、L1 指令 digest 增量（P2）——并把 Codex 的"弱治理自动写/全局单 root"与 DSH 的"无事实记忆"明确列为**去糟**对象。** 即：XEYO 当前值得保留，需要的不是重写，而是"补 3 笔 + 防 3 坑"。
