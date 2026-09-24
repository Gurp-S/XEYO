"""受控 A/B 实验（设计 docs/xeyo-diagnostics-design-2026-09-24.md §7-§9）。

四个模式各自独立：A0 静态差异（零模型调用）、A1 同检查点单请求配对、A2 隔离
环境真实任务配对，外加实验级持久预留账本与 runner。本包**不**向模型可见文本
写任何东西：实验身份只进 manifest / results / report。
"""
