param(
    [Parameter(Mandatory=$true)]
    [string]$EomsUrl,

    [Parameter(Mandatory=$true)]
    [string]$Token,

    [string]$Folder = "."
)

$ErrorActionPreference = "Stop"

$resolvedFolder = Resolve-Path -LiteralPath $Folder
$files = Get-ChildItem -LiteralPath $resolvedFolder -File |
    Where-Object { $_.Extension.ToLowerInvariant() -in @(".pdf", ".xlsx", ".csv") }

if (-not $files) {
    Write-Host "No PDF, XLSX, or CSV files found in $resolvedFolder"
    exit 1
}

$endpoint = $EomsUrl.TrimEnd("/") + "/api/local-rms/import"
$client = [System.Net.Http.HttpClient]::new()
$client.DefaultRequestHeaders.Authorization =
    [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $Token)

$content = [System.Net.Http.MultipartFormDataContent]::new()
$streams = @()

try {
    foreach ($file in $files) {
        $stream = [System.IO.File]::OpenRead($file.FullName)
        $streams += $stream
        $fileContent = [System.Net.Http.StreamContent]::new($stream)
        $fileContent.Headers.ContentType =
            [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("application/octet-stream")
        $content.Add($fileContent, "rms_file", $file.Name)
        Write-Host "Queued $($file.Name)"
    }

    Write-Host "Uploading $($files.Count) file(s) to $endpoint"
    $response = $client.PostAsync($endpoint, $content).Result
    $body = $response.Content.ReadAsStringAsync().Result

    if (-not $response.IsSuccessStatusCode) {
        Write-Host "Upload failed: HTTP $([int]$response.StatusCode)"
        Write-Host $body
        exit 1
    }

    Write-Host "Upload complete:"
    Write-Host $body
}
finally {
    foreach ($stream in $streams) {
        $stream.Dispose()
    }
    $content.Dispose()
    $client.Dispose()
}
