param([string]$EomsUrl,[string]$Token,[string]$Folder)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http
$files = Get-ChildItem -LiteralPath $Folder -File | Where-Object { $_.Extension.ToLower() -in @(".pdf",".xlsx",".csv") }
if (-not $files) { Write-Host "No files found in $Folder"; exit 1 }
$endpoint = $EomsUrl.TrimEnd("/") + "/api/local-rms/import"
$client = New-Object System.Net.Http.HttpClient
$client.Timeout = [TimeSpan]::FromMinutes(10)
$client.DefaultRequestHeaders.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", $Token)
$content = New-Object System.Net.Http.MultipartFormDataContent
$streams = @()
foreach ($f in $files) {
  $s = [System.IO.File]::OpenRead($f.FullName); $streams += $s
  $fc = New-Object System.Net.Http.StreamContent($s)
  $fc.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("application/octet-stream")
  $content.Add($fc, "rms_file", $f.Name)
  Write-Host "Queued $($f.Name)"
}
Write-Host "Uploading $($files.Count) file(s) to $endpoint"
$resp = $client.PostAsync($endpoint, $content).Result
$body = $resp.Content.ReadAsStringAsync().Result
Write-Host "HTTP $([int]$resp.StatusCode)"
Write-Host $body
foreach ($s in $streams) { $s.Dispose() }
$content.Dispose(); $client.Dispose()
