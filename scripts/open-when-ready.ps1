$ErrorActionPreference = "SilentlyContinue"

$AppUrl = "http://127.0.0.1:8000"
$InstanceUrl = "$AppUrl/api/instance"

for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
    $Instance = Invoke-RestMethod -Uri $InstanceUrl -Method Get -TimeoutSec 1
    if ($Instance.app_id -eq "benchmark-video-collector" -and $Instance.data_scope -eq "video") {
        Start-Process $AppUrl
        exit 0
    }
    Start-Sleep -Seconds 1
}

exit 1
