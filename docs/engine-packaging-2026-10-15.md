# XEYO 独立引擎打包与运行服务解耦

这一阶段让 XEYO 可以按引擎依赖独立安装，并移除 `engine` 对 `server` 的直接导入。GUI、TUI、CLI 使用同一套核心；产品入口显式注入后台任务和输入队列服务。

## 安装方式

在仓库根目录执行：

```powershell
# 嵌入式引擎
python -m pip install ./python

# 包含 CLI、serve 及原有产品 Python 依赖
python -m pip install "./python[product]"

# 只需要 HTTP 服务依赖
python -m pip install "./python[server]"

# CLI 含 serve 子命令，因此 cli extra 同时安装服务端依赖
python -m pip install "./python[cli]"
```

基础依赖为 httpx、pydantic、tokenizers。pydantic 是插件清单使用的直接依赖，不能依赖 FastAPI 顺带安装它。桌面启动脚本继续使用 `python/requirements.txt`，无需更换启动方式。

仍采用一个 `xeyo` 发行包。产品模块代码保留在 wheel 中，extras 控制可选依赖；本阶段没有迁移所有内部包到 `src/xeyo/`，也没有引入两个包含重叠文件的发行包。旧的 `engine.*` 导入保持兼容，新增 `xeyo` 公共入口。

```python
import asyncio
from xeyo import build_default_engine

async def main():
    engine = build_default_engine(cwd=".", model_backend="fake")
    async for event in engine.submit("hello"):
        if event.type == "final":
            print(event.text)

asyncio.run(main())
```

`fake` 仅用于本地验证。嵌入真实模型时仍需配置供应商连接、权限及工作区。无产品依赖时不承诺桌面专用工具或服务端后台任务工具可用。

## 依赖与状态归属

结构性根因有两处：包发现清单遗漏实际引用模块；引擎通过服务端单例查找宿主服务，导致核心运行与产品装配混在一起。

| 边界 | 当前规则 |
| --- | --- |
| `engine/runtime_services.py` | 定义 `RuntimeServices`、后台任务快照和边界输入队列协议；每个引擎实例显式持有依赖 |
| `server/engine_services.py` | 适配产品现有注册表；不复制注册表状态，保留原有所有者和重置机制 |
| `server/session_pool.py` 与 `cli/chat_cmd.py` | 创建产品引擎时注入适配器 |
| `engine/query_engine.py` | 未注入服务时返回空宿主任务视图，不再隐式导入服务端 |
| `engine/query_loop.py` | 只新增边界 inbox 参数；投递时机、队列开关和工具批次执行顺序保持不变 |
| `engine/turn_runner.py` | 未绑定时明确报错；由服务端装配入口绑定 pool，核心不查找全局服务端 pool |
| `common/process_identity.py` 与 `common/version.py` | 进程存活检查与版本事实由标准库公共模块提供；旧端口文件接口再导出 |

从外部直接创建 `QueryEngine`、调用 `build_default_engine` 或 `query_loop` 的嵌入方，如需宿主任务和队列，需要传入对应服务。正常 GUI、TUI、CLI 产品入口已经完成接线。

写入、授权、WSC 发布和恢复机制没有重新实现。模型可见文本没有新增编排指令。`engine` 禁止导入 `server`、`cli`、FastAPI 和 uvicorn 的规则由定向测试约束；其它产品工具中的依赖属于后续适配器迁移范围。

## 旁路和 A/B 验证

变更先在当前工作区的隔离副本中实施。基线包含当时已有的未提交修改，候选只叠加本阶段改动。通过后才按文件内容比较合回；未做混合工作区提交。

实际构建的基线 wheel 缺少 coord、lsp、sidecar，包含 evals；候选补齐前三者，移除评测和测试分发内容，并保留 tokenizer 资源。基础直接依赖从 7 项变为 3 项，原有产品依赖由 extras 保留。

文本、工具调用、边界输入和中断共 4 个配对场景、5 次假模型采样：归一化临时工作目录、随机身份和 `time_now` 实测时间后，请求消息、工具表、输出、状态、宿主任务视图及恢复事实相同。相邻文本增量合并比较，同时保留分片数。两个规范化证据文件的 SHA-256 均为 `c4ac371d5c3d9af806585b738f6f8e967d2decfed2127772a9582ba8735f889b`。

| 验证面 | 结果及边界 |
| --- | --- |
| 原有 Python 定向套件 | A/B 各 186 项；初次各 184 通过、2 失败。补齐隔离副本的仓库标记后，该 CLI 路径用例在两侧均通过；剩余 1 项是基线已有的后台输出格式断言 |
| 新增核心与产品接线契约 | 11 项通过；覆盖实例隔离、队列投递、产品入口注入、异常降级和反向导入检查 |
| 合回后的 Python 定向套件 | 197 项中 196 通过、1 项上述基线失败；无新增失败 |
| GUI | 3 个流协议测试文件、47 项通过；类型检查通过 |
| TUI | 回合身份、回执、缺口和输入队列共 14 项通过；类型检查通过 |
| 干净 wheel 安装 | 仓库外加载；阻止产品模块导入时，文本与工具回合、checkpoint 写入及恢复比较通过 |
| 安装后的产品入口 | `xeyo` 与 `python -m cli` 命令入口、CLI 帮助与假模型聊天、HTTP 健康检查、SSE 正文及 DONE 帧通过 |

基线遗留的 `test_job_tools_with_fake_registry` 假定状态行必须是输出最后一行；现有执行事实功能会在后面追加 activity 行。A/B 中均为同一断言失败，本阶段保留该测试及工具实现，避免覆盖并行任务的行为约定。它不是本次新增失败。

这些结果覆盖本轮依赖变更的入口与执行边界，不等同于全量 GUI 交互、所有工具、真实供应商或 Windows 安装器回归。

机器可读结果与本轮文件归属见 [验证记录](engine-packaging-2026-10-15.json)。本地原始 A/B 日志、基线快照和合回前文件备份保存在被忽略的 `python/.tmp-engine-decoupling-20261015/`。文件写入前逐一比较基线内容；没有执行暂存、提交或工作区重置。后续对话可以继续修改 WSC/Agent：本轮在 `query_engine.py`、`query_loop.py` 仅接入宿主服务参数，其余算法归属保持原状。

运行时版本定义移到 `common/version.py`，`cli.__version__` 与 `server.portfile.engine_version` 继续兼容导出。未来发版时需同步该定义与 `pyproject.toml`；安装检查会检测二者是否一致。

## 持续验证与后续迁移

```powershell
python -m pip install build
python -m build python --wheel --outdir dist/engine-contract
python scripts/verify_engine_wheel.py dist/engine-contract/xeyo-1.11.0-py3-none-any.whl --product
```

新增 `engine-package.yml` 在 Windows 与 Linux 构建 wheel，再建立全新虚拟环境验证核心与产品 extras。验证脚本使用临时工作区、假模型和导入隔离，不调用真实供应商。

本轮实际执行的是 Windows 本地检查；新增的远程 CI 尚未运行。

后续可以逐包迁移到正式 `xeyo` 命名空间，继续抽离权限、Git、后台任务与桌面工具的宿主依赖。应先保持这些安装和运行契约，再拆分发行包；这轮不改变 WSC 算法、Agent 协作机制和前端状态实现。
