"""本地模型（llama.cpp）子系统。

对外只暴露四件事：登记表（``catalog``）、配置（``config``）、授权位（``gate``）、
进程管理（``manager``）。设置面板与 HTTP 路由都只经由这四者，不直接碰文件与进程。

模块划分与职责边界：

| 模块       | 唯一职责                                             |
| ---------- | ---------------------------------------------------- |
| `catalog`  | 有哪些模型、权重叫什么、从哪来（机器事实的注册表）   |
| `config`   | 用户选了哪支、端口/上下文等参数落盘与合并            |
| `gate`     | `provider="local"` 是否被授权（产品开关 or 环境变量）|
| `manager`  | 单实例 llama-server 的起停/切换/健康/兜底清理        |

多实例调度**不做**，原因写在 `manager` 模块头部（显存装不下两支常驻副本）。
"""

from __future__ import annotations

from localmodels.gate import local_model_allowed

__all__ = ["local_model_allowed"]
