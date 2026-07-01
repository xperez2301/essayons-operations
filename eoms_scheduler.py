import time
from datetime import datetime
from rms_playwright_autograb import run


LAST_RUNS = {
    "morning": None,
    "night": None
}


def should_run(slot):
    now = datetime.now()

    if slot == "morning":
        return now.hour == 6 and now.minute == 0

    if slot == "night":
        return now.hour == 22 and now.minute == 0

    return False


def run_job(slot_name):
    print("\n==============================")
    print("🚀 EOMS AUTO-GRAB RUN:", slot_name.upper())
    print("TIME:", datetime.now())
    print("==============================\n")

    try:
        run()
        print("\n✅ RUN COMPLETE")
    except Exception as e:
        print("\n❌ ERROR:", e)


def scheduler_loop():
    print("🔥 EOMS SCHEDULER ACTIVE (06:00 & 22:00)")

    while True:
        now = datetime.now()

        # MORNING RUN
        if should_run("morning"):
            if LAST_RUNS["morning"] != now.date():
                run_job("morning")
                LAST_RUNS["morning"] = now.date()

        # NIGHT RUN
        if should_run("night"):
            if LAST_RUNS["night"] != now.date():
                run_job("night")
                LAST_RUNS["night"] = now.date()

        time.sleep(20)  # lightweight loop check


if __name__ == "__main__":
    scheduler_loop()