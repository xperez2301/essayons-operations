from pathlib import Path


class DatabaseCenterService:
    def __init__(
        self,
        stores_file,
        bol_dir,
        upload_dir,
        base_dir,
        database_health_report,
        backup_manager,
    ):
        self.stores_file = Path(stores_file)
        self.bol_dir = Path(bol_dir)
        self.upload_dir = Path(upload_dir)
        self.base_dir = Path(base_dir)

        self.database_health_report = database_health_report
        self.backup_manager = backup_manager

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
        return self.backup_manager.create_backup(reason="manual_backup")