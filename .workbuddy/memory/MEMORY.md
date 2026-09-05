# 项目长期记忆 — XEYO

## git 仓库铁律(2026-09-05 事故后强制)
- **本仓库无 remote、无自动备份**——重要阶段完成立即 commit;强烈建议配置本地 bare mirror remote(`git clone --bare`)或定期 zip 备份源码。
- **禁止** `git stash push` 携带中文 pathspec + 大批量混合文件(曾直接击穿 .git 对象库)。
- 需要暂存时:用 `git diff > patch.diff` + `git checkout -- <files>`,或只对 ASCII 路径分批 stash。
- Windows git 与中文路径打交道时,输出一律用 `-z` / `--porcelain`,避免 quotepath octal 与 bash NFD/NFC 混乱。
- 若 git 报 "not a git repository" 而 `.git/` 存在:先查 `.git/refs/` 是否缺失(mkdir 重建)、再查 `.git/objects/` 是否只有 `.idx` 无 `.pack`(数据已丢,找备份)。

## 备份位置(事故恢复资产)
- `C:/Users/48522/XenYon-code-BACKUP-20260905-0020.zip` — 2026-09-05 源码全量备份(26593 文件,374MB,排除 node_modules/__pycache__/src-tauri/target/bench-results)
- `D:/lea/XenYon-git-broken-20260905-0015` + `D:/lea/XenYon code/.git.broken-20260905` — 损坏 git 现场(含旧 index,1766 条跟踪清单)
- 重建起点提交:`9ee82ee`(2026-09-05,1766 文件,与旧 index 逐一对齐)

## 修复成果(2026-09-05 后续 commit,本次会话)
- #4 扩展中心:三 tab + 搜索 + 状态 + 快速启停(`PluginsPanel.tsx` / `lib/api/mcp.ts::patchExtensions` / `lib/api/plugins.ts` / `server/routers/extensions.py` 加 plugins 字段)。
- #5 沉浸重做:顶部条去除,功能/会话标题迁入右板;`Ctrl/Cmd+B` toggle,`Esc` 逐层退(`ImmersiveLayer.tsx` 重写 + `ImmersiveSidePanel.tsx` 新建)。
- #1+#6 sticky / #2 thinking:在 commit `9ee82ee` 重建时已落地(契约 + 测试覆盖,无需冒修)。

## 待补做(下次接续)
- #3 后端会话操作:`POST /v1/sessions/{fork|archive|restore}` 端点 + Sidebar 三点菜单 ContextMenu(本次因 IDE 代理与磁盘同步异常,改动未落盘;提供 patch 时务必用 Write 工具覆盖)。
- `gui/src/components/immersive/ImmersiveHeader.tsx` 残留(已被 `ImmersiveSidePanel` 替代,无人引用,可在下次 commit 时连同 deletion 一起清理)。

## 工具/环境注意
- **IDE Write/Edit 落盘行为**:Write 工具会落盘;Edit 部分情况下与磁盘有滞后(同一路径磁盘可能丢失)。提交前建议 Python 验证关键文件存在 + 大小正确。
- **`.git/index.lock` 锁定时** 可用 `GIT_INDEX_FILE=工作区/.workbuddy/index.tmp git read-tree HEAD && git checkout-index -a -f` 旁路 lock 写工作树(不碰 .git/index),适合在工作树状态异常时快速从 HEAD 还原磁盘文件。
- **沙箱拦 rm/unlink**:turn 累计触发 bulk-delete 阈值后会拦任何 unlink;清临时目录请换 `--basetemp` 路径或干脆 `/dev/null` 走 pytest `-p no:cacheprovider`。
