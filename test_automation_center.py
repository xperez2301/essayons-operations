from eoms_modules.automation_center_service import AutomationCenterService
from eoms_modules.rms_worker_service import rms_worker


def main():
    center = AutomationCenterService()

    result = center.register_worker(rms_worker)

    print("Registration:")
    print(result)

    print("\nWorkers:")
    print(center.list_workers())

    print("\nCenter Health:")
    print(center.center_health())


if __name__ == "__main__":
    main()