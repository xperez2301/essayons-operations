from functools import wraps
from flask import jsonify, redirect, render_template, request, session, url_for


def admin_required(is_admin_func):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get("logged_in"):
                return redirect(url_for("login", next=request.path))
            if not is_admin_func():
                return render_template("access_denied.html"), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def dispatch_required(can_dispatch_func):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get("logged_in"):
                return redirect(url_for("login", next=request.path))
            if not can_dispatch_func():
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "message": "Dispatch access required."}), 403
                return render_template("access_denied.html"), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator