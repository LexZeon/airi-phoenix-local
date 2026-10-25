#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Export a character config to AIRI and Character Card formats. Python stdlib only.

No network, AIRI storage access, or application changes. Character artwork and any
third-party runtime keep their own rights; this program does not grant those rights.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import zipfile
from pathlib import Path, PurePosixPath


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_config(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if value.get("schemaVersion") != 1:
        raise ValueError("schemaVersion must be 1")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value.get("id", "")):
        raise ValueError("id must be a lowercase slug")
    for key in ("name", "version", "systemPrompt", "description", "personality", "scenario"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError(f"{key} must be a nonempty string")
    if not value.get("greetings") or not all(isinstance(s, str) for s in value["greetings"]):
        raise ValueError("greetings must be a nonempty string array")
    modules = value["modules"]
    for module in ("consciousness", "vision", "speech"):
        for key in ("provider", "model"):
            if not isinstance(modules[module].get(key), str):
                raise ValueError(f"modules.{module}.{key} must be a string")
    if not isinstance(modules["speech"].get("voice_id"), str):
        raise ValueError("modules.speech.voice_id must be a string")
    names = [e["name"] for e in value.get("expressions", [])]
    if len(set(names)) != len(names):
        raise ValueError("Expression names must be unique")
    for name in names:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError("Use stable ASCII expression names")
    for line in value.get("exampleMessages", []):
        if "\n" in line or not line.startswith(("{{user}}:", "{{char}}:")):
            raise ValueError("exampleMessages lines must begin {{user}}: or {{char}}: and contain no newline")
    return value


def expression_prompt(config: dict) -> str:
    if not config.get("expressions"):
        return ""
    lines = [
        "Live2D 表情规则：仅在当前模型的可用控制列表确实包含相应名称时使用。",
        '在需要表情变化的回复开头输出 <|ACT {"expression":{"name":"E01_LowEnergy","duration":4}}|> 形式的单个控制标记；name 必须换成下面的精确名称。',
        'duration 单位秒，建议 2–5 秒；<|ACT {"expression":null}|> 恢复默认表情。普通回复不必每句切换，控制标记以外不说出参数或动作说明。',
    ]
    # The syntax example must use an actual configured expression for other characters.
    lines[1] = lines[1].replace("E01_LowEnergy", config["expressions"][0]["name"])
    lines += [f'- {e["name"]}：{e["use"]}' for e in config["expressions"]]
    return "\n".join(lines)


def native_card(config: dict) -> dict:
    prompt = config["systemPrompt"]
    expressions = expression_prompt(config)
    if expressions:
        prompt += "\n\n" + expressions
    return {
        "name": config["name"], "nickname": config.get("nickname", config["name"]),
        "version": config["version"], "creator": config.get("creator", ""),
        "description": config["description"], "personality": config["personality"],
        "scenario": config["scenario"], "systemPrompt": prompt,
        "postHistoryInstructions": config.get("postHistoryInstructions", ""),
        "greetings": config["greetings"], "messageExample": [config.get("exampleMessages", [])],
        "tags": config.get("tags", []), "notes": config.get("notes", ""),
        "source": config.get("sourceUrls", []),
        "extensions": {"airi": {
            "avatarModels": [], "modules": copy.deepcopy(config["modules"]), "agents": {},
        }},
    }


def ccv3_card(native: dict) -> dict:
    examples = native["messageExample"][0]
    data = {
        "name": native["name"], "nickname": native["nickname"],
        "description": native["description"], "personality": native["personality"],
        "scenario": native["scenario"], "first_mes": native["greetings"][0],
        "alternate_greetings": native["greetings"][1:], "group_only_greetings": [],
        "mes_example": "<START>\n" + "\n".join(examples) if examples else "",
        "creator_notes": native["notes"], "system_prompt": native["systemPrompt"],
        "post_history_instructions": native["postHistoryInstructions"],
        "tags": native["tags"], "creator": native["creator"],
        "character_version": native["version"], "extensions": native["extensions"],
        "source": native["source"],
    }
    return {"spec": "chara_card_v3", "spec_version": "3.0", "data": data}


def model_archive(path: Path, out: Path, names: list[str]) -> Path:
    """Validate a real model package, optionally build a ZIP from a model directory."""
    if path.is_dir():
        archive = out / "live2d-model.zip"
        if path.resolve() == out.resolve() or path.resolve() in out.resolve().parents:
            raise ValueError("Output directory must be outside the source model directory")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for item in sorted(path.rglob("*")):
                if item.is_file():
                    if item.is_symlink():
                        raise ValueError("Model directory may not contain symlinks")
                    z.write(item, item.relative_to(path).as_posix())
    else:
        archive = path
    with zipfile.ZipFile(archive) as z:
        files = set(z.namelist())
        for name in files:
            p = PurePosixPath(name)
            if p.is_absolute() or ".." in p.parts or "\\" in name or ":" in name:
                raise ValueError("Unsafe archive path")
        settings_paths = [p for p in sorted(files) if p.endswith(".model3.json")]
        if len(settings_paths) != 1:
            raise ValueError("Expected exactly one .model3.json")
        settings_path = PurePosixPath(settings_paths[0])
        settings = json.loads(z.read(str(settings_path)))
        refs = settings.get("FileReferences", {})
        required = [refs.get("Moc", ""), *refs.get("Textures", [])]
        if not refs.get("Moc", "").endswith(".moc3") or not refs.get("Textures"):
            raise ValueError("A real MOC3 and textures are required")
        expressions = {e["Name"]: e["File"] for e in refs.get("Expressions", [])}
        missing_names = set(names) - set(expressions)
        if missing_names:
            raise ValueError("Model lacks requested expression names: " + ", ".join(sorted(missing_names)))
        required += list(expressions.values())
        for group in refs.get("Motions", {}).values():
            required += [entry["File"] for entry in group]
        required += [refs[k] for k in ("Physics", "Pose", "DisplayInfo", "UserData") if refs.get(k)]
        for ref in required:
            rp = PurePosixPath(ref)
            if rp.is_absolute() or ".." in rp.parts or "\\" in ref or ":" in ref:
                raise ValueError("Unsafe model reference")
            key = (settings_path.parent / rp).as_posix()
            if key not in files or not z.read(key):
                raise ValueError("Missing or empty model dependency: " + key)
        moc_path = (settings_path.parent / refs["Moc"]).as_posix()
        if z.read(moc_path)[:4] != b"MOC3":
            raise ValueError("Invalid MOC3 magic; run the separate Core validator as well")
    return archive


def export(config_path: Path, out: Path, model: Path | None = None) -> dict:
    config = load_config(config_path)
    out.mkdir(parents=True, exist_ok=True)
    native = native_card(config)
    v3 = ccv3_card(native)
    v2 = copy.deepcopy(v3)
    v2["spec"], v2["spec_version"] = "chara_card_v2", "2.0"
    # Other frontends do not necessarily consume AIRI ACT tokens. The portable
    # card uses the same persona without AIRI-specific animation instructions.
    v2["data"]["system_prompt"] = config["systemPrompt"]
    for field in ("nickname", "group_only_greetings", "source"):
        v2["data"].pop(field, None)
    prefix = config["id"]
    dump(out / f"{prefix}.airi-native.json", native)
    dump(out / f"{prefix}.ccv3.json", v3)
    dump(out / f"{prefix}.sillytavern-v2.json", v2)
    manifest = {"format": "airi-character-card", "version": 1,
                "card": {"path": "card.json", "spec": "chara_card_v3"}}
    archive = model_archive(model, out, [e["name"] for e in config.get("expressions", [])]) if model else None
    if archive:
        manifest["resources"] = {"displayModel": {
            "path": "models/body-model.zip", "format": "live2d-zip",
            "name": prefix + "-live2d.zip",
            "controls": {"disabledExpressions": [], "disabledMotions": []},
        }}
    dump(out / "manifest.json", manifest)
    package = out / f"{prefix}.airi-card.zip"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        z.writestr("card.json", json.dumps(v3, ensure_ascii=False, indent=2))
        if archive:
            z.write(archive, "models/body-model.zip")
    contract = {"schemaVersion": 1, "characterId": prefix,
                "syntax": '<|ACT {"expression":{"name":"EXACT_NAME","duration":3}}|>',
                "reset": '<|ACT {"expression":null}|>',
                "expressions": config.get("expressions", []),
                "modelIncluded": bool(archive),
                "validation": "Archive paths and dependencies checked; genuine Cubism Core and visual validation must be performed separately."}
    dump(out / "act-contract.json", contract)
    result = {"package": package.name, "modelIncluded": bool(archive), "expressionCount": len(config.get("expressions", []))}
    dump(out / "export-result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", type=Path, help="A verified Live2D model ZIP or directory; omit for card-only package")
    args = parser.parse_args()
    print(json.dumps(export(args.config, args.out, args.model), ensure_ascii=False))
