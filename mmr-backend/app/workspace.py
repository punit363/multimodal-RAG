"""Bind a persistent vector directory to exactly one workspace identifier."""

import os
import tempfile
from pathlib import Path


def bind_vector_directory(path: str, workspace: str) -> None:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / ".rag-workspace"
    with tempfile.NamedTemporaryFile(mode="w", prefix=".rag-workspace-", dir=directory,
                                     delete=False, encoding="utf-8") as stream:
        stream.write(workspace + "\n")
        temporary = Path(stream.name)
    try:
        try:
            os.link(temporary, marker)
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)
    if marker.read_text(encoding="utf-8").strip() != workspace:
        raise RuntimeError("Vector directory belongs to a different workspace.")
