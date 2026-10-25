#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reproduce the original DeskBot fixture, including project-owned motion3 data."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
TOOL = HERE.parents[1]/"rig-tools/rig.py"


def motion(curves, duration=6, loop=True):
    payload = {"Version": 3, "Meta": {"Duration": duration, "Fps": 30, "Loop": loop,
        "AreBeziersRestricted": True, "CurveCount": len(curves),
        "TotalSegmentCount": sum(len(points)-1 for points in curves.values()),
        "TotalPointCount": sum(len(points) for points in curves.values()),
        "UserDataCount": 0, "TotalUserDataSize": 0},
        "FadeInTime": .25, "FadeOutTime": .25, "Curves": [], "UserData": []}
    for identifier, points in curves.items():
        segments = list(points[0])
        for time, value in points[1:]:
            segments.extend([0, time, value])
        payload["Curves"].append({"Target": "Parameter", "Id": identifier, "Segments": segments})
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--core-file", type=Path)
    parser.add_argument("--node-executable", default="node")
    args = parser.parse_args()
    output = args.out.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error("--out must be absent or empty; existing output is preserved")
    stages = []

    def call(stage, *extra):
        result = subprocess.run([sys.executable, str(TOOL), stage, *map(str, extra), "--json"], capture_output=True, text=True, encoding="utf-8")
        payload = json.loads(result.stdout)
        stages.append({"stage": stage, "ok": payload.get("ok"), "code": payload.get("code")})
        if result.returncode:
            raise RuntimeError(json.dumps({"failedStage": stage, "result": payload}))
        return payload

    call("inspect", "--project", HERE/"project.json")
    call("build", "--project", HERE/"project.json", "--out", output)
    curves = {
        "idle": {"ParamBreath": [(0,0),(1.5,1),(3,0),(4.5,1),(6,0)],
                 "ParamAngleX": [(0,0),(1.5,.25),(3,0),(4.5,-.25),(6,0)],
                 "ParamAngleZ": [(0,0),(1.5,.25),(3,0),(4.5,-.25),(6,0)]},
        "capability-demo": {
            "ParamEyeLOpen": [(0,1),(.8,1),(1,0),(1.2,1),(6,1)],
            "ParamEyeROpen": [(0,1),(1.8,1),(2,0),(2.2,1),(6,1)],
            "ParamMouthOpenY": [(0,0),(2.7,0),(3,1),(3.3,0),(3.6,.75),(3.9,0),(4.2,1),(4.5,0),(6,0)],
            "ParamBreath": [(0,0),(1.5,1),(3,0),(4.5,1),(6,0)]}}
    (output/"motions").mkdir()
    for name, values in curves.items():
        (output/"motions"/(name+".motion3.json")).write_text(json.dumps(motion(values), indent=2)+"\n", encoding="utf-8")
    model = output/"DeskBot.model3.json"
    settings = json.loads(model.read_text(encoding="utf-8"))
    settings["FileReferences"]["Motions"] = {"Idle": [{"File":"motions/idle.motion3.json"}], "Demo": [{"File":"motions/capability-demo.motion3.json"}]}
    model.write_text(json.dumps(settings, indent=2)+"\n", encoding="utf-8")
    if args.core_file:
        validated = call("validate", "--model", model, "--core-file", args.core_file.resolve(), "--node-executable", args.node_executable)
        core = {key: validated["summary"][key] for key in ("status", "meshes", "parameters", "expressions", "geometryCases")}
    else:
        core = {"status": "NOT_PERFORMED", "reason": "Supply your existing licensed --core-file to run Core validation."}
    references = settings["FileReferences"]
    runtime = [model.name, references["Moc"], *references["Textures"],
        *(entry["File"] for entry in references.get("Expressions", [])),
        *(entry["File"] for entries in references["Motions"].values() for entry in entries),
        "build-manifest.json", "TOOL-LICENSE.txt", "THIRD-PARTY-py-moc3-LICENSE.txt"]
    with zipfile.ZipFile(output/"DeskBot.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in runtime:
            archive.write(output/relative, relative)
    report = {"ok": True, "stages": stages, "core": core, "runtimeFiles": runtime,
        "motionGroups": ["Idle", "Demo"], "coreIncluded": False,
        "motionAuthoring": "Project-owned post-build motion3 data; the generic builder schema does not author motions.",
        "unperformed": ["AIRI desktop import, ACT expression and speech/lip-sync integration", "Cubism Editor .cmo3 authoring"]}
    (output/"rebuild-report.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
