from pathlib import Path


class DatabaseCenterService:
    def __init__(
        self,
        stores_file,
        bol_dir,
        upload_dir,
        base_dir,
        database_health_report,
        backup_stores_json,
        audit,
    ):
        self.stores_file = Path(stores_file)
        self.bol_dir = Path(bol_dir)
        self.upload_dir = Path(upload_dir)
        self.base_dir = Path(base_dir)

        self.database_health_report = database_health_report
        self.backup_stores_json = backup_stores_json
        self.audit = audit

    def status(self):
        return {
            "ok": True,
            "service": "Database Center Service",
            "stores_file": str(self.stores_file),
            "bol_dir": str(self.bol_dir),
            "upload_dir": str(self.upload_dir),
            "base_dir": str(self.base_dir),
        }

    def database_health(self):
        return self.database_health_report(
            self.stores_file,
            self.bol_dir,
            self.upload_dir,
        )

    def create_backup(self):
        backup_path = self.backup_stores_json(
            self.stores_file,
            self.base_dir / "backups",
            reason="manual_backup",
        )

        result = {
            "ok": True,
            "backup_path": str(backup_path),
            "message": "Database backup created.",
        }

        self.audit("Database Backup", result)

        return result