"""Build, health-check, and roll back a single-workspace Docker Compose release."""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy" / "compose.yml"
STATE_DIR = ROOT / ".deploy-state"
REQUIRED = (
    "MMD_ENVIRONMENT", "MMD_WORKSPACE_ID", "MMD_PUBLIC_API_URL", "MMD_CORS_ORIGINS",
    "MMD_ORIGINALS_BUCKET", "MMD_ORIGINALS_PREFIX", "MMD_OWNER_KEY_FILE",
    "MMD_DATABASE_URL_FILE", "MMD_OPENAI_KEY_FILE",
)


def load_env(path: Path) -> dict[str, str]:
    """Read plain KEY=VALUE release config without executing shell code."""
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("Release config must use KEY=VALUE lines.")
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError("Invalid release config key.")
        values[key] = value.strip().strip('"').strip("'")
    missing = [key for key in REQUIRED if not values.get(key)]
    if missing:
        raise ValueError("Missing release settings: " + ", ".join(missing))
    if values["MMD_ENVIRONMENT"] not in {"staging", "production"}:
        raise ValueError("MMD_ENVIRONMENT must be staging or production.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,40}", values["MMD_WORKSPACE_ID"]):
        raise ValueError("MMD_WORKSPACE_ID must be a lowercase, hyphenated identifier.")
    if not values["MMD_PUBLIC_API_URL"].startswith("https://"):
        raise ValueError("MMD_PUBLIC_API_URL must be HTTPS.")
    for key in ("MMD_OWNER_KEY_FILE", "MMD_DATABASE_URL_FILE", "MMD_OPENAI_KEY_FILE"):
        if not Path(values[key]).is_file():
            raise ValueError(f"{key} must point to an existing secret file.")
    return values


def _run(command: list[str], env: dict[str, str]) -> None:
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def _compose(path: Path, project: str, env: dict[str, str], *args: str) -> None:
    _run(["docker", "compose", "--env-file", str(path), "-f", str(COMPOSE),
          "-p", project, *args], env)


def release(path: Path, *, validate_only: bool = False, rollback: bool = False) -> dict:
    path = path.resolve()
    values = load_env(path)
    project = f"mmdrag-{values['MMD_ENVIRONMENT']}-{values['MMD_WORKSPACE_ID']}"
    state_path = STATE_DIR / f"{project}.json"
    state = json.loads(state_path.read_text()) if state_path.is_file() else {}
    if rollback:
        tag = state.get("previous")
        if not tag:
            raise ValueError("No previous release is recorded for this workspace.")
    else:
        if not validate_only and subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
            raise ValueError("Commit all workspace changes before tagging a release image.")
        tag = subprocess.check_output(["git", "rev-parse", "--short=12", "HEAD"], cwd=ROOT, text=True).strip()
    env = {**os.environ, **values}
    env["MMD_BACKEND_IMAGE"] = f"mmd-rag-backend:{project}-{tag}"
    env["MMD_FRONTEND_IMAGE"] = f"mmd-rag-frontend:{project}-{tag}"
    _compose(path, project, env, "config", "--quiet")
    if validate_only:
        return {"project": project, "tag": tag, "validated": True}
    if not rollback:
        _run(["docker", "build", "-t", env["MMD_BACKEND_IMAGE"], "mmr-backend"], env)
        _run(["docker", "build", "-t", env["MMD_FRONTEND_IMAGE"],
              "--build-arg", f"NEXT_PUBLIC_API_BASE_URL={values['MMD_PUBLIC_API_URL']}",
              "mmr-frontend"], env)
    try:
        _compose(path, project, env, "up", "-d", "--no-build", "--wait", "--wait-timeout", "180")
        _run(["python3", str(ROOT / "deploy" / "acceptance.py"),
              "--api", values["MMD_PUBLIC_API_URL"],
              "--owner-key-file", values["MMD_OWNER_KEY_FILE"]], env)
    except (subprocess.CalledProcessError, OSError):
        previous = state.get("current")
        if previous and not rollback:
            env["MMD_BACKEND_IMAGE"] = f"mmd-rag-backend:{project}-{previous}"
            env["MMD_FRONTEND_IMAGE"] = f"mmd-rag-frontend:{project}-{previous}"
            _compose(path, project, env, "up", "-d", "--no-build", "--wait", "--wait-timeout", "180")
        raise
    STATE_DIR.mkdir(exist_ok=True)
    new_state = {"current": tag, "previous": state.get("current")}
    state_path.write_text(json.dumps(new_state, sort_keys=True) + "\n")
    return {"project": project, "tag": tag, "validated": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    print(release(args.env_file, validate_only=args.validate_only, rollback=args.rollback))


if __name__ == "__main__":
    main()
