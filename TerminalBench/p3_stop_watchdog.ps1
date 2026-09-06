# 高峰期看门狗：13:55 硬停所有 p3_batch3 进程；余额 <2 元也停；14:05 后退出。
$ErrorActionPreference = 'SilentlyContinue'
$key = (Get-Content 'D:\lea\XenYon code\api_key.txt' -Raw).Trim()
$log = 'D:\lea\XenYon code\TerminalBench\logs\p3_stop.log'
Set-Content -Path $log -Value "stop-watchdog start $(Get-Date -Format HH:mm:ss)"

function Stop-Batch3 {
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'p3_batch3' } | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Add-Content -Path $log -Value "$(Get-Date -Format HH:mm:ss) KILLED $($_.Name) pid=$($_.ProcessId)"
    }
}

function Get-Balance {
    try {
        $r = Invoke-RestMethod -Uri 'https://api.deepseek.com/user/balance' -Headers @{ Authorization = "Bearer $key" } -TimeoutSec 15
        return [double]($r.balance_infos[0].total_balance)
    } catch { return -1.0 }
}

while ($true) {
    $hm = Get-Date -Format HH:mm
    # 每 5 分钟查一次余额（逢 x0/x5 分）
    if ($hm -match '^[0-9]*[05]:[0-9]{2}$' -or $hm -match ':[0-9]5$') {
        $b = Get-Balance
        Add-Content -Path $log -Value "$(Get-Date -Format HH:mm:ss) balance=$b"
        if ($b -ge 0 -and $b -lt 2) {
            Add-Content -Path $log -Value "$(Get-Date -Format HH:mm:ss) LOW BALANCE -> stop batch3"
            Stop-Batch3
        }
    }
    if ($hm -ge '13:54' -and $hm -le '14:05') {
        $running = (Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'p3_batch3' } | Measure-Object).Count
        if ($running -gt 0) {
            Add-Content -Path $log -Value "$(Get-Date -Format HH:mm:ss) peak window -> stop batch3"
            Stop-Batch3
        }
    }
    if ($hm -gt '14:04') {
        Add-Content -Path $log -Value "$(Get-Date -Format HH:mm:ss) past 14:04, exit"
        exit 0
    }
    Start-Sleep -Seconds 20
}
