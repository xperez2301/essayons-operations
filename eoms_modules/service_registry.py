from eoms_modules.backup_manager import BackupManager
from eoms_modules.database_validator import DatabaseValidator
from eoms_modules.legacy_rms_repair import LegacyRMSRepair
from eoms_modules.database_center_service import DatabaseCenterService
from eoms_modules.system_health_service import SystemHealthService
from eoms_modules.azure_health_service import AzureHealthService


class ServiceRegistry:
    """
    Central dependency container for EOMS services.
    """

    def __init__(self, app):
        self.app = app

        self.stores_file = app.config["STORES_FILE"]
        self.bol_dir = app.config["BOL_DIR"]
        self.upload_dir = app.config["UPLOAD_DIR"]
        self.base_dir = app.config["BASE_DIR"]
        self.database_health_report = app.config["DATABASE_HEALTH_REPORT"]
        self.backup_stores_json = app.config["BACKUP_STORES_JSON"]
        self.audit = app.config["AUDIT"]

        self.database_validator = DatabaseValidator()
        self.legacy_rms_repair = LegacyRMSRepair()

        self.backup_manager = BackupManager(
            stores_file=self.stores_file,
            base_dir=self.base_dir,
            backup_stores_json=self.backup_stores_json,
            audit=self.audit,
        )

        self.azure_health_service = AzureHealthService(app)

        self.database_center_service = DatabaseCenterService(
            stores_file=self.stores_file,
            bol_dir=self.bol_dir,
            upload_dir=self.upload_dir,
            base_dir=self.base_dir,
            database_health_report=self.database_health_report,
            backup_manager=self.backup_manager,
            database_validator=self.database_validator,
            legacy_rms_repair=self.legacy_rms_repair,
        )

        self.system_health_service = SystemHealthService(
        database_center_service=self.database_center_service,
        azure_health_service=self.azure_health_service,
    )