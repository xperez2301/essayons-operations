async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));

    if (!response.ok || data.ok === false) {
        throw new Error(data.message || data.error || "Request failed");
    }

    return data;
}

function formatBytes(bytes) {
    if (!bytes && bytes !== 0) return "-";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function formatDate(value) {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
}

function showDbResult(title, data) {
    const box = document.getElementById("dbResultBox");
    const text = document.getElementById("dbResultText");
    if (!box || !text) return;

    let output = title + "\n\n";
    output += "Updated: " + (data.updated ?? data.repaired ?? 0) + "\n";
    output += "Failed: " + (data.failed ?? 0) + "\n\n";

    const failures = data.failures || [];
    if (failures.length) {
        output += "Failures\n--------------------------\n";
        failures.slice(0, 25).forEach((f, index) => {
            output += `${index + 1}. ${f.origin || f.bol || f.store || "Unknown"}\n`;
            output += `Address: ${f.address || "-"}\n`;
            output += `Reason: ${f.reason || "-"}\n\n`;
        });
    }

    box.style.display = "block";
    text.textContent = output;
}

function showTab(name) {
    document.querySelectorAll(".db-tab").forEach(tab => {
        tab.style.display = "none";
    });

    const active = document.getElementById("tab-" + name);

    if (active) {
        active.style.display = "block";
        active.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    if (name === "backups") {
        loadBackups();
    }
}

async function loadBackups() {
    const body = document.getElementById("backupTableBody");
    const count = document.getElementById("backupCount");

    if (!body || !count) return;

    body.innerHTML = `<tr><td colspan="4" class="muted">Loading backups...</td></tr>`;

    try {
        const data = await fetchJson("/api/database/backups");
        const backups = data.backups || [];

        count.textContent = data.count ?? backups.length;

        if (!backups.length) {
            body.innerHTML = `<tr><td colspan="4" class="muted">No backups found.</td></tr>`;
            return;
        }

        body.innerHTML = backups.map(file => `
            <tr>
                <td>${file.name || "-"}</td>
                <td>${formatDate(file.modified_at)}</td>
                <td>${formatBytes(file.size_bytes)}</td>
                <td>
                    <button class="secondary-btn" type="button" onclick="restoreBackup('${file.name}')">Restore</button>
                </td>
            </tr>
        `).join("");
    } catch (error) {
        count.textContent = "Error";
        body.innerHTML = `<tr><td colspan="4" class="muted">Error loading backups: ${error.message}</td></tr>`;
    }
}

async function loadDatabaseCenter() {
    const systemStatus = document.getElementById("systemStatus");
    const duplicateCount = document.getElementById("duplicateCount");
    const missingPdfCount = document.getElementById("missingPdfCount");

    if (systemStatus) systemStatus.textContent = "Checking...";

    try {
        await loadBackups();
        if (systemStatus) systemStatus.textContent = "Online";
    } catch {
        if (systemStatus) systemStatus.textContent = "Warning";
    }

    try {
        const dup = await fetchJson("/api/database/duplicates");
        if (duplicateCount) {
            duplicateCount.textContent = dup.duplicate_count ?? dup.duplicate_bol_count ?? 0;
        }
    } catch {
        if (duplicateCount) duplicateCount.textContent = "Error";
    }

    try {
        const missing = await fetchJson("/api/database/missing-pdfs");
        if (missingPdfCount) {
            missingPdfCount.textContent = missing.missing_pdf_count ?? 0;
        }
    } catch {
        if (missingPdfCount) missingPdfCount.textContent = "Error";
    }
}

async function restoreBackup(name) {
    if (!name) return;

    const confirmed = confirm(
        "Restore this backup?\n\n" +
        name +
        "\n\nThis will overwrite the current stores.json. A safety backup should be created first."
    );

    if (!confirmed) return;

    try {
        const data = await fetchJson("/api/database/restore-backup", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ backup_name: name })
        });

        alert(data.message || "Backup restored successfully.");
        await loadDatabaseCenter();
        showTab("backups");
    } catch (error) {
        alert("Restore failed: " + error.message);
    }
}

async function createBackupNow() {
    const confirmed = confirm("Create a new stores.json backup now?");
    if (!confirmed) return;

    try {
        const data = await fetchJson("/api/database/backup", {
            method: "POST",
            headers: { "Content-Type": "application/json" }
        });

        alert(data.message || "Backup created.");
        await loadDatabaseCenter();
        showTab("backups");
    } catch (error) {
        alert("Backup failed: " + error.message);
    }
}

async function reGeocodeStores() {
    const confirmed = confirm(
        "Re-geocode all stores using the current Azure Maps key?\n\nThis will update saved latitude/longitude coordinates."
    );

    if (!confirmed) return;

    try {
        const data = await fetchJson("/api/geocode-stores", {
            method: "POST",
            headers: { "Content-Type": "application/json" }
        });

        showDbResult("Re-geocode complete", data);
        alert(`Re-geocode complete.\nUpdated: ${data.updated}\nFailed: ${data.failed}`);
        await loadDatabaseCenter();
    } catch (error) {
        alert("Re-geocode failed: " + error.message);
    }
}

async function repairLegacyRmsData() {
    alert("Database Center 2.0\n\nRepair Legacy RMS Data is coming next.");
}

window.fetchJson = fetchJson;
window.formatBytes = formatBytes;
window.formatDate = formatDate;
window.showDbResult = showDbResult;
window.showTab = showTab;
window.loadBackups = loadBackups;
window.loadDatabaseCenter = loadDatabaseCenter;
window.restoreBackup = restoreBackup;
window.createBackupNow = createBackupNow;
window.reGeocodeStores = reGeocodeStores;
window.repairLegacyRmsData = repairLegacyRmsData;

document.addEventListener("DOMContentLoaded", function () {
    loadDatabaseCenter();

    const createBackupButton = document.getElementById("btnCreateBackupNow");
    if (createBackupButton) {
        createBackupButton.addEventListener("click", createBackupNow);
    }
});