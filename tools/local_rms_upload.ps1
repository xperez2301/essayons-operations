param(
    [string]$EomsUrl = $env:AZURE_EOMS_URL,
    [string]$Token = $env:LOCAL_RMS_IMPORT_TOKEN,
    [string]$LocalEomsUrl = "http://127.0.0.1:5000",
    [string[]]$Folders = @("bol_files\Imported", "bol_files\Need_Review", "uploads"),
    [int]$MaxAgeMinutes = 360,
    [switch]$SkipAutoGrab,
    [string]$LogPath = "diagnostics\local_rms_upload.log"
)

$ErrorActionPreference = "Stop"

function Write-WorkerLog {
    param([string]$Message)
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Host $line
    $dir = Split-Path -Parent $LogPath
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    Add-Content -LiteralPath $LogPath -Value $line
}

function Read-DotEnv {
    param([string]$Path = ".env")
    if (-not (Test-Path -LiteralPath $Path)) { return }
    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
        $name, $value = $line.Split("=", 2)
        $name = $name.Trim()
        $value = $value.Trim().Trim('"').Trim("'")
        if ($name -and -not [Environment]::GetEnvironmentVariable($name, "Process")) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

function Invoke-LocalAutoGrab {
    param([string]$BaseUrl)
    $endpoint = $BaseUrl.TrimEnd("/") + "/api/rms/auto-grab-bols"
    Write-WorkerLog "Starting local RMS Auto Grab through $endpoint"
    try {
        $response = Invoke-RestMethod -Method Post -Uri $endpoint -ContentType "application/json" -Body '{"max_bols":0}' -TimeoutSec 3600
        $result = $response.result
        $message = if ($result -and $result.message) { $result.message } else { ($response | ConvertTo-Json -Compress -Depth 6) }
        Write-WorkerLog "Local Auto Grab finished: $message"
    }
    catch {
        Write-WorkerLog "Local Auto Grab failed: $($_.Exception.Message)"
        throw
    }
}

function Get-RmsFiles {
    param([string[]]$FolderList, [int]$AgeMinutes)
    $cutoff = (Get-Date).AddMinutes(-1 * [Math]::Abs($AgeMinutes))
    $results = @()
    foreach ($folder in $FolderList) {
        if (-not (Test-Path -LiteralPath $folder)) { continue }
        $results += Get-ChildItem -LiteralPath $folder -Recurse -File |
            Where-Object { $_.Extension.ToLowerInvariant() -in @(".pdf", ".xlsx", ".csv") -and $_.LastWriteTime -ge $cutoff }
    }
    $results | Sort-Object FullName -Unique
}

function Send-RmsFiles {
    param([string]$BaseUrl, [string]$ImportToken, [System.IO.FileInfo[]]$Files)
    if (-not $Files -or $Files.Count -eq 0) {
        Write-WorkerLog "No new PDF, XLSX, or CSV files found to upload."
        return
    }

    $endpoint = $BaseUrl.TrimEnd("/") + "/api/local-rms/import"
    Add-Type -AssemblyName System.Net.Http
    $client = [System.Net.Http.HttpClient]::new()
    $client.Timeout = [TimeSpan]::FromMinutes(30)
    $client.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $ImportToken)
    $client.DefaultRequestHeaders.Add("X-Local-RMS-Token", $ImportToken)
    $client.DefaultRequestHeaders.Add("X-EOMS-Worker", $env:COMPUTERNAME)

    $content = [System.Net.Http.MultipartFormDataContent]::new()
    $streams = @()
    try {
        foreach ($file in $Files) {
            $stream = [System.IO.File]::OpenRead($file.FullName)
            $streams += $stream
            $fileContent = [System.Net.Http.StreamContent]::new($stream)
            $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("application/octet-stream")
            $content.Add($fileContent, "rms_file", $file.Name)
            Write-WorkerLog "Queued $($file.FullName)"
        }

        Write-WorkerLog "Uploading $($Files.Count) file(s) to $endpoint"
        $response = $client.PostAsync($endpoint, $content).Result
        $body = $response.Content.ReadAsStringAsync().Result
        if (-not $response.IsSuccessStatusCode) {
            Write-WorkerLog "Upload failed: HTTP $([int]$response.StatusCode) $body"
            exit 1
        }
        Write-WorkerLog "Upload complete: $body"
    }
    finally {
        foreach ($stream in $streams) { $stream.Dispose() }
        $content.Dispose()
        $client.Dispose()
    }
}

Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
Read-DotEnv

if (-not $EomsUrl) { $EomsUrl = $env:AZURE_EOMS_URL }
if (-not $Token) { $Token = $env:LOCAL_RMS_IMPORT_TOKEN }
if (-not $EomsUrl) { throw "AZURE_EOMS_URL or -EomsUrl is required." }
if (-not $Token) { throw "LOCAL_RMS_IMPORT_TOKEN or -Token is required." }

Write-WorkerLog "Local RMS sync worker started."
if (-not $SkipAutoGrab) {
    Invoke-LocalAutoGrab -BaseUrl $LocalEomsUrl
}
$files = @(Get-RmsFiles -FolderList $Folders -AgeMinutes $MaxAgeMinutes)
Send-RmsFiles -BaseUrl $EomsUrl -ImportToken $Token -Files $files
Write-WorkerLog "Local RMS sync worker finished."