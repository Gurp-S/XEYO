"""XEYO 统一扩展层：插件 = 打包 skill + MCP server 配置 + 可选提示。

一个插件(manifest) 能贡献 skills、MCP server 与 T_now 提示，作为三者之上的
统一发现/安装/生命周期单元（企业级，默认关闭，全部经权限与审计契约）。

红线：
- 插件 / skill 提示走 T_now 投影（``prompt.pre_llm_inject``），绝不进 system 左段。
- MCP 动态工具必须经 ``tools.tool_registry.ToolRegistry.run`` 的权限三态，
  默认 ``outbound_ask``，不得绕过。
- 同名 skill 默认禁止覆盖（workspace > home > plugin），防供应链混淆。
"""
