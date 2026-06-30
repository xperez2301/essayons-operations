$ErrorActionPreference = "Continue"

$Base = "C:\Users\essay\OneDrive\Documentos\GitHub\essayons-operations"
$AzureUrl = "https://eoms-dispatch-v2-aahcamatf0cpa5gy.centralus-01.azurewebsites.net"
$LogFile = Join-Path $Base "diagnostics\eoms_commander.log"

New-Item -ItemType Directory -Force -Path (Split-Path $LogFile) | Out-Null

function Write-Log($Message) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $Message" | Tee-Object -FilePath $LogFile -Append
}

function Pause-Commander {
    Write-Host ""
    Read-Host "Press Enter to return to EOMS Commander"
}

while ($true) {
    Clear-Host
    Write-Host "===================================================="
    Write-Host "             ESSAYONS EOMS COMMANDER"
    Write-Host "===================================================="
    Write-Host ""
    Write-Host "1. Open Azure EOMS"
    Write-Host "2. Open Local EOMS"
    Write-Host "3. Start RMS Browser"
    Write-Host "4. Run Daily Sync / Upload"
    Write-Host "5. View Commander Log"
    Write-Host "6. Exit"
    Write-Host ""

    $choice = Read-Host "Choose option"

    switch ($choice) {
        "1" {
            Write-Log "Opening Azure EOMS"
            Start-Process $AzureUrl
        }

        "2" {
            Write-Log "Opening local EOMS"
            Start-Process "http://127.0.0.1:5000/dashboard"
        }

        "3" {
            Write-Log "Starting RMS browser"
            Start-Process -FilePath (Join-Path $Base "START_RMS_EDGE_DEBUG.bat")
            Pause-Commander
        }

        "4" {
            Write-Log "Starting daily sync/upload"
            powershell -ExecutionPolicy Bypass -File (Join-Path $Base "daily_sync.ps1")
            Write-Log "Daily sync/upload finished"
            Pause-Commander
        }

        "5" {
            Write-Log "Opening commander log"
            notepad $LogFile
        }

        "6" {
            Write-Log "Commander closed"
            exit
        }

        default {
            Write-Host "Invalid option."
            Start-Sleep -Seconds 1
        }
    }
}