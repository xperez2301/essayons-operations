from eoms_modules.automation_center_service import AutomationCenterService
from eoms_modules.rms_worker_service import rms_worker


automation_center = AutomationCenterService()


def register_default_workers():
    """
    Register all default FT3 workers.

    Future workers:
    - GPS7000 Worker
    - SMS Worker
    - Email Worker
    - PDF Worker
    """
    if not automation_center.get_worker(rms_worker.name()):
        automation_center.register_worker(rms_worker)

    return automation_center


register_default_workers()
