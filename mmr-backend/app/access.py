"""Path-level role policy for one isolated workspace deployment."""

ROLE_LEVEL = {"viewer": 1, "editor": 2, "owner": 3}


def required_role(path: str, method: str) -> str:
    """Return the least privileged role allowed to call a private route."""
    if path.startswith(("/api/ops/", "/api/members", "/api/shares")) or path == "/api/audit-events":
        return "owner"
    if path in {"/api/chat", "/api/chat-stream", "/api/conversations", "/api/auth/logout"} and method == "POST":
        return "viewer"
    if path.startswith("/api/messages/") and method == "PATCH":
        return "viewer"
    if method in {"GET", "HEAD"}:
        return "viewer"
    return "editor"


def allowed(role: str, path: str, method: str) -> bool:
    return ROLE_LEVEL.get(role, 0) >= ROLE_LEVEL[required_role(path, method)]
