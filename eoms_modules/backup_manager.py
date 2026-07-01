from pathlib import Path


class BackupManager:
    def __init__(self, stores_file, base_dir, backup_stores_json, audit):
        self.stores_file = Path(stores_file)
        self.base_dir = Path(base_dir)
        self.backup_stores_json = backup_stores_json
        self.audit = audit

    def create_backup(self, reason="manual_backup"):
        backup_path = self.backup_stores_json(
            self.stores_file,
            self.base_dir / "backups",
            reason=reason,
        )

        result = {
            "ok": True,
            "backup_path": str(backup_path),
            "message": "Database backup created.",
        }

        self.audit("Database Backup", result)
        return result