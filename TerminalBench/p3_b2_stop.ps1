# 批 2 硬停看门狗：13:58 后若批 2 仍在跑则停止（防止闯入高峰期）。
$ErrorActionPreference = 'SilentlyContinue'
$log = 'D:\lea\XenYon code\TerminalBench\logs\p3_b2stop.log'
Set-Content -Path $log -Value "b2-stop start $(Get-Date -Format HH:mm:ss)"

while ($true) {
    $hm = Get-Date -Format HH:mm
    if ($hm -ge '13:58') {
        Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'p3_batch2' } | ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            Add-Content -Path $log -Value "$(Get-Date -Format HH:mm:ss) KILLED $($_.Name) pid=$($_.ProcessId)"
        }
        Add-Content -Path $log -Value "$(Get-Date -Format HH:mm:ss) batch2 stopped for peak window, exit"
        exit 0
    }
    Start-Sleep -Seconds 20
}
