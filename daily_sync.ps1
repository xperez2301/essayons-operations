$ErrorActionPreference = "Stop"

$base = "C:\Users\essay\OneDrive\Documentos\GitHub\essayons-operations"
$log  = Join-Path $base "daily_sync.log"

function Log($m){
  "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $m" | Tee-Object -FilePath $log -Append
}

Log "=== Daily sync start ==="

$src = Join-Path $base "bol_files\Imported"
$stage = Join-Path $base "_dailyupload"

Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $stage | Out-Null

$cut = (Get-Date).AddHours(-24)

$recent = Get-ChildItem $src -Recurse -Filter *.pdf -ErrorAction SilentlyContinue |
  Where-Object { $_.LastWriteTime -ge $cut } |
  Group-Object {
    if ($_.BaseName -match '^BOL_(\d+)') {
      $matches[1]
    } else {
      $_.BaseName
    }
  } |
  ForEach-Object {
    $_.Group | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  }

if (-not $recent) {
  Log "No new unique BOL PDFs in last 24h."
  Log "=== Done ==="
  return
}

$recent | Copy-Item -Destination $stage
Log ("Staged " + $recent.Count + " unique BOL PDF(s).")

$token = [System.Environment]::GetEnvironmentVariable("LOCAL_RMS_IMPORT_TOKEN","User")
if (-not $token) {
  Log "No token found. Aborting."
  Log "=== Done ==="
  return
}

$azure = "https://eoms-dispatch-v2-aahcamatf0cpa5gy.centralus-01.azurewebsites.net"
$up = Join-Path $base "tools\eoms_upload.ps1"

Log "Starting upload..."

try {
  $out = & powershell -ExecutionPolicy Bypass -File $up -EomsUrl $azure -Token $token -Folder $stage 2>&1
  $out | ForEach-Object { Log $_ }
} catch {
  Log ("UPLOAD ERROR: " + $_.Exception.Message)
}

Log "=== Done ==="