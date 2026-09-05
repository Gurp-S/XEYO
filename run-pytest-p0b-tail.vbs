' XEYO P0b 全量回归 · 全静默启动器（双击零窗口，杜绝任何闪黑框）。
' 通过 WScript (无控制台) + pythonw (无控制台) 启动 run_p0b_tail_batches.py --all。
' 进度/结果全部写日志文件：
'   logs\pytest-p0b-tail.summary.txt   （每批 exit + OVERALL）
'   logs\p0b-batchNN.log / .xml        （每批 pytest 输出 / JUnit）
'   logs\pytest-p0b-tail.done          （结束哨兵 done exit=<0|1>）
' 用已开的终端看进度（不新开窗）：
'   powershell "while(!(Test-Path 'logs\pytest-p0b-tail.done')){Get-Content 'logs\pytest-p0b-tail.summary.txt' -Tail 40; sleep 5}"
Option Explicit
Dim sh, fso, base, py
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = base
py = base & "\run_p0b_tail_batches.py"
' 0 = hidden window; False = do not wait. pythonw itself has no console either.
sh.Run "pythonw """ & py & """ --all", 0, False
WScript.Quit 0
