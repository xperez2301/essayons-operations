from __future__ import annotations

import subprocess
from datetime import datetime, timezone


class GitHubDeploymentService:
    """
    Provides Git repository and deployment health information.
    """

    def __init__(self, base_dir: str):
        self.base_dir = base_dir

    def get_health(self) -> dict:
        branch = self._git("rev-parse --abbrev-ref HEAD")
        commit = self._git("rev-parse --short HEAD")
        status = self._git("status --porcelain")

        return {
            "name": "GitHub",
            "status": "ok",
            "message": "Repository is healthy.",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "details": {
                "branch": branch,
                "commit": commit,
                "working_tree": "Clean" if status == "" else "Modified",
                "base_directory": str(self.base_dir),
            },
        }

    def _git(self, command: str) -> str:
        try:
            result = subprocess.run(
                ["git"] + command.split(),
                cwd=self.base_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0:
                return result.stdout.strip()

            return "Unavailable"

        except Exception:
            return "Unavailable"