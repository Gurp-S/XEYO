# 宿主 env 不密闭：待裁方案（2026-10-07）

> 只碰测试与名单来源，**不碰 `system_prompt`／冻结前缀**，故不触发基线重钉。
> 本文件是待裁方案，不含已实施改动。

## 一、现象与实测证据

同一工作树、同一命令，唯一变量是进程环境：

```
py -3.11 -m pytest python/tests/test_context_limit_declared.py \
  python/tests/test_runtime_c2.py python/tests/wsc/test_extension_economics.py \
  python/tests/wsc/test_fold_cadence_veto.py python/tests/wsc/test_fold_gate_coverage.py -q

A) 宿主原样                                  : 12 failed, 62 passed
B) 清 SOFT_WATERMARK + COMPACT_RATIO          : 74 passed
C) 只清 XEYO_WSC_SOFT_WATERMARK               :  1 failed, 73 passed   ← 它负责 11 条
D) 只清 XEYO_CONTEXT_COMPACT_RATIO            : 11 failed, 63 passed   ← 它负责 1 条
```

（`test_data_root_overrides` 也曾在此集合内，已作为自引入回归单独修掉，故 13→12。）

症状与键的对应关系可逐条核对：

| 宿主键 | 值 | 症状 |
| --- | --- | --- |
| `XEYO_WSC_SOFT_WATERMARK` | `200000` | fold 记录 `reason='soft_watermark_below_soft_watermark'`——软水位抢先否决，走不到 θ 门/经济性路径；`economics_basis` 随之缺失 |
| `XEYO_CONTEXT_COMPACT_RATIO` | `0.95` | `should_force_compact_on_pressure(100000, 120000)`：`120000×0.95=114000>100000` ⇒ 不到压线，返回 False |

同族历史记录（更早一轮）：`XEYO_TOOL_DENY=Agent` ⇒ 8 文件 18 条；`XEYO_WSC=1` ⇒ 12 条；`XEYO_WSC_SIZE_PRUNE=1` ⇒ 1 条；changedetect golden 实测 4+3 处幻影变化。

## 二、结构性根因（不是"再补两个键"）

**隔离名单有三份、无单一来源，且按"已知坑"人肉补丁式维护：**

| 来源 | 覆盖 | 维护方式 |
| --- | --- | --- |
| `tests/conftest.py` | 12 键（`XEYO_WSC*`／`TOOL_DENY`／`L5`／`C2_GATE`／`TOOL_AGING` + 7 个 tmp 目录键） | 手写 `delenv`/`setenv`，每条后面挂着"实测 N 条红"的注释 |
| `evals/changedetect/env_baseline.py::PINS` | 3 键（`TOOL_DENY`／`TOOL_SURFACE`／`T_NOW_SKIP`） | 手写 |
| 宿主/GUI 实际注入面 | 本机实测 14 个 `XEYO_*` | 无登记 |

两份名单交集只有 `XEYO_TOOL_DENY` 一个键（#10）。因此每出现一个新键就以"某天 N 条红"的形式复发——`XEYO_WSC_SOFT_WATERMARK` 正是这种新键。

二级根因：现名单按"开关族"（`=0`/`=1`）建模，而 `SOFT_WATERMARK`／`COMPACT_RATIO` 是**参数族**（数值），补丁式维护天然抓不到。

## 三、修法：一条规则

> **R：测试进程的 `XEYO_*` 只有一个权威来源；任何键的出现都必须过门。**

### R1 单一权威名单（新模块 `python/tests/_xeyo_env_policy.py`）

条目三段式 `(name, 处置, 原因)`，处置 ∈ `{drop, force_value, pin_tmp, allow}`。

初稿不由人手写：新增只读脚本 `python/scripts/snapshot_host_xeyo_env.py`，从
`.xeyo/settings.json` + 运行中服务进程读出宿主真实注入面，生成清单草稿；
人只做"这条该 drop / force / 还是 allow"的分类。

### R2 conftest 从 R1 派生

删掉 conftest 里 12 处手写补丁，改为遍历名单统一 `drop`/`force`/`pin_tmp`。
**语义与现状等价**（现状 12 键原样进名单），只是来源唯一化。
`_restore_os_environ`（逐用例 `os.environ` 快照）**保留不动**——它管的是另一半：被测代码自己写 env 的传染。

### R3 漂移守卫（这条才是"结构上不再发生"）

新增 `python/tests/test_xeyo_env_policy_is_complete.py`：

1. 扫描 `python/**/*.py` 的 `XEYO_[A-Z_]+` 字面量与读取点 ⇒ 键集合 `K_src`
   （注释/docstring 剥除复用 `evals/changedetect/compliance.py` 已有的 ast 做法，不新写一套，避免假阳）；
2. 采集宿主注入面 `K_host`（同 R1 快照）；
3. 断言 `K_src ∪ K_host ⊆ 名单`，否则红并逐个打印未登记键。

效果：新键一出现就红在"名单缺登记"，而不是三周后红在远端 11 条测试上。
`env_baseline.PINS` 一并改为从 R1 派生 ⇒ 消掉"两份名单"（#10）。

## 四、验收（必须能反证）

1. **同集同果**：13 个目标用例在"宿主原样"与"清空后"两种 env 下结果一致（当前是 12R/62P vs 74P，即验收起点）。
2. **门有牙齿**：故意 `setenv XEYO_FOO_BAR=1` ⇒ R3 必须红；从名单删一个已登记键 ⇒ R3 必须红。
3. **不越界**：改动文件限于 `python/tests/**`、`python/scripts/**`、`evals/changedetect/env_baseline.py`；`system_prompt`／冻结前缀零改动 ⇒ 无基线重钉。
4. **不误伤**：`XEYO_HOME`／`XEYO_PYTHON_ROOT`／`XEYO_PORT_FILE` 等路径类键属 `allow`/`pin_tmp`，不得被一刀切清掉（清掉会让测试回落到真实主目录，实测过污染：审计账 34 条、指标账 2,350 行）。

## 五、不做的事

- **不做"全清 `XEYO_*`"**：路径解析类键是输入面，全清会改测试语义。
- **不改产品**：`XEYO_WSC_SOFT_WATERMARK` 是合法产品参数（软水位），产品侧无需动。
- **不动冻结前缀**：本方案不产生基线变更。

## 六、待你裁的一格

`XEYO_REWIND_ENABLED`／`XEYO_MAX_TOOL_CALLING`／`XEYO_L5=project` 今天**未致红**，形态与两键同类。选择：

- (a) 一并登记为 `drop`（更干净，但可能掩盖某些用例的真实需求）；
- (b) 只登记实测致红的两键，其余交给 R3 在下次出现时抓（推荐：让门暴露，而不是预言）。
