"""Verify and copy registered source originals to a configured S3 bucket."""

import argparse
import os
from pathlib import Path

from app import database, originals


def migrate(upload_dir: Path) -> dict[str, int]:
    """Copy registered originals; keep local files for rollback and verification."""
    if not originals.enabled():
        raise ValueError("Set RAG_ORIGINALS_BUCKET before copying originals.")
    documents = database.list_documents()
    sources = {}
    for document in documents:
        name = document.get("storage_name") or document["filename"]
        if Path(name).name != name:
            raise ValueError("A registered original has an unsafe storage name.")
        source = upload_dir / name
        if not source.is_file():
            raise FileNotFoundError("A registered original is missing; migration stopped.")
        sources[name] = source
    for name, source in sources.items():
        originals.put(name, source)
    return {"documents": len(documents), "objects_verified": len(sources)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uploads", type=Path, default=Path(os.getenv("RAG_UPLOAD_DIR", "docs")))
    args = parser.parse_args()
    print(migrate(args.uploads))


if __name__ == "__main__":
    main()
