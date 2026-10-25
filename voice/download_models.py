#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Explicit online setup: download pinned official weights; normal service is offline."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time
import urllib.request


def digest(file, kind):
    hasher = hashlib.sha256() if kind == "sha256" else hashlib.sha1()
    if kind == "gitSha1":
        hasher.update(f"blob {file.stat().st_size}\0".encode())
    with file.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-root", required=True, type=Path, help="Shared local TTS model directory")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    lock = json.loads((Path(__file__).parent / "models.lock.json").read_text(encoding="utf-8"))
    root = args.models_root.expanduser().resolve()
    destination = root / lock["directory"]
    destination.mkdir(parents=True, exist_ok=True)

    def transfer(entry):
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid locked relative path")
        file = destination / relative
        if not file.resolve().is_relative_to(destination.resolve()):
            raise ValueError("Model file resolves outside destination")
        kind = "sha256" if "sha256" in entry else "gitSha1"
        expected = entry[kind]
        if file.is_file() and file.stat().st_size == entry["size"] and digest(file, kind) == expected:
            return {"file": entry["path"], "status": "reused-verified", "bytes": entry["size"]}
        if args.verify_only:
            raise ValueError("Missing or mismatched locked model file: " + entry["path"])
        file.parent.mkdir(parents=True, exist_ok=True)
        partial = file.with_name(file.name + ".partial")
        if partial.exists() and partial.stat().st_size > entry["size"]:
            raise ValueError("Oversized partial model file; inspect it before retrying")
        url = f'https://huggingface.co/{lock["repo"]}/resolve/{lock["revision"]}/{entry["path"]}'
        for attempt in range(5):
            try:
                offset = partial.stat().st_size if partial.exists() else 0
                headers = {"User-Agent": "airi-phoenix-local-voice-setup/0.1"}
                if offset:
                    headers["Range"] = f"bytes={offset}-"
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as response:
                    append = bool(offset and response.status == 206)
                    with partial.open("ab" if append else "wb") as output:
                        while chunk := response.read(4 * 1024 * 1024):
                            output.write(chunk)
                if partial.stat().st_size != entry["size"] or digest(partial, kind) != expected:
                    raise ValueError("Downloaded file failed size/hash verification: " + entry["path"])
                partial.replace(file)
                return {"file": entry["path"], "status": "downloaded-verified", "bytes": entry["size"]}
            except Exception:
                if attempt == 4:
                    raise
                time.sleep(min(2 ** attempt, 15))

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(transfer, lock["files"]))
    manifest = {"repo": lock["repo"], "revision": lock["revision"], "files": results,
                "tokenizer": "speech_tokenizer is the matching official 12Hz tokenizer; no duplicate download."}
    (destination / "download-verification.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
