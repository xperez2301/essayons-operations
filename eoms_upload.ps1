param(
    [Parameter(Mandatory=$true)][string]$EomsUrl,
    [Parameter(Mandatory=$true)][string]$Token,
    [Parameter(Mandatory=$true)][string]$Folder,
    [string]$StoresJson = "C:\GitHub\essayons-operations\data\stores.json"
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http

# Gather PDFs/spreadsheets to upload
$files = Get-ChildItem -LiteralPath $Folder -File | Where-Object { $_.Extension.ToLower() -in @(".pdf",".xlsx",".csv") }
if (-not $files) { Write-Host "No files found in $Folder"; exit 1 }

# Option C: build bol_data.json (BOL -> due date, contact) from local stores.json
$sidecar = $null
if (Test-Path -LiteralPath $StoresJson) {
    try {
        $stores = Get-Content -LiteralPath $StoresJson -Raw | ConvertFrom-Json
        $map = @{}
        foreach ($s in $stores) {
            $bol = "$($s.bol)".Trim()
            if ($bol) {
                $map[$bol] = @{
                    due_date      = "$($s.due_date)"
                    assigned_date = "$($s.assigned_date)"
                    contact       = "$($s.contact)"
                    contact_phone = "$($s.contact_phone)"
                    contact_email = "$($s.contact_email)"
                }
            }
        }
        $sidecar = Join-Path $Folder "bol_data.json"
        ($map | ConvertTo-Json -Depth 5) | Set-Content -LiteralPath $sidecar -Encoding UTF8
        Write-Host "Built bol_data.json with $($map.Count) BOL record(s)"
    } catch {
        Write-Host "Could not build bol_data.json: $($_.Exception.Message)"
    }
}

$endpoint = $EomsUrl.TrimEnd("/") + "/api/local-rms/import"
$client = New-Object System.Net.Http.HttpClient
$client.Timeout = [TimeSpan]::FromMinutes(15)
$client.DefaultRequestHeaders.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", $Token)
$content = New-Object System.Net.Http.MultipartFormDataContent
$streams = @()
try {
    foreach ($f in $files) {
        $s = [System.IO.File]::OpenRead($f.FullName); $streams += $s
        $fc = New-Object System.Net.Http.StreamContent($s)
        $fc.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("application/octet-stream")
        $content.Add($fc, "rms_file", $f.Name)
        Write-Host "Queued $($f.Name)"
    }
    if ($sidecar -and (Test-Path -LiteralPath $sidecar)) {
        $ss = [System.IO.File]::OpenRead($sidecar); $streams += $ss
        $sc = New-Object System.Net.Http.StreamContent($ss)
        $sc.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("application/json")
        $content.Add($sc, "rms_file", "bol_data.json")
        Write-Host "Queued bol_data.json (due dates + contacts)"
    }
    Write-Host "Uploading to $endpoint"
    $resp = $client.PostAsync($endpoint, $content).Result
    $body = $resp.Content.ReadAsStringAsync().Result
    Write-Host "HTTP $([int]$resp.StatusCode)"
    Write-Host $body
} finally {
    foreach ($s in $streams) { $s.Dispose() }
    $content.Dispose(); $client.Dispose()
}
