#!/usr/bin/env python3
"""Config-driven MOC3 authoring CLI. Toolkit code is MIT licensed."""
from pathlib import Path, PureWindowsPath
import argparse
import hashlib
import importlib.util
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor" / "py-moc3" / "src"))
from moc3 import Moc3
from moc3._core import SECTION_LAYOUT, ElemType, SectionEntry


class RigError(Exception):
    def __init__(self, code, message, details=None, exit_code=2):
        super().__init__(message)
        self.code, self.details, self.exit_code = code, details, exit_code


def load_project(path):
    try:
        spec = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as error:
        raise RigError("PROJECT_READ", str(error)) from error
    return spec


def validate_schema(value, rule, document, location="$"):
    """Validate the shipped schema's small JSON-Schema vocabulary without dependencies."""
    def fail(message):
        raise RigError("PROJECT_SCHEMA", f"{location}: {message}")
    if "$ref" in rule:
        target = document
        for part in rule["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        return validate_schema(value, target, document, location)
    if "oneOf" in rule:
        matched = 0
        for variant in rule["oneOf"]:
            try:
                validate_schema(value, variant, document, location)
                matched += 1
            except RigError:
                pass
        if matched != 1:
            fail("must match exactly one supported schema variant")
    for variant in rule.get("allOf", []):
        if "if" in variant:
            try:
                validate_schema(value, variant["if"], document, location)
                condition = True
            except RigError:
                condition = False
            if condition and "then" in variant:
                validate_schema(value, variant["then"], document, location)
        else:
            validate_schema(value, variant, document, location)
    kind = rule.get("type")
    checks = {"object": isinstance(value, dict), "array": isinstance(value, list), "string": isinstance(value, str), "integer": isinstance(value, int) and not isinstance(value, bool), "number": isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value), "boolean": isinstance(value, bool)}
    if kind and not checks.get(kind, False):
        fail(f"expected {kind}")
    if "const" in rule and value != rule["const"]:
        fail(f"must equal {rule['const']!r}")
    if "enum" in rule and value not in rule["enum"]:
        fail("unsupported value")
    if isinstance(value, dict):
        if len(value) < rule.get("minProperties", 0) or len(value) > rule.get("maxProperties", math.inf):
            fail("invalid number of object properties")
        for required in rule.get("required", []):
            if required not in value:
                fail(f"missing required field {required}")
        for key, item in value.items():
            if key in rule.get("properties", {}):
                validate_schema(item, rule["properties"][key], document, location+"."+key)
            else:
                additional = rule.get("additionalProperties", True)
                if additional is False:
                    fail(f"unknown field {key}")
                if isinstance(additional, dict):
                    validate_schema(item, additional, document, location+"."+key)
    elif isinstance(value, list):
        if len(value) < rule.get("minItems", 0) or len(value) > rule.get("maxItems", math.inf):
            fail("invalid array length")
        if rule.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            fail("array entries must be unique")
        for index, item in enumerate(value):
            if "items" in rule:
                validate_schema(item, rule["items"], document, f"{location}[{index}]")
    elif isinstance(value, str):
        if len(value) < rule.get("minLength", 0) or len(value) > rule.get("maxLength", math.inf):
            fail("invalid string length")
        if "pattern" in rule and not re.search(rule["pattern"], value):
            fail("invalid identifier or string format")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value) or value < rule.get("minimum", -math.inf) or value > rule.get("maximum", math.inf):
            fail("number is out of range")
        if value <= rule.get("exclusiveMinimum", -math.inf) or value >= rule.get("exclusiveMaximum", math.inf):
            fail("number exceeds its exclusive range")


def inspect_project(project):
    from PIL import Image
    spec = load_project(project)
    schema = json.loads((ROOT/"project.schema.json").read_text(encoding="utf-8"))
    validate_schema(spec, schema, schema)
    allowed = {"version", "name", "canvas", "asset_root", "sources", "source_overlays", "atlas_grid", "atlas_size", "pixels_per_unit", "allow_opaque_sources", "layers", "parameters", "groups", "expressions", "limits", "copyright", "adaptations", "hit_areas"}
    unknown = sorted(set(spec)-allowed)
    if unknown:
        raise RigError("PROJECT_FIELDS", "Unknown project fields", {"fields": unknown})
    if spec.get("version") != 1:
        raise RigError("PROJECT_VERSION", "Project version must be 1")
    name = spec.get("name", "")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,47}", name):
        raise RigError("PROJECT_NAME", "name must be an ASCII identifier of 1 to 48 characters")
    canvas = spec.get("canvas")
    if not isinstance(canvas, list) or len(canvas) != 2 or any(not isinstance(x, int) or x < 32 or x > 8192 for x in canvas):
        raise RigError("CANVAS_INVALID", "canvas must contain two integer dimensions from 32 to 8192")
    asset_root = (project.parent / spec.get("asset_root", ".")).resolve()
    sources, records = spec.get("sources", {}), []
    if not sources:
        raise RigError("SOURCES_EMPTY", "At least one real RGBA PNG source is required")
    for alias, relative in sources.items():
        if not isinstance(relative, str):
            raise RigError("SOURCE_PATH", f"Source {alias} must be a local path string")
        path = asset_root / relative
        if not path.is_file():
            raise RigError("ASSET_MISSING", f"Source {alias} does not exist", {"file": relative})
        try:
            with Image.open(path) as image:
                if image.format != "PNG" or image.mode != "RGBA":
                    raise RigError("ASSET_NOT_RGBA_PNG", f"Source {alias} must be a genuine RGBA PNG")
                extrema = image.getchannel("A").getextrema()
                if extrema[1] == 0 or (extrema[0] == 255 and not spec.get("allow_opaque_sources", False)):
                    raise RigError("ASSET_ALPHA", f"Source {alias} has no usable transparency")
                records.append({"source": alias, "file": relative, "dimensions": list(image.size), "alpha": extrema, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        except RigError:
            raise
        except Exception as error:
            raise RigError("ASSET_DECODE", f"Source {alias} cannot be decoded: {error}") from error
    for overlay in spec.get("source_overlays", []):
        if overlay.get("target") not in sources or overlay.get("source") not in sources:
            raise RigError("OVERLAY_SOURCE", "Technical overlays must refer to existing source aliases")
        if len(overlay.get("rect", [])) != 4 or not overlay.get("polygons"):
            raise RigError("OVERLAY_MASK", "Technical overlays need an explicit rect and polygons")
    parameters = spec.get("parameters", [])
    ids = [item.get("id") for item in parameters]
    if len(set(ids)) != len(ids):
        raise RigError("PARAMETER_DUPLICATE", "Parameter IDs must be unique")
    for parameter in parameters:
        if not isinstance(parameter.get("id"), str) or len(parameter["id"].encode()) > 63:
            raise RigError("PARAMETER_ID", "Parameter IDs must fit the 63-byte MOC3 ID field")
        keys = parameter.get("keys", [parameter.get("min"), parameter.get("default"), parameter.get("max")])
        keys = sorted(set(keys))
        if len(keys) < 2 or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in keys):
            raise RigError("PARAMETER_KEYS", f"Invalid keys for {parameter['id']}")
        if not parameter["min"] <= parameter["default"] <= parameter["max"]:
            raise RigError("PARAMETER_RANGE", f"Invalid range for {parameter['id']}")
        if keys[0] != parameter["min"] or keys[-1] != parameter["max"] or parameter["default"] not in keys:
            raise RigError("PARAMETER_KEY_RANGE", f"Keys for {parameter['id']} must include min, max and default")
        parameter["keys"] = keys
    layers = spec.get("layers", [])
    layer_ids = [item.get("id") for item in layers]
    if not layers or len(set(layer_ids)) != len(layer_ids):
        raise RigError("LAYER_IDS", "The project needs layers with unique IDs")
    used = set()
    groups = spec.get("groups", {})
    for layer in layers:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,62}", layer.get("id", "")):
            raise RigError("LAYER_ID", "Layer IDs must be ASCII identifiers of 1 to 63 characters")
        if layer.get("source") not in sources:
            raise RigError("LAYER_SOURCE", f"Missing source alias for {layer['id']}")
        if layer.get("group") and layer["group"] not in groups:
            raise RigError("LAYER_GROUP", f"Unknown group on {layer['id']}")
        if "rect" in layer and (len(layer["rect"]) != 4 or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in layer["rect"]) or layer["rect"][2] <= 0 or layer["rect"][3] <= 0):
            raise RigError("LAYER_RECT", f"Invalid rect on {layer['id']}")
        if "cell" in layer:
            grid = layer.get("grid", spec.get("atlas_grid", [4, 3]))
            if len(layer["cell"]) != 2 or len(grid) != 2 or any(not isinstance(value, int) or value < 0 or value >= grid[index] for index, value in enumerate(layer["cell"])):
                raise RigError("ATLAS_CELL", f"Invalid cell on {layer['id']}")
        mesh = layer.get("mesh", [4, 4])
        if len(mesh) != 2 or any(not isinstance(value, int) or not 1 <= value <= 128 for value in mesh):
            raise RigError("MESH_SIZE", f"Invalid mesh on {layer['id']}")
        effects = {**layer.get("effects", {}), **groups.get(layer.get("group"), {}).get("effects", {})}
        if any(parameter not in ids for parameter in effects):
            raise RigError("EFFECT_PARAMETER", f"Unknown parameter on {layer['id']}")
        used.update(effects)
        for operations in effects.values():
            for operation in (operations if isinstance(operations, list) else [operations]):
                if operation.get("type") not in {"translate", "rotate", "scale", "aperture", "curve", "opacity", "multiply_color"}:
                    raise RigError("EFFECT_TYPE", f"Unknown effect type on {layer['id']}")
                if operation["type"] == "opacity" and (not isinstance(operation.get("points"), list) or len(operation["points"]) < 2):
                    raise RigError("OPACITY_POINTS", f"Opacity on {layer['id']} needs at least two points")
        keyforms = math.prod(len(parameters[ids.index(parameter)]["keys"]) for parameter in effects)
        if keyforms > spec.get("limits", {}).get("keyforms_per_mesh", 10000):
            raise RigError("KEYFORM_LIMIT", f"Too many parameter combinations for {layer['id']}", {"keyforms": keyforms})
    unused = sorted(set(ids)-used)
    if unused:
        raise RigError("PARAMETER_UNBOUND", "Parameters without real layer effects are not allowed", {"parameters": unused})
    expression_names = []
    for expression in spec.get("expressions", []):
        expression_names.append(expression["name"])
        if any(key not in ids for key in expression.get("values", {})):
            raise RigError("EXPRESSION_PARAMETER", f"Unknown parameter in {expression['name']}")
        for key, value in expression.get("values", {}).items():
            parameter = parameters[ids.index(key)]
            if not isinstance(value, (int, float)) or not parameter["min"] <= value <= parameter["max"]:
                raise RigError("EXPRESSION_RANGE", f"Value out of range in {expression['name']}: {key}")
    if len(expression_names) != len(set(expression_names)):
        raise RigError("EXPRESSION_DUPLICATE", "Expression names must be unique")
    masks = {item["id"]: item.get("masks", []) for item in layers}
    def visit_mask(identifier, stack):
        if identifier not in masks:
            raise RigError("MASK_LAYER", f"Unknown mask {identifier}")
        if identifier in stack:
            raise RigError("MASK_CYCLE", f"Cyclic clipping masks: {identifier}")
        for child in masks[identifier]:
            visit_mask(child, stack+[identifier])
    for identifier in masks:
        visit_mask(identifier, [])
    for hit in spec.get("hit_areas", []):
        if hit.get("Id") not in layer_ids:
            raise RigError("HIT_AREA_LAYER", "HitAreas must refer to actual drawable layer IDs")
    return spec, {"name": name, "sources": records, "layers": len(layers), "parameters": len(parameters), "expressions": expression_names}


def interpolate(points, value):
    points = sorted(points)
    if value <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if value <= x1:
            return y0+(y1-y0)*(value-x0)/(x1-x0)
    return points[-1][1]


def apply_effects(points, layer, values, parameter_map, groups):
    x0, y0, width, height = layer["rect"]
    opacity = layer.get("opacity", 1.0)
    color = [1.0, 1.0, 1.0]
    # Local facial operations run before the shared pose deformation.
    effects = [layer.get("effects", {}), groups.get(layer.get("group"), {}).get("effects", {})]
    result = list(points)
    for effect_set in effects:
        for identifier, operations in effect_set.items():
            operations = operations if isinstance(operations, list) else [operations]
            parameter, value = parameter_map[identifier], values[identifier]
            side = parameter["max"]-parameter["default"] if value >= parameter["default"] else parameter["default"]-parameter["min"]
            normalized = (value-parameter["default"])/side if side else 0.0
            for operation in operations:
                kind = operation["type"]
                amount = value if operation.get("value_mode") == "raw" else normalized
                if kind == "opacity":
                    opacity *= interpolate(operation["points"], value)
                    continue
                if kind == "multiply_color":
                    mapped = [interpolate(channel, value) for channel in operation["channels"]]
                    color = [a*b for a, b in zip(color, mapped)]
                    continue
                changed = []
                for x, y in result:
                    weight = 1.0
                    if "weight_y" in operation:
                        full, zero = operation["weight_y"]
                        t = max(0.0, min(1.0, (y-full)/(zero-full)))
                        weight = 1-t*t*(3-2*t)
                    if "weight_rect" in operation:
                        left, top, right, bottom, feather = operation["weight_rect"]
                        distance = min(x-left, right-x, y-top, bottom-y)
                        t = max(0.0, min(1.0, distance/feather)) if feather else float(distance >= 0)
                        weight *= t*t*(3-2*t)
                    pivot_x, pivot_y = operation.get("pivot", [x0+width/2, y0+height/2])
                    if kind == "translate":
                        x += operation.get("x", 0)*amount*weight
                        y += operation.get("y", 0)*amount*weight
                    elif kind == "rotate":
                        angle = math.radians(operation.get("degrees", 0)*amount*weight)
                        dx, dy = x-pivot_x, y-pivot_y
                        x, y = pivot_x+dx*math.cos(angle)-dy*math.sin(angle), pivot_y+dx*math.sin(angle)+dy*math.cos(angle)
                    elif kind == "scale":
                        x = pivot_x+(x-pivot_x)*(1+operation.get("x", 0)*amount*weight)
                        y = pivot_y+(y-pivot_y)*(1+operation.get("y", 0)*amount*weight)
                    elif kind == "aperture":
                        factor = interpolate(operation.get("points", [[parameter['min'], .03], [parameter['max'], 1]]), value)
                        y = pivot_y+(y-pivot_y)*max(.01, factor)
                    elif kind == "curve":
                        u = (x-x0)/width
                        y += operation.get("bend", 0)*amount*4*(u-.5)**2
                    else:
                        raise RigError("EFFECT_TYPE", f"Unsupported effect type {kind}")
                    changed.append((x, y))
                result = changed
    return result, max(0.0, min(1.0, opacity)), color


def pack_atlas(layers, prepared, output, size):
    from PIL import Image
    pages = [Image.new("RGBA", (size, size))]
    page, x, y, row_height, padding = 0, 4, 4, 0, 4
    placements = {}
    ordered = sorted(layers, key=lambda item: Image.open(prepared/item["file"]).height, reverse=True)
    for layer in ordered:
        image = Image.open(prepared/layer["file"]).convert("RGBA")
        if image.width+8 > size or image.height+8 > size:
            raise RigError("ATLAS_SIZE", f"Layer {layer['id']} does not fit atlas size {size}")
        if x+image.width+padding > size:
            x, y, row_height = padding, y+row_height+padding, 0
        if y+image.height+padding > size:
            page += 1
            pages.append(Image.new("RGBA", (size, size)))
            x, y, row_height = padding, padding, 0
        pages[page].paste(image, (x, y))
        placements[layer["id"]] = [page, x, y, image.width, image.height]
        x, row_height = x+image.width+padding, max(row_height, image.height)
    texture_paths = []
    (output/"textures").mkdir(exist_ok=True)
    for index, image in enumerate(pages):
        path = output/"textures"/f"texture_{index:02d}.png"
        image.save(path)
        texture_paths.append(path.relative_to(output).as_posix())
    return placements, texture_paths


def serialize_model(spec, placements, output):
    layout = list(SECTION_LAYOUT)
    layout[41], layout[44] = layout[44], layout[41]
    layout[82], layout[83] = layout[83], layout[82]
    m, layers, parameters = Moc3(), spec["layers"], spec["parameters"]
    width, height = spec["canvas"]
    unit = spec.get("pixels_per_unit", 1024)
    m.canvas.pixels_per_unit, m.canvas.origin_x, m.canvas.origin_y = unit, width/2, height/2
    m.canvas.canvas_width, m.canvas.canvas_height = width, height
    groups = spec.get("groups", {})
    parameter_map = {item["id"]: item for item in parameters}
    slots = {entry.name: [] for entry in layout if entry.elem_type != ElemType.RUNTIME}
    def put(key, value):
        slots[key] = value
    bindings = [item["id"] for item in parameters]
    binding_indices, binding_band_starts, binding_band_counts = [], [], []
    keys, binding_key_starts, binding_key_counts = [], [], []
    for parameter in parameters:
        binding_key_starts.append(len(keys))
        binding_key_counts.append(len(parameter["keys"]))
        keys.extend(parameter["keys"])
    uv, indices, positions, masks = [], [], [], []
    mask_starts, mask_counts = [], []
    vertex_counts, index_counts, uv_starts, index_starts = [], [], [], []
    keyform_starts, keyform_counts, position_starts, orders, opacities, colors = [], [], [], [], [], []
    dependency_map = {}
    for layer_index, layer in enumerate(layers):
        mask_starts.append(len(masks))
        mask_counts.append(len(layer.get("masks", [])))
        for mask in layer.get("masks", []):
            if mask not in [item["id"] for item in layers]:
                raise RigError("MASK_LAYER", f"Unknown mask {mask} on {layer['id']}")
            masks.append([item["id"] for item in layers].index(mask))
        local_effects = layer.get("effects", {})
        global_effects = groups.get(layer.get("group"), {}).get("effects", {})
        identifiers = list(dict.fromkeys([*local_effects, *global_effects]))
        dependency_map[layer["id"]] = identifiers
        binding_band_starts.append(len(binding_indices))
        binding_band_counts.append(len(identifiers))
        for identifier in identifiers:
            binding_indices.append(bindings.index(identifier))
        columns, rows = layer.get("mesh", [4, 4])
        if columns < 1 or rows < 1 or (columns+1)*(rows+1) >= 32768:
            raise RigError("MESH_SIZE", f"Invalid mesh grid on {layer['id']}")
        left, top, layer_width, layer_height = layer["rect"]
        points = [(left+layer_width*x/columns, top+layer_height*y/rows) for y in range(rows+1) for x in range(columns+1)]
        page, texture_x, texture_y, texture_width, texture_height = placements[layer["id"]]
        atlas_size = spec.get("atlas_size", 2048)
        uv_starts.append(len(uv))
        for row in range(rows+1):
            for column in range(columns+1):
                # Core converts the source V coordinate; Cubism's WebGL shader
                # reverses that conversion. Source data therefore stays PNG top-down.
                uv.extend([(texture_x+texture_width*column/columns)/atlas_size, (texture_y+texture_height*row/rows)/atlas_size])
        index_starts.append(len(indices))
        for row in range(rows):
            for column in range(columns):
                a = row*(columns+1)+column
                b, c, d = a+1, a+columns+1, a+columns+2
                indices.extend([a, c, b, b, c, d])
        vertex_counts.append(len(points))
        index_counts.append(columns*rows*6)
        keyform_starts.append(len(position_starts))
        # MOC3 binding bands use the first parameter as the fastest-varying axis.
        combinations = [tuple(reversed(values)) for values in itertools.product(*(parameter_map[identifier]["keys"] for identifier in reversed(identifiers)))]
        keyform_counts.append(len(combinations))
        for combination in combinations:
            values = dict(zip(identifiers, combination))
            changed, opacity, color = apply_effects(points, layer, values, parameter_map, groups)
            xys = [coordinate for x, y in changed for coordinate in ((x-width/2)/unit, (y-height/2)/unit)]
            position_starts.append(len(positions))
            positions.extend(xys+[0.0]*len(xys))
            orders.append(float(layer_index))
            opacities.append(opacity)
            colors.append(color)
    parameter_starts = list(range(len(parameters)))
    parameter_counts = [1]*len(parameters)
    count = len(layers)
    m.counts[4:6] = [count, len(parameters)]
    m.counts[9:20] = [len(position_starts), len(positions), len(binding_indices), count, len(bindings), len(keys)+sum(len(p["keys"]) for p in parameters), len(uv), len(indices), len(masks), 1, count]
    put("art_mesh.ids", [layer["id"] for layer in layers])
    put("art_mesh.keyform_binding_band_indices", list(range(count)))
    put("art_mesh.keyform_begin_indices", keyform_starts)
    put("art_mesh.keyform_counts", keyform_counts)
    for key in ("visibles", "enables"):
        put("art_mesh."+key, [True]*count)
    for key in ("parent_part_indices", "parent_deformer_indices"):
        put("art_mesh."+key, [-1]*count)
    put("art_mesh.texture_indices", [placements[layer["id"]][0] for layer in layers])
    put("art_mesh.drawable_flags", [4]*count)
    put("art_mesh.position_index_counts", index_counts)
    put("art_mesh.vertex_counts", vertex_counts)
    put("art_mesh.uv_begin_indices", uv_starts)
    put("art_mesh.position_index_begin_indices", index_starts)
    put("art_mesh.mask_begin_indices", mask_starts)
    put("art_mesh.mask_counts", mask_counts)
    put("drawable_mask.art_mesh_indices", masks)
    put("uv.xys", uv)
    put("position_index.indices", indices)
    put("keyform_position.xys", positions)
    put("art_mesh_keyform.keyform_position_begin_indices", position_starts)
    put("art_mesh_keyform.opacities", opacities)
    put("art_mesh_keyform.draw_orders", orders)
    for field in ("ids", "min_values", "max_values", "default_values"):
        source = {"ids": "id", "min_values": "min", "max_values": "max", "default_values": "default"}[field]
        put("parameter."+field, [parameter[source] for parameter in parameters])
    put("parameter.repeats", [False]*len(parameters))
    put("parameter.decimal_places", [3]*len(parameters))
    put("parameter.keyform_binding_begin_indices", parameter_starts)
    put("parameter.keyform_binding_counts", parameter_counts)
    put("keyform_binding_index.indices", binding_indices)
    put("keyform_binding_band.begin_indices", binding_band_starts)
    put("keyform_binding_band.counts", binding_band_counts)
    put("keyform_binding.keys_begin_indices", binding_key_starts)
    put("keyform_binding.keys_counts", binding_key_counts)
    put("draw_order_group.object_begin_indices", [0])
    put("draw_order_group.object_counts", [count])
    put("draw_order_group.object_total_counts", [count])
    put("draw_order_group.min_draw_orders", [0])
    put("draw_order_group.max_draw_orders", [count-1])
    put("draw_order_group_object.types", [0]*count)
    put("draw_order_group_object.indices", list(range(count)))
    put("draw_order_group_object.group_indices", [-1]*count)
    for entry in layout:
        if entry.elem_type != ElemType.RUNTIME:
            m[entry.name] = slots[entry.name] or [("" if entry.elem_type == ElemType.STR64 else 0)]*m.counts[entry.count_idx]
    extra = []
    for slot in range(101, 137):
        element_type = ElemType.F32 if slot in list(range(108,114))+[135,136] else ElemType.I32
        extra.append(SectionEntry("v42."+str(slot), element_type, -1, 64))
        m["v42."+str(slot)] = []
    extra[1] = SectionEntry("v42.102", ElemType.RUNTIME, 5, 64)
    m.header.version = 4
    m._build_layout = lambda: layout+extra
    m.counts.extend([len(position_starts), len(position_starts)]+[0]*7)
    parameter_key_starts = []
    for parameter in parameters:
        parameter_key_starts.append(len(keys))
        keys.extend(parameter["keys"])
    m["keys.values"] = keys
    m["v42.103"] = parameter_key_starts
    m["v42.104"] = [len(parameter["keys"]) for parameter in parameters]
    m["v42.107"] = keyform_starts
    for channel, slot in enumerate(range(108, 111)):
        m["v42."+str(slot)] = [color[channel] for color in colors]
    for slot in range(111, 114):
        m["v42."+str(slot)] = [0.0]*len(position_starts)
    for slot in range(114, 117):
        m["v42."+str(slot)] = [0]*len(parameters)
    model_path = output/(spec["name"]+".moc3")
    m.to_file(model_path)
    return {"moc": model_path.name, "mesh_dependencies": dependency_map, "vertex_counts": vertex_counts, "index_counts": index_counts, "keyform_counts": keyform_counts, "moc_bytes": model_path.stat().st_size}


def build_project(project, output):
    spec, inspected = inspect_project(project)
    output.mkdir(parents=True, exist_ok=True)
    helper_spec = importlib.util.spec_from_file_location("rig_asset_tools", ROOT/"prepare-assets.py")
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    prepared = output/"authoring"
    spec, provenance = helper.prepare(project, prepared)
    # inspect normalized key arrays survive the independent preprocessing read.
    normalized, _ = inspect_project(project)
    spec["parameters"] = normalized["parameters"]
    placements, textures = pack_atlas(spec["layers"], prepared, output, spec.get("atlas_size", 2048))
    summary = serialize_model(spec, placements, output)
    references = {"Moc": summary["moc"], "Textures": textures}
    expression_files = []
    if spec.get("expressions"):
        (output/"expressions").mkdir(exist_ok=True)
        for index, expression in enumerate(spec["expressions"]):
            file = f"expressions/expression_{index+1:02d}.exp3.json"
            payload = {"Type": "Live2D Expression", "FadeInTime": .25, "FadeOutTime": .35, "Parameters": [{"Id": key, "Value": value, "Blend": "Overwrite"} for key, value in expression["values"].items()]}
            (output/file).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            expression_files.append({"Name": expression["name"], "File": file})
        references["Expressions"] = expression_files
    parameters = {parameter["id"] for parameter in spec["parameters"]}
    groups = []
    for name, candidates in (("EyeBlink", ["ParamEyeLOpen", "ParamEyeROpen"]), ("LipSync", ["ParamMouthOpenY"])):
        if set(candidates) <= parameters:
            groups.append({"Target": "Parameter", "Name": name, "Ids": candidates})
    model_settings = {"Version": 3, "FileReferences": references, "Groups": groups}
    if spec.get("hit_areas"):
        model_settings["HitAreas"] = spec["hit_areas"]
    model_file = output/(spec["name"]+".model3.json")
    model_file.write_text(json.dumps(model_settings, ensure_ascii=False, indent=2), encoding="utf-8")
    parameter_map = {item["id"]: item for item in spec["parameters"]}
    defaults = {key: value["default"] for key, value in parameter_map.items()}
    states = [{"name": "default", "values": {}}]
    for parameter in spec["parameters"]:
        for endpoint in ("min", "max"):
            states.append({"name": parameter["id"]+":"+endpoint, "values": {parameter["id"]: parameter[endpoint]}})
    for state in states:
        state["meshes"] = []
        values = {**defaults, **state["values"]}
        for layer in spec["layers"]:
            columns, rows = layer.get("mesh", [4, 4])
            x, y, w, h = layer["rect"]
            points = [(x+w*c/columns, y+h*r/rows) for r in range(rows+1) for c in range(columns+1)]
            probes = sorted(set([0, len(points)//2, len(points)-1]))
            changed, opacity, _ = apply_effects(points, layer, values, parameter_map, spec.get("groups", {}))
            unit = spec.get("pixels_per_unit", 1024)
            expected = [[(changed[index][0]-spec["canvas"][0]/2)/unit, -(changed[index][1]-spec["canvas"][1]/2)/unit] for index in probes]
            state["meshes"].append({"id": layer["id"], "indices": probes, "positions": expected, "opacity": opacity})
    manifest = {"tool": "config-driven-moc3-rig", "version": 1, "name": spec["name"], "canvas": spec["canvas"], "pixels_per_unit": spec.get("pixels_per_unit", 1024), "model": model_file.name, **summary, "parameters": spec["parameters"], "expressions": spec.get("expressions", []), "textures": textures, "atlas_placements": placements, "art_provenance": provenance, "source_project": project.name, "copyright": spec.get("copyright", {}), "expected_probes": states, "validation": "Run validate with an existing licensed Core. Build success alone is not runtime or visual certification."}
    (output/"build-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copyfile(ROOT/"LICENSE", output/"TOOL-LICENSE.txt")
    shutil.copyfile(ROOT/"vendor/py-moc3/LICENSE", output/"THIRD-PARTY-py-moc3-LICENSE.txt")
    runtime_files = [model_file.name, summary["moc"], *textures, *(item["File"] for item in expression_files), "build-manifest.json", "TOOL-LICENSE.txt", "THIRD-PARTY-py-moc3-LICENSE.txt"]
    archive = output/(spec["name"]+".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
        for file in runtime_files:
            package.write(output/file, file)
    return {"model": str(model_file.resolve()), "moc_bytes": summary["moc_bytes"], "meshes": len(spec["layers"]), "parameters": len(spec["parameters"]), "expressions": len(expression_files), "zip": str(archive.resolve())}, [str((output/file).resolve()) for file in runtime_files]+[str(archive.resolve())]


def runtime_references(model):
    """Read every model3 runtime reference before invoking Core. Does not write."""
    try:
        settings = json.loads(model.read_text(encoding="utf-8-sig"))
    except Exception as error:
        raise RigError("MODEL_READ", str(error), exit_code=4) from error
    references = settings.get("FileReferences")
    if not isinstance(references, dict) or not isinstance(references.get("Moc"), str):
        raise RigError("MODEL_REFERENCES", "model3 needs a FileReferences.Moc path", exit_code=4)
    if not isinstance(references.get("Textures"), list) or not references["Textures"] or any(not isinstance(item, str) for item in references["Textures"]):
        raise RigError("MODEL_REFERENCES", "model3 needs a nonempty FileReferences.Textures path array", exit_code=4)
    paths = []
    def collect(value, location):
        if isinstance(value, str):
            paths.append((location, value))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                collect(item, f"{location}[{index}]")
        elif isinstance(value, dict):
            for key, item in value.items():
                if key not in {"Name", "FadeInTime", "FadeOutTime"}:
                    collect(item, location+"."+key)
    collect(references, "FileReferences")
    root = model.parent.resolve()
    resolved = []
    for location, relative in paths:
        windows = PureWindowsPath(relative)
        if not relative or ":" in relative or "\\" in relative or Path(relative).is_absolute() or windows.is_absolute() or ".." in Path(relative).parts:
            raise RigError("RUNTIME_REFERENCE_UNSAFE", f"Unsafe runtime path at {location}", {"reference": relative}, 4)
        target = (root/relative).resolve()
        if not target.is_relative_to(root):
            raise RigError("RUNTIME_REFERENCE_UNSAFE", f"Runtime path escapes the model directory: {relative}", exit_code=4)
        if not target.is_file() or target.stat().st_size == 0:
            raise RigError("RUNTIME_REFERENCE_MISSING", f"Missing or empty runtime dependency: {relative}", {"location": location, "reference": relative}, 4)
        resolved.append({"location": location, "file": relative, "bytes": target.stat().st_size})
        try:
            if target.suffix.lower() == ".json":
                json.loads(target.read_text(encoding="utf-8-sig"))
            elif target.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                from PIL import Image
                with Image.open(target) as image:
                    image.verify()
        except Exception as error:
            raise RigError("RUNTIME_REFERENCE_INVALID", f"Invalid runtime dependency: {relative}: {error}", exit_code=4) from error
    return resolved


def validate_model(model, core_file, node_executable, report_dir=None):
    dependencies = runtime_references(model)
    if not core_file or not core_file.is_file():
        raise RigError("CORE_MISSING", "Supply an existing licensed Cubism Core JavaScript file with --core-file or LIVE2D_CORE_FILE", exit_code=4)
    command = [node_executable, str(ROOT/"validate_core.cjs"), "--model", str(model), "--core-file", str(core_file)]
    if report_dir:
        command.extend(["--report-dir", str(report_dir)])
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=180)
    except Exception as error:
        raise RigError("CORE_EXECUTION", str(error), exit_code=4) from error
    if result.returncode:
        raise RigError("CORE_VALIDATION", result.stderr.strip() or result.stdout.strip(), exit_code=4)
    try:
        report = json.loads(result.stdout)
    except ValueError as error:
        raise RigError("CORE_OUTPUT", "Validator did not return JSON", {"stdout": result.stdout, "stderr": result.stderr}, 4) from error
    report["runtime_references"] = dependencies
    if report_dir:
        (report_dir/"core-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report, [str(report_dir/"core-validation.json"), str(report_dir/"core-poses.json")] if report_dir else []


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    class JsonArgumentParser(argparse.ArgumentParser):
        def error(self, message):
            print(json.dumps({"ok": False, "stage": "arguments", "code": "ARGUMENT_INVALID", "message": message, "outputs": []}))
            self.exit(2)
    parser = JsonArgumentParser(description="Build real MOC3 rigs from explicit transparent layers and JSON authoring data")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "build"):
        command = subparsers.add_parser(name)
        command.add_argument("--project", type=Path, required=True)
        command.add_argument("--json", action="store_true")
        if name == "build":
            command.add_argument("--out", type=Path, required=True)
    command = subparsers.add_parser("validate")
    command.add_argument("--model", type=Path, required=True)
    command.add_argument("--core-file", type=Path, default=os.environ.get("LIVE2D_CORE_FILE"))
    command.add_argument("--node-executable", default=os.environ.get("NODE", "node"))
    command.add_argument("--report-dir", type=Path, help="Optional report output. Without this option validation does not write files.")
    command.add_argument("--json", action="store_true")
    command = subparsers.add_parser("init")
    command.add_argument("--out", type=Path, required=True)
    command.add_argument("--name", default="RobotDemo")
    command.add_argument("--json", action="store_true")
    command = subparsers.add_parser("render", help="Optional isolated visual proof with an existing AIRI Pixi/Electron installation")
    command.add_argument("--model", type=Path, required=True)
    command.add_argument("--core-file", type=Path, required=True)
    command.add_argument("--renderer-dir", type=Path, required=True)
    command.add_argument("--electron-executable", type=Path, required=True)
    command.add_argument("--out", type=Path, required=True)
    command.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "inspect":
            _, summary = inspect_project(args.project.resolve())
            outputs = []
        elif args.command == "build":
            summary, outputs = build_project(args.project.resolve(), args.out.resolve())
        elif args.command == "validate":
            summary, outputs = validate_model(args.model.resolve(), args.core_file.resolve() if args.core_file else None, args.node_executable, args.report_dir.resolve() if args.report_dir else None)
        elif args.command == "render":
            environment = dict(os.environ)
            environment.pop("ELECTRON_RUN_AS_NODE", None)
            result = subprocess.run([str(args.electron_executable.resolve()), str(ROOT/"render_airi_offscreen.cjs"), "--model", str(args.model.resolve()), "--core-file", str(args.core_file.resolve()), "--renderer-dir", str(args.renderer_dir.resolve()), "--out", str(args.out.resolve())], capture_output=True, text=True, encoding="utf-8", timeout=150, env=environment)
            if result.returncode:
                raise RigError("RENDER_FAILED", result.stderr[-6000:], exit_code=4)
            rendered = json.loads(result.stdout.strip())
            summary, outputs = {"renderer": "Actual AIRI Pixi/Cubism WebGL, offscreen Electron", "frames": len(rendered["outputs"])}, rendered["outputs"]
        else:
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,47}", args.name):
                raise RigError("PROJECT_NAME", "The template name must be a safe ASCII identifier")
            if args.out.exists() and any(args.out.iterdir()):
                raise RigError("INIT_EXISTS", "init requires an absent or empty output directory")
            shutil.copytree(ROOT/"examples/robot", args.out, dirs_exist_ok=True)
            project = args.out/"project.json"
            spec = load_project(project)
            spec["name"] = args.name
            project.write_text(json.dumps(spec, indent=2), encoding="utf-8")
            summary, outputs = {"project": str(project.resolve()), "name": args.name}, [str(path.resolve()) for path in args.out.rglob("*") if path.is_file()]
        payload = {"ok": True, "stage": args.command, "code": "OK", "outputs": outputs, "summary": summary}
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return 0
    except RigError as error:
        print(json.dumps({"ok": False, "stage": args.command, "code": error.code, "message": str(error), "details": error.details, "outputs": []}, ensure_ascii=False))
        return error.exit_code
    except Exception as error:
        print(json.dumps({"ok": False, "stage": args.command, "code": "BUILD_INTERNAL" if args.command == "build" else "INTERNAL", "message": str(error), "outputs": []}, ensure_ascii=False))
        return 3


if __name__ == "__main__":
    sys.exit(main())
