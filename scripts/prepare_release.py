#!/usr/bin/env python3
"""Reassemble, verify, and publish only an explicitly approved EVE HQ release ZIP."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
READY = ROOT / "publishing" / "ready.json"


def fail(msg):
    raise SystemExit(f"ERROR: {msg}")


def main():
    doc = json.loads(READY.read_text(encoding="utf-8"))
    version = doc["version"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        fail("invalid semantic version")
    if doc["tag"] != "v" + version or doc["archive"] != f"EVE_HQ_{version}_UPDATE.zip":
        fail("release tag and ZIP name do not match version")
    parts = doc["parts"]
    if not 1 <= len(parts) <= 32:
        fail("expected 1-32 encoded ZIP parts")
    expected_names = [f"publishing/payloads/v{version}/part-{i:02d}.txt" for i in range(1, len(parts) + 1)]
    if parts != expected_names:
        fail("parts are not ordered and confined to the expected release directory")
    encoded = "".join((ROOT / part).read_text(encoding="ascii").strip() for part in parts)
    try:
        archive_bytes = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        fail(f"base64 payload is invalid: {exc}")
    digest = hashlib.sha256(archive_bytes).hexdigest()
    if digest != doc["sha256"] or not re.fullmatch(r"[0-9a-f]{64}", digest):
        fail("release SHA-256 mismatch")
    from io import BytesIO
    with zipfile.ZipFile(BytesIO(archive_bytes)) as z:
        if z.testzip() is not None:
            fail("archive has a corrupt member")
        names = z.namelist()
        if len(set(names)) != len(names):
            fail("ZIP contains duplicate paths")
        if not names or names[0] != "release.json":
            fail("missing release manifest")
        manifest = json.loads(z.read("release.json"))
        if manifest.get("version") != version or manifest.get("requires_version") is None:
            fail("ZIP version and manifest do not match")
        allowed = set(manifest.get("files", {}))
        if set(names) != allowed | {"release.json"}:
            fail("ZIP members differ from the allowlisted release manifest")
        for path, expected_sha in manifest["files"].items():
            if not path.startswith("app/") or path.startswith("app/data/") or ".." in Path(path).parts or ".env" in path or path.endswith((".sqlite3", ".db")):
                fail(f"forbidden ZIP member: {path}")
            if hashlib.sha256(z.read(path)).hexdigest() != expected_sha:
                fail(f"file checksum mismatch: {path}")
    out = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / doc["archive"]
    out.write_bytes(archive_bytes)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as f:
            f.write(f"tag={doc['tag']}\narchive={out}\n")
    print(f"Verified {doc['tag']}: {len(archive_bytes):,} bytes; SHA-256 {digest}")


if __name__ == "__main__":
    main()