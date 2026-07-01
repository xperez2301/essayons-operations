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
        database_validator=None,
        legacy_rms_repair=None,
    ):
        self.stores_file = Path(stores_file)
        self.bol_dir = Path(bol_dir)
        self.upload_dir = Path(upload_dir)
        self.base_dir = Path(base_dir)

        self.database_health_report = database_health_report
        self.backup_manager = backup_manager
        self.database_validator = database_validator
        self.legacy_rms_repair = legacy_rms_repair

    def status(self):
        return {
            "ok": True,
            "service": "Database Center Service",
            "stores_file": str(self.stores_file),
            "bol_dir": str(self.bol_dir),
            "upload_dir": str(self.upload_dir),
            "base_dir": str(self.base_dir),
            "has_backup_manager": self.backup_manager is not None,
            "has_database_validator": self.database_validator is not None,
        }

    def database_health(self):
        return self.database_health_report(
            self.stores_file,
            self.bol_dir,
            self.upload_dir,
        )

    def create_backup(self):
        return self.backup_manager.create_backup(reason="manual_backup")

    def validate_records(self, records):
        if self.database_validator is None:
            return {
                "status": "error",
                "message": "DatabaseValidator service is not configured.",
            }

        return self.database_validator.validate_records(records)
    
        def needs_legacy_rms_repair(self, record):
        if self.legacy_rms_repair is None:
            return False

        return self.legacy_rms_repair.needs_repair(record)

    def repair_legacy_rms_record(self, record):
        if self.legacy_rms_repair is None:
            return {
                "status": "error",
                "message": "LegacyRMSRepair service is not configured.",
                "record": record,
            }

        return self.legacy_rms_repair.repair_record(record)