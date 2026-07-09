# FT5.3A Local Visible RMS Worker

RMS Auto Grab runs directly on the operator's machine. Automation Center
launches a dedicated, visible Microsoft Edge window, attaches the existing EOMS
scraper through CDP, and closes that dedicated browser after synchronization.
There is no active Docker worker, heartbeat loop, or RMS job queue.

## Local configuration

Copy `.env.example` to `.env` and configure:

```text
EOMS_BASE_URL=https://your-eoms-app.azurewebsites.net
EOMS_WORKER_TOKEN=<same strong token configured in EOMS>
RMS_CDP_ENDPOINT=http://127.0.0.1:9223
RMS_HEADLESS=0
RMS_MANUAL_LOGIN=1
RMS_BROWSER=cdp
```

## One-click operation

1. Start EOMS:

   ```text
   .venv\Scripts\python.exe app.py
   ```

2. Log into EOMS, open Automation Center, and click **Run RMS Auto Grab**.

3. Confirm the dedicated visible RMS window moves through the BOL workflow,
   `bol_data.json` updates, `/api/sync-result` receives the final result, and
   Automation Center displays it. The dedicated Edge window closes when the
   worker finishes.

The worker writes stdout plus `diagnostics/eoms_local_worker.log`. It uses
`runtime/rms_user_edge_debug_profile` by default so RMS authentication can be
retained between runs without touching the operator's normal Edge windows.

## Daily schedule

Run `INSTALL_LOCAL_RMS_SYNC_TASK.bat` once. It creates `EOMS Local RMS Sync`
at 06:00 daily and invokes `eoms_local_worker.py` using the repository `.venv`.
The scheduled run uses the same automatic Edge lifecycle as the button.

## Archived Docker reference

`Dockerfile.rms-worker` and `docker-compose.rms-worker.yml` are retained only
as historical reference. The Compose service requires the explicit
`archived-reference` profile and is not part of current operation or
validation.
