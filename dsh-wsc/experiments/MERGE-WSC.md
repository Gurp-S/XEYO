# WSC 并入主链路（desktop profile）

时间：2026-11-04 02:5x
结论：WSC 已成为 `desktop` profile 的压缩后端，参数取质量/成本验证里最好的 **k2 臂**。

## 改了什么

`C:\Users\48522\.dsh\profiles\desktop\cordis.patch.yml`：

1. `wsc-config`：`mode: off` → `mode: active`，并写入 k2 参数。
2. 新增 `compaction-basic: disabled: true`。
3. 新增 `insert: wsc-engine (@xeyo/dsh-wsc/engine)`。

k2 臂用 `capacityMode: tokens / capacityTokens: 28235`，那是 echo 夹具 65,536 窗口下的绝对值
（= 43.1% × 65536，force 0.85 → 36.6% 触发）。主链路窗口是 1,000,000，所以改成
`capacityMode: ratio / capacityPercent: 43`，保持同一比例，其余比例参数原样搬过来：
`warnRatio 0.8`、`forceRatio 0.85`、`retainRatio 0.136`、`minReclaimRatio 0`、
`selection: selective`、`controlItemCap 4000`、`selectionMaxTokens 16384`、
`payloadWorkingset: true / v2 / files 6 / itemCap 700 / sectionCap 2500`、`denoise: true`。

## 两个踩到的坑

**1. 包自带补丁打不上。** `@xeyo/dsh-wsc` 的 `cordis.patch.yml` 去 patch `preset-cordis`，
desktop 树里没有这个花名册条目，dsh 报 `patch: entry "preset-cordis" not found`，
于是 `wsc-engine` 根本没挂上、`compaction-basic` 仍是后端 —— 只把 `mode` 改成 `active`
只会启用宿主面配置服务，不会换掉压缩后端。所以按 k 臂的做法在 profile 层替换：
关 `compaction-basic`、插 `wsc-engine`。

**2. 依赖解析失败。** desktop 用 `link:D:/lea/XenYon code/dsh-wsc` 装插件，Node 按真实路径
解析，插件找不到 `@deepseek-ai/schemastery`、`@deepseek-ai/dsh-compaction-basic`，profile 直接
起不来。实验臂用的是 `file:./xeyo-dsh-wsc-0.1.0.tgz`（pnpm 物化到 profile 内，peer 能解析）。
在 desktop 上 `pnpm install` 需要删除 node_modules（`ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY`），
会动到正在运行的 GUI，所以改用零风险方案：
`D:\lea\XenYon code\dsh-wsc\node_modules\@deepseek-ai` 建 junction 指向
`E:\nodejs\node_modules\@deepseek-ai\dsh\node_modules\@deepseek-ai`。
`package.json` 仍是 `link:`，与已安装状态一致。

> 长期正确做法：把插件打成 tgz 安装（`CI=true dsh plugin --profile desktop install`），
> 去掉这条 junction。junction 只是本机让 link 安装能解析 peer 的补丁。

## 验证

- `dsh --profile desktop --dump-config`：`compaction-basic` 两处均 `disabled: true`，
  `wsc-engine` 在树里，`wsc-config` 为 `mode: active / capacityPercent: 43 / forceRatio: 0.85 /
  payloadWorkingsetVersion: 2`。
- 另起端口实跑：`dsh --profile desktop --no-open --port 10499` 启动成功，`GET /` 返回 200。
- 未做的是"真的触发一次压缩"：capacity 43% × 1M = 430k，短任务不会触发；
  要验就得烧几十万 token，等下次真实长会话自然验证（会话里 `compaction/summary` 的
  provider 字段即可确认后端）。

## 回退

把 `cordis.patch.yml` 里 `mode: active` 改回 `mode: off`，并删掉 `compaction-basic: disabled`
与 `wsc-engine` 的 insert 两段，即恢复原生压缩。

## 顺带测到的 WSM 真实质量（第一项待办）

脚本 `experiments/tools/wsm-quality.mjs`：统计"压缩后重读本会话已读过的文件"的比例，
以及工作集对这些重读的覆盖。

| 臂 | 读 | 其中重读 | 重读占比 | 工作集覆盖重读 |
|---|---|---|---|---|
| j（无工作集） | 405 | 263 | 65% | 0 |
| k（工作集 v2） | 275 | 200 | 73% | 16（8%） |
| k2 | 70 | 26 | 37% | 0 |

全量：789 次读里 489 次是重读（62%），工作集只覆盖其中 16 次（3%）。
**工作集 v2 目前没有抑制重读**——6 个文件 / 700 字节条目的容量太小，且列出的多是
压缩前读过的文件，重读时往往已经不在集合里。这是 k2 之后最值得调的旋钮
（`payloadWorkingsetFiles`、`payloadWorkingsetItemCap`），但先不动已并入的配置。
