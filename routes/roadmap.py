"""Roadmap workspace blueprint.

FT6 blueprint split: relocates Flask routing/glue code out of app.py.
Business logic stays in eoms_modules.roadmap_service, unchanged.
"""

from flask import Blueprint, render_template

from app import ROADMAP_FILE, build_roadmap_workspace

roadmap_bp = Blueprint("roadmap", __name__)


@roadmap_bp.route("/roadmap")
def roadmap_workspace():
    workspace = build_roadmap_workspace(ROADMAP_FILE)
    return render_template("roadmap.html", workspace=workspace)
