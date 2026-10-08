# 批次54：恢复模型自决压缩主流程

用户现场反馈：昨天占用约50%，今天只有4%；核查后用户明确要求“改回去”。

## 现场证据

昨天 `sess_muzjl9ob_p8woul` 的厂商末次prompt_tokens为470332，声明容量1M，无历史折叠。今天 `sess_muzpwhpu_loivz9` 厂商末次prompt_tokens为36599，同样1M，实际占用3.66%。今天源中无Compact调用，但折叠账有7次：size_gate_fold及worth_fold，均非容量强压。

01:06:18尺寸门折叠前后实际输入238706→18918；01:50:06经济门99171→22030；01:50:36再折叠23285→18375。4%主要由真实提前折叠造成，不能归因于显示分母或只是去噪。

提交49e8dc6（00:55:42）将wsc_timing.enabled改为显式环境开关、默认关闭。正常.env没有MODEL_TIMING设置；旧尺寸/经济门重新进入普通主链。任务请求分层与失败事实也被改回显式旁路，使旧目标/旧决定重新出现。

## 恢复及改动文件

新增单一 `python/memory/wsc_main_policy.py` 作为已授权主策略来源，旧实验键缺省或0均无法禁用。时机仍完全按此前用户四项：模型Compact拥有普通折叠；完整当前请求80%一次事实通知、85%强压；异步交接/严格落盘确认先于折叠。厂商计量标签等用户现有修改保留。

恢复接线：`python/memory/wsc_timing.py`、`python/memory/runtime.py`、`python/memory/wsc_execution_boundary.py`、`python/synaptic/receipt_render.py`、`python/synaptic/request_plane.py`、`python/synaptic/failure_facts.py`。`python/engine/env_switches.py`说明改为旧兼容键，不再描述默认关。

回归暴露回退新代同时展示旧C2原话和新交接，`python/memory/wsc_fallback_handoff.py::compose`统一为已提交状态存在时只发该交接及冷来源；无提交保持原兼容表示。只影响新压缩代，已有冻结头不改写，原始历史仍完整存档。

`python/tests/wsc/test_main_timing.py`增加缺省/0×native/回退四臂，长任务约240K估参不推进cursor/C1、不进入旧经济函数。`python/tests/wsc/test_request_timing_loop.py`旧未交接强压夹具接真实TodoWrite/持久化，保持最终schema压力前折叠、重测keep、一次主模型发送的原接受项。

本轮此前进行中的分页目录改造保留，仍未宣称它已全部验收：`wsc_handoff_catalog.py`、`wsc_handoff_generation.py`及其工具名单契约改动。恢复时机不依赖分页目录收益，后续继续独立验收。

## 测试与真实源离线重建

相关主时机、80/85精确边界、主动Compact、完整请求、容量交接、持久化故障、任务状态、多次fold和旧C2联合 **107 passed**。不等于全仓测试，部分初查失败来自被退回的旁路接线，全部原接受项保留并恢复通过。

`_wsc_out/restored-main-2026-10-09/report.json` 从今天实际转录及blob恢复构建新离线投影，原JSONL1226行，经原生MessageStore选择536条；完整DeepSeek发送形状+默认工具估参385975/1M，action=keep，无通知、游标0、原源及转录字节一致4/4。这是新未折叠重建的估参，不是厂商实际发射，也不是重写用户已有压缩头。

本轮API请求0，费用0。进程检查未发现当前Python/XEYO后端，代码需在下次后端启动时加载；未启动新服务、未修改或展开旧会话头。已折叠会话会从原头继续累积，显示不会凭空立刻回到50%。

整体goal仍开放：分页目录/交接输入预算、真实模型检索及复杂长任务连续性等保持TODO，不能以恢复时机结案全部WSC问题。
