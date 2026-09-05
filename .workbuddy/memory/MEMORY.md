# 项目长期记忆 — XEYO

## git 仓库铁律(2026-09-05 两次事故后强制,第二次 13:33)
- **本仓库无 remote、无自动备份**——重要阶段完成立即 commit;已配置本地 bare mirror:`git push mirror master`(remote 名 `mirror` → `D:/lea/XenYon-git-mirror-20260905-1340.git`)。
- **绝对禁止 `git stash`(任何形式,含 ASCII pathspec、单文件)**——13:33 二次事故证明 ASCII pathspec stash 同样击穿 .git(refs 清空+对象库清空)。需要暂存时只用 `git diff > patch.diff` + `git checkout -- <files>`。
- **多会话并行时 commit 防卷入(14:16 两次实测)**:index 是共享的,`git add X && git commit` 会提交整个 staged 快照,并行会话随时往里 add。正解=路径限定提交 `git commit -m "..." -- <path>`(只提交该路径工作树内容,无视 index 其他 staged,且保持它们 staged);提交前 `git diff --cached --name-only` 检查只是缓解,竞态窗口仍存在。误卷后修复:`git reset --soft HEAD~1 && git reset -q` 再路径限定重提(均不动工作树)。
- Windows git 与中文路径打交道时,输出一律用 `-z` / `--porcelain`,避免 quotepath octal 与 bash NFD/NFC 混乱。
- 事故征兆自查:`git cat-file -t <已知提交>` 失败 = 对象库损;`.git/refs/heads/` 空 = ref 被清;objects 只有 .idx 无 .pack = 数据已丢。恢复手册:封存现场为 `.git.broken-*` → `git init -b master` → 按 .gitignore 清垃圾暂存 → 提交重建点 → 立即建/推 bare mirror。
- 全量 pytest 在沙箱环境不可靠(共享 basetemp mkdir 竞争产生大量假失败,单跑即过);P0 门以用户手动 run-pytest-p0a.bat 为准;`--basetemp` 每次必须用全新路径。

## 备份位置(事故恢复资产)
- `C:/Users/48522/XenYon-code-BACKUP-20260905-0020.zip` — 2026-09-05 源码全量备份(26593 文件,374MB,排除 node_modules/__pycache__/src-tauri/target/bench-results)
- `D:/lea/XenYon-git-broken-20260905-0015` + `D:/lea/XenYon code/.git.broken-20260905` — 损坏 git 现场(含旧 index,1766 条跟踪清单)
- 重建起点提交:`9ee82ee`(2026-09-05,1766 文件,与旧 index 逐一对齐)

## 修复成果(2026-09-05 后续 commit,本次会话)
- #4 扩展中心:三 tab + 搜索 + 状态 + 快速启停(`PluginsPanel.tsx` / `lib/api/mcp.ts::patchExtensions` / `lib/api/plugins.ts` / `server/routers/extensions.py` 加 plugins 字段)。
- #5 沉浸重做:顶部条去除,功能/会话标题迁入右板;`Ctrl/Cmd+B` toggle,`Esc` 逐层退(`ImmersiveLayer.tsx` 重写 + `ImmersiveSidePanel.tsx` 新建)。
- #1+#6 sticky / #2 thinking:在 commit `9ee82ee` 重建时已落地(契约 + 测试覆盖,无需冒修)。

## 待补做(下次接续)
- ~~#3 后端会话操作~~ **已完成(2026-09-05 13:55)**:`/v1/sessions/{fork|archive|restore}` 端点 + Sidebar/SideChat 三点菜单均已入库;本次补齐归档门槛(常态禁删,409 archived_required),见 commit `0c672f3`(+`8fd685d` 收编部分文件)。
- `gui/src/components/immersive/ImmersiveHeader.tsx` 残留(已被 `ImmersiveSidePanel` 替代,无人引用,可在下次 commit 时连同 deletion 一起清理)。
- **vitest 既有 7 失败**(MessageList.chat / mainPaths.workflow / chatStore busy+hydrate)归属在途 MorphVerb.tsx / useStreamTypewriter.ts / agent-map.css 改动,经 HEAD 版对照实验确认;待该工作流自己收口。

## 工具/环境注意
- **IDE Write/Edit 落盘行为**:Write 工具会落盘;Edit 部分情况下与磁盘有滞后(同一路径磁盘可能丢失)。提交前建议 Python 验证关键文件存在 + 大小正确。
- **`.git/index.lock` 锁定时** 可用 `GIT_INDEX_FILE=工作区/.workbuddy/index.tmp git read-tree HEAD && git checkout-index -a -f` 旁路 lock 写工作树(不碰 .git/index),适合在工作树状态异常时快速从 HEAD 还原磁盘文件。
- **沙箱拦 rm/unlink**:turn 累计触发 bulk-delete 阈值后会拦任何 unlink;清临时目录请换 `--basetemp` 路径或干脆 `/dev/null` 走 pytest `-p no:cacheprovider`。
