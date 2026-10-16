# XEYO Harness 源码审计与旁路 A/B（2026-10-11）

## 结论与交付边界

按用户后续选择，本轮仅完成源码审计和离线旁路 A/B，**没有并入默认行为**。
原对话的“Edit diff + py_compile 能让合法误删漏网率降到 0”不成立。
实验证明了信息丢失和无效 Python 写入这两类机制缺口，也证明了候选方案仍无法阻止合法语义损坏、未定义名称和直接写入路径的并发覆盖。因此不能报告“治本完全修复”。

新增文件只有独立评估模块、评估测试及本目录证据。没有编辑生产模块，没有改开关默认值，没有重启后端，没有重钉 golden。工作区在任务开始前已有大量未提交改动；本报告不把它们归属本轮。

源码基准 HEAD：`3e7fff023f7e1d3bdb050f654fecd29b345a5d44`。
HEAD 不能代表脏工作树，`ab-results.json` 另保存 10 个实际读取生产文件的 SHA-256。

## 实验口径

- A：实际 `FileEditTool.validate_input → call → map_tool_result_to_content`，以及默认 `digest` 投影。
- B：相同流程，使用既有 `XEYO_TOOL_RESULT_DIFF=full`；额外使用**仅在评估模块定义**的 Edit 子类，在 `_persist` 前对最终归一化 Python 内容执行 `compile(..., 'exec', dont_inherit=True)`。
- 两种持久化路径分别跑：直接写入、WriteStore。5 种输入 × 2 路径 = 10 组配对、20 次尝试。
- A/B 使用同进程内独立工具实例和临时工作区；环境变量逐段恢复。没有调用模型，没有使用真实会话和生产 journal，没有经过完整 registry / 权限审批 / 网络请求链。
- B 编译门是严格实验原型，不是已完成的生产实现；它会拒绝仍含编译错误的旧文件，未实现已有错误的修复策略。测试覆盖 Python，不覆盖 TS/JS/JSON、NotebookEdit、Bash 或全部写入入口。
- A/B 同时改变投影和写前编译两个因素，结果按不同机制分别解释，不能据此估计两因素组合的真实任务收益。
- 运行身份及 verdict 示例使用明确标注的夹具。台账登记、缓存和归属测试是源码/机制探针，未伪装成五项功能全部完成的生产 A/B。

## 1. Edit 回执与自动检查：结构性根因已定位，候选方案只解决部分机制

阶段：Edit 成功后，结果送入模型及写入持久化。归属：Harness；高严重度。

**证据**：`python/tools/file_edit_tool/file_edit_tool.py:578` 已生成 capped unified diff。
`python/prompt/tool_result_diff_digest.py:62` 默认 `digest`，`:119` 在投影时删除 diff；
`python/engine/query_loop.py` 的多个投影/重建出口调用该函数。
原对话把问题归因于“Edit 没生成 diff”，实际是模型投影删除了证据。

`python/engine/write_store.py:350` 计算 `syntax_ok`，`:356` 无条件写入，检查只是 journal 状态。
Edit `_persist` 只返回 journal 警示，没有把 `syntax_valid=False` 传给模型。
直接写入路径没有同等写前检查。Write 另有语法提示，不能证明 Edit 同样具备该行为。

**A/B 结果**：

- 合法误删（2 路径）：A/B 都接受；A 的 0/2 结果显示 diff，B 为 2/2。被删掉的 `"ERROR: "` 在 B 的结果里可见，但仍然被删除。
- 语法错误及“顶层 return”（4 个路径/用例组合）：A 全部接受并落盘，B 全部在落盘前拒绝，4/4 保持原磁盘字节。顶层 return 提醒了 `ast.parse` 与可编译代码并不等价。
- 未定义名称（2 路径）：A/B 全部接受，编译结果合法。编译检查不验证运行时名称、业务语义或任务要求。
- 全部 20 个结果：投影不改 transcript、重复投影幂等。小样本中保留完整 diff 的新增字符随改动变化，不能推广成固定成本或真实额度节省。

**额外高风险证据**：校验后把文件从 `value = 1` 外部改成 `value = 99`，再调用 Edit。
直接路径 A/B 都接受并覆盖成 `value = 2`；WriteStore 两边都拒绝并保留 99。
根因是 `call` 使用校验缓存的全文，而直接 `_persist` 不做锁内内容哈希比较；并且 diff 来自旧缓存，不能忠实反映被覆盖的外部内容。加编译门不能解决这一问题。

**治本规则与下一步架构**：模型投影保留可核对的实际变更；所有可写入口使用同一持久化事务，在同一锁内读当前正文、比较基线、检查最终候选、原子落盘，并返回来自本次事务的检查与变更事实。不能依赖写后提示或回读，也不能以无锁“再读一次”消除竞争窗口。

**回归设计**：精确覆盖合法删除可见性、拒绝后的磁盘/快照/journal 零修改、两写者交错、编码/CRLF、已有错误修复、创建文件和各写入口。语义正确性必须用目标行为断言；diff/compile 不作完整修复证明。
预期收益：消除指定的证据丢失和无效 Python 落盘；并发事务统一后才能消除已复现的外部覆盖。

## 2. 契约面查询与已知红：有基础设施，但归因口径不足

阶段：改默认面及验证。归属：Harness；中严重度。

`evals.changedetect` 已有 L0/L1 golden、`scripts/baseline_run.ps1` 已有临时 worktree 基线及台账。
未发现 `--who-pins` 实现，不能把文本搜索命中当成精确测试依赖，也不能仅凭测试 import 推断“谁会失败”。
`baseline_run.ps1:116` 仅根据整次退出码叙述红的归属；旧基线存在任意失败并不能证明当前失败也是旧失败。
默认 `first_head` 还可能早于某测试/合同，因此结论必须绑定提交、实际源码、用例身份及环境。

**实际定向运行**：42 条，38 通过、4 失败：

1. `test_declared_scratch_passes_write_and_bash_predicates`：Windows `.xeyo\\tmp` 与硬编码 `.xeyo/tmp` 不等。
2. `test_scratch_dir_reported_only_when_workspace_is_writable`：同一分隔符合同不一致。
3. `test_default_surface_unchanged_and_context_is_not_silently_discarded`：现源码已有 `matches`，旧断言预期不存在。
4. `test_content_single_file_pagination_uses_numeric_source_lines`：现源码返回数字第 2 行，旧断言预期第 10 行。

这些失败来自本轮未编辑的生产代码和已有测试，**没有进行历史提交基线归因**；只据本次实际源码描述，不照抄原对话的“全关对照 2 红”。

**治本规则**：历史红是版本化的失败用例集合，不是退出码标签。依赖查询分别报告静态候选、已实测钉住面与未覆盖，集合差分区分共同失败、新失败、修复和缺失测试。缓存键包含源码/环境/测试身份。
回归：基线失败 X、当前失败 Y；新增测试在旧版本缺失；宿主开关被测试 fixture 清掉；精确相等与语义合同分别归因。
收益：减少错误归因；本轮未实现该产品查询，未做它的因果 A/B。

## 3. 会话开关台账：不能再维护一份手写名单

阶段：默认值变更与报告。归属：Harness + 模型工作集管理；中严重度。

已有 `python/engine/env_switches.py` 统一登记表，但没有完整的“会话触碰 → 当前谓词值 → 默认值 → 来源版本”查询。
本轮直接调用 10 个现有开关谓词，逐项测未设/显式 0/显式 1，并恢复环境。只有 1/10 在 `SWITCHES` 登记。
这表示登记不完整，不表示仓库所有开关只有 10 个，也不证明全部漏登记项都会漂移 golden。

实测默认：execution contracts、completeness、scratch、env extra、read structure hint、grep pagination、grep symbol ranges、bash error origin 开；tool description facts、env syntax 关。
因此“tool description facts 开事实方案”在源码里实际由另一个 `XEYO_READ_STRUCTURE_HINT` 承担，不能混称为同一开关。

**治本规则**：当前值来自真实执行谓词；定义/默认语义与测试隔离共用登记；会话触碰来自实际操作事实，按需查询，不常驻注入。缺来源明确返回 unknown，不靠猜测字符串值。
回归：unset/0/1、非法值、运行中覆盖、会话隔离、退役开关、未登记来源。
收益：减少默认值重建和错误报告。当前结果是机制探针，未建立生产会话台账，未证明实际调用次数减少。

## 4. 运行身份与并发改动归属：已有事实不等于完整来源证明

阶段：判断代码是否生效及 git 改动归属。归属：Harness；中严重度；直接覆盖为高。

`server/portfile.py:78` 已记录 PID、started_at、engine_version，env facts 没有把这些提供为按需运行事实。
本机端口文件记录 PID 22520、版本 1.11.0、启动时间 `2026-10-11T03:38:56+00:00`（香港 11:38:56）。
这里只读取端口文件，**未验证进程存活、未读取后端内存、未确认生产进程加载版本**。
缺少 scratch 也可能由开关/权限造成，原对话仅据该字段缺席判“旧进程”不具唯一性。

运行夹具：内存函数返回 1，改磁盘后源码返回 2，而内存函数及 code hash 保持原值。
证明现场 git HEAD/文件 hash 不等于加载代码身份。该 hash 只标识一个函数，不涵盖模块常量、配置或完整后端。

`session_presence.py` 已有写入归属；实际探针写 65 个文件，只保留 64 个，过 TTL 后为 0。
`JournalQuery` 已能按会话筛 journal，但兼容无 session_id 旧记录，不能把这些旧记录归给当前会话。
会话曾写过某文件，也不证明 git diff 每一行属于它；“未写过”更不能自动推断是谁写的。

**治本规则**：运行身份在实际加载/启动时冻结，记录构建/模块来源与配置世代；磁盘版本单独查询。完整会话变更查询使用可恢复且带来源的事务日志，分别呈现已记录本会话操作、其他已记录写者、来源未知，保留证据边界。
回归：磁盘改动不改变 loaded 身份、重启改变世代、跨进程、归属过期/截断、Bash/外部编辑、同文件多个写者。
收益：避免误判生效与误领他人改动。本轮未接入生产运行身份及归属分组，没有宣称该项已修复。

**发现的缓存缺口**：`env_facts.py:261` 默认开态使用 `cache or collect` 但未写回缓存；夹具两次请求触发两次 collect。
另在已有缓存、写范围收窄且 scratch 开关仍开时，只更新 writable、不重新计算 scratch；夹具实际返回 writable 消失但 scratch 残留。
正确边界应分离进程稳定事实缓存与实时权限事实；本轮仅复现，不修改生产行为。

## 5. verdict-first：展示摩擦成立，不能当作安全修复

阶段：读取验证结果。归属：Harness；低严重度。
`evals/changedetect/__main__.py:54` 先输出完整索引，再输出 verdict。
夹具使用实际 `cmd_surface_check`，A 判决在第 4 行；评估输出重排 B 在第 1 行，保留相同文本行与退出码 0。
这只证明展示方案无信息丢失。未接入 CLI，未测试变化面/严格模式失败的全部展示组合，未证明模型少调用了工具。
治本规则：判决和明细使用同一比较结果，首行判决、完整索引独立按需查询；回归同时核对文本与退出码。

## 验证与尚未覆盖

- 新增旁路测试：9/9 通过。
- 已有定向测试：38 通过、4 失败，身份如上。
- L0 `surface check --strict`：退出码 0、无变化。没有重写 golden。
- L1 `trace check --strict`：退出码 0、无变化，但 `loop/multi_turn` 的输出包含 `<raised AttributeError: 'Message' object has no attribute 'get'>`。这说明 golden 相等不代表运行健康；没有在本轮修复该异常。
- 没有全量 WSC、`scripts/check.ps1`、真实模型任务 A/B、额度/延迟测量或压缩实验。原对话重复回读次数、36% 上下文、收益面 2.2% 等历史数字未获得原始 rollout，本轮不把它们当已验证数据。
- 结构视图事实与截断事实的默认行为已从源码核实，但没有把原对话所有“已改善”项再次完整重跑，也未用这一结果证明减少回读或临时文件残留。

## 重跑

在 `python/` 下执行：

```powershell
py -3.11 -m evals.harness_friction_audit --out ../docs/harness-friction-audit-2026-10-11/ab-results.json
py -3.11 -m pytest tests/test_harness_friction_audit.py -q
```

后续实施顺序由本报告的风险决定：统一写入事务与真实变更证据、写前检查、版本化合同归因、按需事实查询、展示调整。实施仍需保持旁路，满足相应行为断言后再评估是否并入默认；本轮没有发生并入。
