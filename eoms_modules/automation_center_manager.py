from eoms_modules.automation_center_service import AutomationCenterService
from eoms_modules.rms_worker_service import rms_worker
from eoms_modules.gps7000_worker_service import gps7000_worker


automation_center = AutomationCenterService()


def register_default_workers():
    """
    Register all default FT3 workers.
    """
    if not automation_center.get_worker(rms_worker.name()):
        automation_center.register_worker(rms_worker)

    if not automation_center.get_worker(gps7000_worker.name()):
        automation_center.register_worker(gps7000_worker)

    return automation_center


register_default_workers()