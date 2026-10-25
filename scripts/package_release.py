#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build and verify the source/recipe bundle without models, profiles or weights."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.2.0"
FOLDER = "airi-character-forge"
ROOT_FILES = {".gitignore", "AGENTS.md", "LICENSE", "README.md", "RIGHTS.md", "SKILL.md", "START_HERE.md"}
FOLDERS = {"agents", "agent_bridge", "airi-integration", "character-tools", "control-center", "diagnostics", "launchers", "mmd-tools", "docs", "examples", "prompts", "rig-tools", "scripts", "shared-speech", "sticker-tools", "voice"}
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".cjs", ".mjs", ".html", ".yaml"}
BINARY_FILES = {"rig-tools/examples/robot/artwork/parts.png", "examples/deskbot/artwork/parts.png",
    "docs/images/robot-preview.png", "voice/samples/phoenix-soft.wav",
    "voice/samples/phoenix-drowsy.wav", "voice/samples/phoenix-focused.wav", "mmd-tools/examples/natural-idle.vmd"}
EXCLUDE_PARTS = {".git", "__pycache__", "node_modules", ".venv", "runtime", "state", "logs", "backups", "work", "output", "local-assets", "electron-profile", "isolated-profile", ".browser-profile"}
EXTRA_SOURCE_FILES = {"control-center/web/app.js", "control-center/web/style.css", "control-center/web/favicon.svg", "launchers/airi-select-profile.ps1", "launchers/control-center-start.ps1", "launchers/control-center-stop.ps1", "airi-integration/character-3d-bootstrap.js", "mmd-tools/mmd-idle-driver.js", "voice/bench_sapi.ps1", "voice/windows-sapi/.gitignore", "voice/windows-sapi/common.ps1", "voice/windows-sapi/start.ps1", "voice/windows-sapi/stop.ps1", "voice/windows-sapi/worker.ps1", "airi-integration/offline-shell/character-bootstrap.js", "airi-integration/offline-shell/character-3d-bootstrap.js", "airi-integration/offline-shell/character-view-controller.js", "airi-integration/offline-shell/mmd-idle-driver.js", "launchers/airi-env.ps1", "launchers/airi-start.ps1", "launchers/airi-stop.ps1", "launchers/airi-update.ps1", "launchers/airi-model-common.ps1", "launchers/airi-model-start.ps1", "launchers/airi-model-stop.ps1", "launchers/airi-model-health.ps1", "launchers/airi-speech-start.ps1", "launchers/airi-speech-stop.ps1"}


def source_files():
    files = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDE_PARTS for part in relative.parts):
            continue
        if relative.parts[0] not in FOLDERS and relative.as_posix() not in ROOT_FILES:
            continue
        if path.is_symlink():
            raise ValueError(f"Symlink is not a releasable source file: {relative}")
        name = relative.as_posix()
        if name not in BINARY_FILES and name not in EXTRA_SOURCE_FILES and path.suffix.lower() not in TEXT_SUFFIXES and path.name != "LICENSE" and name != ".gitignore":
            raise ValueError(f"Unexpected file type; explicitly review before publishing: {name}")
        data = path.read_bytes()
        if name not in BINARY_FILES:
            text = data.decode("utf-8-sig")
            normalized = text.replace("\\\\", "\\").replace("\\", "/").lower()
            if re.search(r"\b[a-z]:/users/[^/ \t\r\n]+", normalized) or re.search(r"\bsk-[a-zA-Z0-9]{24,}\b", text):
                raise ValueError(f"Private path or token-shaped material in: {name}")
        files.append((name, data))
    return files


def verify(archive):
    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read(FOLDER+"/PACKAGE-MANIFEST.json"))
        expected = {FOLDER+"/"+entry["file"] for entry in manifest["files"]}
        expected.add(FOLDER+"/PACKAGE-MANIFEST.json")
        if set(bundle.namelist()) != expected or len(bundle.namelist()) != len(expected):
            raise ValueError("Archive entries do not exactly match the manifest")
        for entry in manifest["files"]:
            data = bundle.read(FOLDER+"/"+entry["file"])
            if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError("Archive integrity mismatch: "+entry["file"])
            path = Path(entry["file"])
            if path.is_absolute() or ".." in path.parts or any(part in EXCLUDE_PARTS for part in path.parts):
                raise ValueError("Excluded or unsafe archive path: "+entry["file"])
            if path.suffix.lower() in {".png", ".wav", ".vmd"} and entry["file"] not in BINARY_FILES:
                raise ValueError("Unreviewed binary artwork/audio: "+entry["file"])
        return {"ok": True, "version": manifest["version"], "sourceFiles": len(manifest["files"]),
            "archiveFiles": len(expected), "bytes": archive.stat().st_size,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "excludedVerified": ["Core/SDK binaries", "official and official-derived media/models", "weights", "credentials/private paths", "browser profiles/caches", ".git", "runtime user settings"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT/"dist"/(FOLDER+"-"+VERSION+".zip"))
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify(args.verify.resolve()), indent=2))
        return
    files = source_files()
    manifest = {"name": FOLDER, "version": VERSION, "license": "MIT for original code/docs/prompts/robot; third-party and character rights separate",
        "entry": "SKILL.md", "start": "START_HERE.md", "selfContainedSource": True,
        "externalRequirements": ["Python/Pillow", "optional Node and independently licensed Core", "optional GPU/PyTorch plus separately downloaded TTS weights", "agent-supplied semantic image tools"],
        "files": [{"file": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in files]}
    output = args.out.resolve()
    if output == ROOT or output.is_dir():
        parser.error("--out must be a ZIP file path")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name, data in [*files, ("PACKAGE-MANIFEST.json", (json.dumps(manifest, indent=2)+"\n").encode())]:
            info = zipfile.ZipInfo(FOLDER+"/"+name, (2026,10,25,0,0,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, data)
    report = verify(output)
    output.with_suffix(".manifest.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({**report, "archive": str(output)}, indent=2))


if __name__ == "__main__":
    main()
