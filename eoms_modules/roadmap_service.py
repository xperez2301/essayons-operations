import json
from copy import deepcopy
from pathlib import Path


SUPPORTED_BUILD_STATUSES = ("Completed", "Current", "Planned", "Future")
STATUS_CLASSES = {
    "Completed": "success",
    "Current": "warning",
    "Planned": "danger",
    "Future": "neutral",
}
STATUS_MARKERS = {
    "Completed": "green",
    "Current": "yellow",
    "Planned": "red",
    "Future": "blue",
}
DEVELOPMENT_STANDARD = (
    "Blueprint",
    "Design",
    "Build",
    "Validate",
    "Commit",
    "Crack Check",
    "Patch",
    "Clean Git",
    "Blueprint Update",
    "Next Build",
)
FUTURE_CARD_TITLES = (
    "Release History",
    "Architecture Timeline",
    "Technical Debt",
    "Upcoming Features",
)


def clean(value):
    return "" if value is None else str(value).strip()


def safe_percent(completed, total):
    if not total:
        return 0
    return round((completed / total) * 100)


def load_roadmap(path):
    path = Path(path)
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def validate_roadmap(data):
    if not isinstance(data, dict):
        raise ValueError("Roadmap data must be a dictionary.")

    for field in ("current_version", "current_branch", "current_build", "eras", "builds"):
        if field not in data:
            raise ValueError(f"Roadmap data is missing {field}.")

    if not isinstance(data["eras"], list):
        raise ValueError("Roadmap eras must be a list.")

    if not isinstance(data["builds"], list):
        raise ValueError("Roadmap builds must be a list.")

    era_ids = set()
    for era in data["eras"]:
        if not isinstance(era, dict):
            raise ValueError("Every roadmap era must be a dictionary.")
        era_id = clean(era.get("id"))
        if not era_id:
            raise ValueError("Every roadmap era requires an id.")
        era_ids.add(era_id)

    for build in data["builds"]:
        if not isinstance(build, dict):
            raise ValueError("Every roadmap build must be a dictionary.")

        for field in ("id", "title", "era", "status", "description"):
            if not clean(build.get(field)):
                raise ValueError(f"Every roadmap build requires {field}.")

        if build["status"] not in SUPPORTED_BUILD_STATUSES:
            raise ValueError(f"Unsupported build status: {build['status']}")

        if clean(build.get("era")) not in era_ids:
            raise ValueError(f"Build {build.get('id')} references an unknown era.")

    return True


def decorate_build(build):
    decorated = deepcopy(build)
    status = clean(decorated.get("status")) or "Future"
    decorated["status_class"] = STATUS_CLASSES.get(status, "neutral")
    decorated["status_marker"] = STATUS_MARKERS.get(status, "blue")
    decorated.setdefault("completion_date", "")
    decorated.setdefault("release_version", "")
    decorated.setdefault("commit", "")
    decorated.setdefault("dependencies", [])
    decorated.setdefault("notes", "")
    return decorated


def completion_counts(builds):
    completed = [build for build in builds if build["status"] == "Completed"]
    remaining = [build for build in builds if build["status"] != "Completed"]
    return completed, remaining


def build_era_progress(eras, builds):
    progress = []

    for era in eras:
        era_builds = [build for build in builds if build["era"] == era["id"]]
        completed, remaining = completion_counts(era_builds)
        current = next((build for build in era_builds if build["status"] == "Current"), None)
        status = "Current" if current else ("Completed" if era_builds and not remaining else "Planned")

        progress.append({
            "id": era["id"],
            "title": era["title"],
            "description": era.get("description", ""),
            "completed": len(completed),
            "total": len(era_builds),
            "remaining": len(remaining),
            "percent": safe_percent(len(completed), len(era_builds)),
            "status": status,
            "status_class": STATUS_CLASSES.get(status, "neutral"),
            "builds": era_builds,
        })

    return progress


def build_workspace(path):
    data = load_roadmap(path)
    validate_roadmap(data)

    builds = [decorate_build(build) for build in data["builds"]]
    completed, remaining = completion_counts(builds)
    current_build = next((build for build in builds if build["id"] == data["current_build"]), None)
    if current_build is None:
        current_build = next((build for build in builds if build["status"] == "Current"), None)

    next_build = next((build for build in builds if build["status"] in {"Planned", "Future"}), None)
    era_progress = build_era_progress(data["eras"], builds)

    return {
        "current_version": data["current_version"],
        "current_branch": data["current_branch"],
        "current_build": current_build or {},
        "next_build": next_build or {},
        "overall_completion": safe_percent(len(completed), len(builds)),
        "completed_builds": len(completed),
        "remaining_builds": len(remaining),
        "total_builds": len(builds),
        "era_completion": era_progress,
        "builds": builds,
        "development_standard": DEVELOPMENT_STANDARD,
        "future_cards": FUTURE_CARD_TITLES,
        "status_legend": [
            {"status": status, "class": STATUS_CLASSES[status], "marker": STATUS_MARKERS[status]}
            for status in SUPPORTED_BUILD_STATUSES
        ],
    }
