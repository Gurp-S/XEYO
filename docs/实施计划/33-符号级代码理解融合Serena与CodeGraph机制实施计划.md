# 33 - 符号级代码理解:融合 Serena 与 CodeGraph 机制到既有工具(实施计划)

> 状态:已冻结(2026-08-30,第一阶段 + 第1/2层输出形态优化全部落地;第2层含 detail=folded 折叠与 kinds 过滤,commit 1a2293e)
> 目标读者:XEYO 后端维护者
> 关联:Serena(MIT,符号级代码工具)、CodeGraph(代码知识图谱)的**实现机制自研移植**,非外挂、非 MCP 接入

---

## 一、目标

### 1.1 一句话目标

不新增任何工具、不引入 LSP 子进程、不建持久索引,通过**一个按需解析的符号缓存模块 + 给 Read/Grep 各加一个参数**,让 XEYO 的既有工具获得 Serena 的符号级读取代价优势与 CodeGraph 的"仓库符号目录"能力。

### 1.2 要解决的真实问题

当前 agent 理解代码只有两条路,都有明确代价:

1. **Grep 定位 + Read 整读**:看一个 800 行文件里的一个函数,要为几百行无关内容付出 token 与轮次;
2. **纯文本检索理解结构**:`def|class` 正则 grep 只能拿到"哪里有定义",拿不到符号层级(方法属于哪个类)、签名、行号范围,更拿不到一次调用就浏览全仓库符号目录的能力。

对照之下:

| 能力 | Serena 的做法 | CodeGraph 的做法 | 本计划的做法 |
|---|---|---|---|
| 只读某个符号体 | LSP/tree-sitter 定位行号范围后截取 | — | Read 加 `symbol` 参数,同机制自研 |
| 按名找符号 | tree-sitter 符号索引 | 图节点查询 | Grep `output_mode: "symbols"`,同机制自研 |
| 引用/依赖图 | LSP 精确解析 | 持久图存储边 | **本计划不做**(见 5.1 边界) |

### 1.3 硬性约束(验收红线)

- **零新工具**:`ENABLED_TOOL_ENTRIES`、`TOOL_META`、`policy.py`、`catalog.py` 一律不改;启动断言不得漂移。
- **零持久状态**:无 SQLite、无文件监听、无后台索引线程、无新进程。
- **零硬依赖**:tree-sitter 是可选依赖,未安装时功能降级而非报错;Python 文件走内置 `ast`,零依赖可用。
- **主循环零改动**:`query_loop.py`、`turn_runner.py` 不动。

---

## 二、最终结构

### 2.1 新增与修改的文件全景

```
python/
├── codeindex/                          # 新增包(底座,唯一新代码集中地)
│   ├── __init__.py                     #   导出 outline / locate / iter_symbols
│   └── symbols.py                      #   解析器 + 缓存 + 降级策略(~300 行)
├── tools/
│   ├── file_read_tool/
│   │   └── file_read_tool.py           # 修改:schema 加 symbol 参数 + 执行分支
│   │   └── prompt.py                   # 修改:描述补充 symbol 用法一句
│   └── grep_tool/
│       ├── grep_tool.py                # 修改:output_mode 加 "symbols" + 分支
│       └── prompt.py                   # 修改:描述补充 symbols 模式一句
├── requirements.txt                    # 修改:追加可选依赖(注释标明 optional)
└── tests/
    └── test_codeindex.py               # 新增:底座单测
```

不触碰的文件(作为红线自查清单):`tools/meta.py`、`tools/catalog.py`、`tools/base_tool.py`、`tools/tool_registry.py`、`permissions/*`、`engine/*`。

### 2.2 底座模块设计:`python/codeindex/symbols.py`

```python
@dataclass(frozen=True, slots=True)
class Symbol:
    kind: str          # "class" | "function" | "method" | "interface" | ...
    name: str          # 标识符
    start: int         # 起始行,1-indexed,含
    end: int           # 结束行,1-indexed,含
    parent: str | None # 父符号名(方法 → 所属类),构成一层伪图
    signature: str     # 单行签名串,如 "def query_loop(abort) -> AsyncIterator[Event]"

# 三个公开函数,全部 workspace 路径入口
def outline(path: str) -> list[Symbol]
    # 单文件符号大纲;结果按 start 行排序;方法嵌在类下并自带 parent
def locate(path: str, symbol_path: str) -> Symbol | None
    # 点号路径定位,如 "ChatStore.applyRewind"、"query_loop"
    # 先精确匹配全路径,再回退尾段唯一匹配(同名多定义时返回 None 并让调用方提示歧义)
def iter_symbols(paths: Iterable[str], pattern: str) -> Iterator[tuple[str, Symbol]]
    # 多文件流式过滤,供 Grep symbols 模式使用;惰性,逐文件产出
```

内部机制三层:

1. **缓存**:`dict[str, CachedEntry]`,键为绝对路径,值为 `(size, content_hash, tuple[Symbol, ...])`。
   失效校验借鉴 CodeGraph 类项目的**内容哈希**机制(而非 mtime):命中时读文件 → 算哈希(blake2b,10 万字符亚毫秒级)→ 一致直接用缓存,不一致才重解析。由于 parse 本身就要读整个文件,哈希校验不引入额外 I/O,只是把"读后必 parse"变成"读后可选 parse",省下的正是最贵的 CPU;同时彻底规避 Windows mtime 同秒粗粒度问题(哈希对内容敏感、对时间不敏感)。
   全局上限 `MAX_CACHED_FILES = 5000`,超限淘汰最旧(插入序 LRU,`OrderedDict` 即可)。
   **只缓存 Symbol 元数据与哈希,绝不保留 AST/语法树/源码文本**——这是内存不爆炸的根本前提(量级论证见 5.2)。
2. **语言后端**(按扩展名分发,`_BACKENDS` 表驱动):
   - `.py`:内置 `ast` 模块。遍历 `ast.ClassDef / FunctionDef / AsyncFunctionDef`,取 `node.lineno/end_lineno`,signature 由 `ast.unparse(args)` 拼装。零依赖,精度完整。
   - `.ts/.tsx/.mjs/.js`:懒导入 `tree_sitter` + 语言 grammar;`ImportError` 时降级为正则启发式(匹配 `function X(`、`class X`、`interface X`、`const X = (` 等声明行),启发式结果标记 `kind` 原样、`end` 取缩进回推的块尾(启发式下允许不准,调用方语义是"尽力")。
   - 其他扩展名:返回空列表,调用方自然回退原行为。
3. **防御**:解析异常(语法错误文件等)吞掉并返回空,缓存空结果(带哈希)避免反复重试;单文件解析加软超时保护异常大的文件(超过阈值行数直接走启发式)。

### 2.3 Read 工具改动:`symbol` 参数

schema 新增(与 `offset/limit` 互斥,schema 层写明):

```json
"symbol": {
  "type": "string",
  "description": "Read only one symbol's body instead of the whole file, e.g. \"MyClass.handle_request\" or \"query_loop\". Cannot be combined with offset/limit."
}
```

执行分支(在文本读取路径内,vision/PDF 路径直接拒绝该参数):

```
if input_data.symbol:
    sym = codeindex.locate(expand_path(file_path), input_data.symbol)
    if sym is None: 返回错误,提示先用 Grep output_mode="symbols" 查确切名字(含歧义列表)
    return read_lines(path, sym.start, sym.end)   # 复用既有按行读 + 截断逻辑
```

权限语义不变:Read 本就是 read-only / always-allow,`symbol` 只是缩小返回范围,**只会更安全**。返回的 metadata 里附 `"symbol": name, "range": [start, end]`,便于前端展示与审计。

### 2.4 Grep 工具改动:`output_mode` 增加 `"symbols"`

枚举扩展为 `["content", "files_with_matches", "count", "symbols"]`。命中 `"symbols"` 时:

- 不调用 rg;用 `codeindex.iter_symbols(path 展开 + glob 过滤, pattern)` 流式收集;
- 输出行格式对齐 grep 习惯:`{file}:{line}: {signature}`,文件路径相对 cwd;
- 复用既有 `head_limit / offset / -i` 语义(pattern 过滤 `name`,大小写不敏感遵循 `-i`;不加 `glob` 时默认排除 node_modules/.git/dist/__pycache__/build);
- 全局防御:累计符号数到 `MAX_SCAN_SYMBOLS = 200_000` 即截断并附提示,防误扫巨型目录拖死一次调用。

输出示例:

```
python/engine/query_loop.py:392: async def query_loop(...) -> AsyncIterator[Event]
python/engine/query_loop.py:1245: def _perm_resume(...)
gui/src/stores/chatStore.ts:88: class ChatStore
gui/src/stores/chatStore.ts:140:   applyRewind(...)
```

这一形态就是 CodeGraph"列节点"查询的高频子集:一次调用拿到全仓库的类/函数目录,含归属层级与行号。

### 2.5 依赖变更

```
# requirements.txt 追加(可选,缺失自动降级)
tree-sitter>=0.22        # TS/JS 符号解析,未安装时用正则启发式
tree-sitter-typescript>=0.21
tree-sitter-javascript>=0.21
```

代码中一律 `try: import ... except ImportError` 懒加载;启动脚本与 `XEYO.bat` 无需感知。

---

## 三、具体步骤(按实施顺序)

### 阶段划分(先读这段再开工)

- **第一阶段 = Step 1 ~ Step 4**(本次开工范围):`codeindex` 底座 + Read `symbol` 参数 + Grep `"symbols"` 模式 + 端到端验收。全部零持久状态、零新进程,交付后即可日常使用。
- **第二阶段(另立计划,不在本次范围)**:若第一阶段实测后确有"改这个函数影响谁"类需求,再议持久化引用图(CodeGraph 路线:SQLite + 内容哈希增量重索引,在 `codeindex` API 下替换实现,工具层不动)。
- **LSP / 文件监听路线(Serena 路线)= 最后的最后**:只有当无状态缓存方案与持久图方案都被实测证明无法满足时才重新评估;该路线意味着每语言一个常驻子进程、监听转发链路与崩溃恢复,与本项目"不重"的根本取向冲突。在此之前不做任何相关预研或预留代码。

### Step 1:底座 `python/codeindex/symbols.py`(纯新增,先行可独立验证)

1. `Symbol` dataclass + 缓存结构(含 LRU 上限、(size, content_hash) 键控);
2. Python 后端(`ast` 遍历,parent 归属,signature 拼装);
3. TS/JS 后端:tree-sitter 懒导入 + 正则启发式降级;
4. `locate()` 的点号路径匹配与歧义返回;
5. `iter_symbols()` 流式过滤 + 排除目录 + 截断上限;
6. 单测 `python/tests/test_codeindex.py`:
   - 缓存命中/失效(内容变化哈希不匹配 → 重解析;内容改回原样 → 命中)、LRU 淘汰;
   - 语法错误文件返回空且不抛;
   - `Class.method` 精确定位、同名歧义返回 None;
   - TS 无 tree-sitter 时启发式降级可用;
   - 排除目录与 MAX_SCAN_SYMBOLS 截断。

**验证**:单独跑 `pytest tests/test_codeindex.py`,不碰任何既有模块,此时仓库行为与改前完全一致。

### Step 2:Read 接入 `symbol` 参数

1. schema 加字段(含与 offset/limit 互斥说明);
2. 执行分支:locate → 行号范围 → 复用既有读取;未命中/歧义给出引导性错误信息;
3. `prompt.py` 描述补一句:"优先用 symbol 只读单个类/函数,避免整文件读取";
4. 跑既有 `test_file_tools_contract.py` 确认契约未破,补 2~3 条 symbol 路径用例。

### Step 3:Grep 接入 `"symbols"` 模式

1. `output_mode` 枚举扩展;
2. 分支实现 + 输出格式 + head_limit/offset 复用;
3. `prompt.py` 补一句:"找符号定义/浏览仓库结构时优先 output_mode=symbols";
4. 跑 Grep 既有测试 + 新增用例。

### Step 4:端到端验收

1. 起 XEYO,对 `gui/src/stores/chatStore.ts`(真实大文件)依次验证:
   - Grep symbols 一次列出仓库符号目录;
   - Read symbol="ChatStore.applyRewind" 只返回该方法的行;
   - 故意传错符号名,确认错误信息引导模型改用 Grep 查名;
2. 确认 `test_catalog.py` 启动断言通过(红线:meta/catalog 零改动);
3. 确认未装 tree-sitter 的干净环境(临时 venv)下 TS 降级路径可用、Python 路径完整。

### Step 5:文档收尾

`README.md` 核心能力一节补两行(符号级读取/符号目录);本计划文档状态改为"已落地",记录实际行数与偏差。

---

## 四、可能遇到的问题与解法

### 4.1 内存膨胀(已论证可控,但设防)

**问题**:长会话反复扫描大仓库,缓存只进不出;误扫 node_modules 等巨型目录。
**解法**(全部在底座内,见 2.2):只缓存 Symbol 元数据不缓存 AST/源码——20 万符号约 40–60 MB;`MAX_CACHED_FILES=5000` 插入序 LRU;固定排除目录清单;`MAX_SCAN_SYMBOLS=200_000` 单次调用截断。
**判定**:若实测仍超预期(>150 MB),把缓存改为进程级 `functools.lru_cache` 按文件数硬限,或直接砍缓存改为会话内弱引用——底座 API 不变,调用方无感。

### 4.2 缓存失效(已通过内容哈希解决,借鉴 CodeGraph 机制)

**问题**:若用 mtime 做失效键,Windows 同秒粗粒度下"写入再改回"会命中过期缓存;外部变更(git checkout、脚本生成)也无法被 mtime 之外的机制感知。
**解法**:缓存键采用 `(size, content_hash)`,命中时读文件算哈希校验。因 parse 本就要读整个文件,校验无额外 I/O,只是"读后必 parse"变为"读后可选 parse";哈希对内容敏感,同秒改写、内容改回等 mtime 场景全部天然正确。此设计参考了 CodeGraphContext 的 XXH3 内容哈希增量重索引机制(见"参考"),选用标准库 blake2b 避免新依赖。
**残余风险**:校验发生在"读文件"之后,即每次命中仍付一次文件 I/O——这是零状态方案的固有代价,量级为亚毫秒,可接受;若未来测量发现 I/O 成为瓶颈,演进顺序固定为:先评估第二阶段持久图路线,**LSP/监听路线是排在持久图之后的最后的最后**(见"三、阶段划分")。
**对照参考**:Serena 不缓存、靠 LSP did_change 通知 + 文件监听转发外部变更(其 CHANGELOG 记录了外部变更未通知导致引用结果过期的修复);CodeGraph 类项目持久图 + 内容哈希增量重索引。本方案取中间态:无监听、无子进程,用哈希校验兜住正确性。

### 4.3 符号定位歧义(同名方法、重载)

**问题**:`locate("applyRewind")` 命中多个类下的同名方法,或 TS 重载签名。
**解法**:精确点号路径优先;尾段匹配多命中时返回 None,Read 错误信息列出全部候选(文件:行:签名),模型自然改用全路径。TS 重载取首个声明的范围,初版接受。

### 4.4 TS/JS 解析精度不足(无 tree-sitter 降级)

**问题**:正则启发式拿不到准确 end 行、嵌套类/箭头函数归归属不准。
**解法**:降级产物明确"尽力"语义——end 不准只影响 Read symbol 截断范围(宁可少给不给错:启发式下截断范围向内收缩 0 行,但 Read 返回时附 `"approximate": true` 标记与符号名,模型可用 offset/limit 微调);requirements 默认会装上 tree-sitter,降级仅是干净环境兜底。
**判定**:Python 路径(本仓库自身 + 多数用户项目)零依赖且精度完整,TS 是增强项,允许不完美。

### 4.5 大文件 / 超大仓库单次调用耗时

**问题**:Grep symbols 扫 1 万+ 文件首次全解析,树客户端可能数秒。
**解法**:流式产出(边解析边收集,head_limit 命中即停,后续调用命中缓存);head_limit 默认 250 本就限制了全扫范围;排除清单挡住大头(node_modules)。预热不做——首次慢一次是可接受的代价,换取零状态。

### 4.6 schema token 预算

**问题**:`tool_registry.schemas()` 有 token 预算机制(`apply_schema_budget`),Read/Grep 描述加长可能挤压其他工具。
**解法**:新参数 description 控制在一行内;prompt.py 的长解释放工具描述里,若预算超限由 meta 的既有预算机制自动裁剪,实测 Step 2/3 后跑一次 `test_catalog.py` 观察。

### 4.7 与既有行为冲突的边界

- Read 的 vision/PDF 路径:`symbol` 参数传入即报参数冲突错误,不进视觉分支;
- Grep 的 `-B/-A/-C` 与 symbols 模式:明确无意义,分支里忽略(schema 描述注明仅 content 模式有效);
- Read `symbol` 与 `offset/limit` 同传:参数校验直接报错,让模型二选一。

---

## 五、明确不做的(边界声明)

1. **跨文件引用解析(CodeGraph 的"边")**:调用图、`find_references`、影响面分析。它需要持久图或 LSP,是本计划"轻"的边界外。现阶段引用查找 = Grep 搜符号名,准确率对 agent 日常够用;将来若做,持久层在 `codeindex` API 下替换,工具层不改(预留的演进路径)。
2. **LSP 子进程接入(含文件监听转发)**:明确定为**最后的最后**——只有无状态缓存(本计划)与持久图(第二阶段)两条路线都被实测证明无法满足需求时,才重新评估;不预研、不预留代码(理由见"三、阶段划分")。
3. **写入类符号操作**(rename symbol 等):Serena 的另一半能力,涉及多文件写与权限面,留待有真实需求后另立计划。
4. **符号大纲自动注入 system prompt**:可省一次工具调用,但改动主循环,违反零侵入红线;后续可另议。

---

## 六、最终收益

### 6.1 直接收益(可度量)

| 收益 | 机制 | 预期量级 |
|---|---|---|
| **读符号体省 token** | Read symbol 只返回目标函数/类 | 常见"大文件看一个函数"场景 token 降为原来的 5%–20%;800 行文件读一个 40 行方法,直接省 95% |
| **省轮次** | 无需"grep 定位行号 → 再算 offset/limit → 再读"三步 | 符号读取一步到位;对高频导航场景每任务省 1–3 轮 |
| **仓库结构一屏可得** | Grep symbols 列签名目录 | 一次调用替代多次 `grep "^def\|^class"`,且含行号范围与类归属(纯文本 grep 做不到) |
| **TS/Python 外的免费扩展位** | `_BACKENDS` 表驱动 | 新语言只需注册一个后端函数,工具层不动 |

### 6.2 架构收益

- **零状态哲学得到验证**:证明 agent 的代码理解能力可以不靠"索引基建"而靠"解析缓存"获得,为后续按需引入持久层(LSP/图)树立了对照基线——先有便宜的,再决定要不要贵的;
- **演进路径已铺好**:`outline/locate/iter_symbols` 三个 API 就是未来引用图的查询面,届时把实现从"内存缓存"换成"SQLite 图 + 增量同步",Read/Grep 的改动全部保留;
- **未动任何既有机制**:权限、审计、meta/catalog 断言、主循环全部原样,回归风险被压到两个工具文件内部。

### 6.3 收益边界(诚实声明)

- 引用/调用关系仍靠文本搜索,准确率低于 LSP——"改这个函数会影响谁"类问题本计划不解决;
- 精度取决于语言后端:Python 完整,TS 取决于 tree-sitter 是否安装;
- 收益以"读代码"为主,不改变写代码(Edit)的任何行为。

---

## 七、验收清单(Definition of Done)

- [x] `python/codeindex/` 落地,单测覆盖 2.2 全部用例;
- [x] Read `symbol` 参数可用,错误路径有引导信息,vision 路径正确拒绝;
- [x] Grep `output_mode="symbols"` 可用,排除清单与截断生效;
- [x] 干净环境(无 tree-sitter)Python 路径完整、TS 降级可用;装 tree-sitter 后精确路径可用;
- [x] `test_catalog.py` / `test_file_tools_contract.py` / Grep 既有测试全绿(全量 1048 通过,18 个失败为基线既有、与本计划无关,已用基线 worktree 对比确认);
- [x] meta.py、catalog.py、policy.py、engine/ 的 diff 为零(红线自查);
- [x] README 核心能力一节更新,本计划状态改"已落地"。

补充记录(实施期发现):
- tree-sitter Python 绑定无 `start_position`(Rust API),须用 `start_point.row`;
- tree-sitter 0.25/0.26 的 `Node.children` 迭代在真实大文件上会 access violation,requirements 已钉 `<0.25`(0.24.0 验证稳定);
- venv 实测:精确 TS 模式 `approximate: false`,启发式降级模式 `approximate: true` 均按预期工作。

### 落地后补充:第1/2层输出形态优化(冻结前追加,commit 1a2293e)

离线收益评测(`python/scripts/bench_codeindex_benefit.py`,零 API 调用)实测三挡位经济性(对 gui/src/stores,ground truth 396 符号):

| 挡位 | 参数组合 | token | 条目 | 定位 |
|---|---|---|---|---|
| 骨架 | folded + kinds=["class","interface"] | **73** | 4 | 看架构分层,旧路径无此能力 |
| 概览 | detail="folded" | 5,685 | 275 容器 | 全仓库概览,方法折叠可展开 |
| 全量 | detail="signatures"(默认) | 7,883 | 396 | 精确到每方法签名,下钻用 |
| (对照)旧路径正则 grep | — | 4,258 | 199(有损 50%) | 无行号范围/父级/方法 |

- 符号体读取(Read symbol):单次省 **98%** token(13,479→203 / 6,728→115)、轮次 2→1、零截断;
- 嵌套折叠判定用**行号范围包含**(object-literal 方法 parent=None 不可靠);
- 边界覆盖 8/8 PASS;红线保持 meta/catalog/engine 零改动;
- 遗留触发条件:若真实会话中概览挡频繁超 head_limit,再考虑概览挡默认限流(一行改动)。

---

## 八、参考

机制调研来源(2026-08):

- Serena(符号级工具,MIT):仓库 [oraios/serena](https://github.com/oraios/serena) · [CHANGELOG(外部变更未通知导致引用过期的修复记录)](https://github.com/oraios/serena/blob/main/CHANGELOG.md) · [配置文档](https://oraios.github.io/serena/02-usage/050_configuration.html) · [issue #799(语法错误文件被语言服务器拒绝)](https://github.com/oraios/serena/issues/799)
- CodeGraphContext(图数据库式代码图谱):[仓库](https://github.com/codegraphcontext/codegraphcontext) · [Tree-Sitter 知识图谱论文(arXiv,XXH3 内容哈希增量重索引)](https://arxiv.org/pdf/2603.27277) · [CodeGraph (colinvaughn,文件监听 + git hook)](https://mcpservers.org/servers/colinvaughn/codegraph)
- 机制对照结论:Serena = 无自有缓存 + LSP 通知/监听转发;CodeGraph = 持久图 + 内容哈希增量重索引;本方案取中间态 = 无状态内存缓存 + 内容哈希校验(见 4.2)。

