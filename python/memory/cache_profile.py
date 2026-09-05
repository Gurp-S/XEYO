"""多厂商 KV 画像：三价、TTL、块粒度、存活率。

设计见 docs/10-完整记忆体系.md §4.7 v6.1。本文件仅占位，不含实现。

字段（实现时）：
  p_u, p_r, p_w, p_o     # 未缓存输入 U / 缓存读 H / 缓存写 / 输出
  H, U, W_phys           # 互斥 H+U+W_phys=|X|；p_w=0 只表示写入免费，不表示 W_phys=0
  C_t                    # 与 S 正交的缓存状态；rho = rho_hat(C)
  G_beta                 # 1[|M|>beta|T|]，beta=8；不进 F_R / 不进 J
  hat_H clip             # clip(rho * L_blk, 0, |X^a|)
  empty M                # Q=1, D=0, C1/C2 不进可行集
  J tie-break            # keep > C1 > C2
  C_action               # 只在 h=0；之后按正常策略 pi，不锁死在 a
  C_biz(X; S, C)         # C 只通过 hat_H 进入 H
  a_hard                 # argmin D；|D1-D2|<=eps_D 则 C1（数值 epsilon）
  I = I_M                # 只评价 M；segments 不重叠且 sum v_i = |M|
  L(S_a) = |X^a|         # 与 API prompt_tokens 对齐
  S_a = Apply(a, S0)     # 独立分支，禁止改写 S0
  rho_hat                # 预测参数；P0 = s * alpha_hit；用 H_obs 校准
  tau_switch             # 0.85；HardTop 绕过；a_hard = argmin D
  a_R / a_vote / a*      # 每层 argmin J → 有多数跟多数 / 无多数 keep；票数不进 J
  Margin_J(R)            # 只记日志，不加 η 闸
  r_stub, r_summary      # 先验表 0.25 / 0.6，不是超参 gamma

DeepSeek 对账：无独立 write 档 → 发票 W_phys=0、未命中进 U；物理 cache fill 另记。
DeepSeek V4 官方价（2026-08-17 00:00 北京时间起，元 / 百万 token）：
  高峰 09:00–12:00、14:00–18:00；空闲 = 高峰 × 1/2；p_w = 0。
  flash 空闲 命中 0.05 / 未命中 1.5 / 输出 4.5；高峰 0.10 / 3.0 / 9.0
  pro   空闲 命中 0.15 / 未命中 4.5 / 输出 13.5；高峰 0.30 / 9.0 / 27.0
"""
