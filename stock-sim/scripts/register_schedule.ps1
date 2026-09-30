# stock-sim 대시보드 자동 갱신 작업을 Windows 작업 스케줄러에 등록한다.
# backtest.end: auto 는 "어제"까지를 구간으로 잡으므로, 화~토 아침에 돌면 직전 거래일 종가까지 반영된다.
# 열어 둔 dashboard.html 은 <meta http-equiv="refresh"> 로 5분마다 새 파일을 다시 읽는다.
# 사용: powershell -ExecutionPolicy Bypass -File scripts\register_schedule.ps1 [-Time 07:30] [-Unregister]
param(
    [string]$Time = "07:30",
    [string]$TaskName = "stock-sim-dashboard",
    [switch]$Unregister
)

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "작업 삭제: $TaskName"
    return
}

$root = Split-Path -Parent $PSScriptRoot           # stock-sim/
$uv = (Get-Command uv -ErrorAction Stop).Source
$logDir = Join-Path $root "data\logs"               # data/ 는 .gitignore 대상
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir "scheduled_run.log"

# 키는 로그에 남지 않는다(kis_client 가 마스킹). 실행 로그만 덧붙인다.
$cmd = "Set-Location -LiteralPath '$root'; & '$uv' run --directory src python -m stock_sim run --config ../config.yaml *>> '$log'"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -Command `"$cmd`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Tuesday, Wednesday, Thursday, Friday, Saturday -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "작업 등록: $TaskName (화~토 $Time), 로그: $log"
