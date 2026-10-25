"""Technical crop, alpha mask, placement and atlas preparation. No inpainting."""
from pathlib import Path
import argparse
import hashlib
import json
from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent


def alpha_crop(image, padding=3):
    alpha = image.getchannel("A")
    bbox = alpha.point(lambda value: 255 if value >= 10 else 0).getbbox()
    if bbox is None:
        raise ValueError("Empty transparent source")
    left, top, right, bottom = bbox
    bbox = (max(0, left-padding), max(0, top-padding), min(image.width, right+padding), min(image.height, bottom+padding))
    return image.crop(bbox), bbox


def polygon_alpha(image, points):
    mask = Image.new("L", image.size)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    image.putalpha(ImageChops.multiply(image.getchannel("A"), mask))
    return image


def prepare(spec_path, output=None):
    spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    output = Path(output or (spec_path.parent / "prepared"))
    output.mkdir(exist_ok=True, parents=True)
    asset_root = (spec_path.parent / spec.get("asset_root", ".")).resolve()
    width, height = spec["canvas"]
    files = {}
    for name, file in spec["sources"].items():
        path = (asset_root / file).resolve()
        source = Image.open(path)
        if source.mode != "RGBA":
            raise ValueError(f"Source must have genuine RGBA pixels: {path}")
        files[name] = source.copy()
    overlay_reports = []
    for overlay in spec.get("source_overlays", []):
        target = files[overlay["target"]].copy()
        before = target.copy()
        patch = files[overlay["source"]].copy()
        if "crop" in overlay:
            patch = patch.crop(tuple(overlay["crop"]))
        x, y, patch_width, patch_height = overlay["rect"]
        patch = patch.resize((round(patch_width), round(patch_height)), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", target.size)
        canvas.paste(patch, (round(x), round(y)))
        mask = Image.new("L", target.size)
        drawer = ImageDraw.Draw(mask)
        for points in overlay["polygons"]:
            drawer.polygon([tuple(point) for point in points], fill=255)
        hard_mask = mask.copy()
        if overlay.get("feather", 0):
            mask = ImageChops.multiply(mask.filter(ImageFilter.GaussianBlur(overlay["feather"])), hard_mask)
        target = Image.composite(canvas, target, mask)
        if overlay.get("preserve_target_alpha", True):
            target.putalpha(before.getchannel("A"))
        delta = ImageChops.difference(before, target)
        changed = ImageChops.lighter(ImageChops.lighter(delta.getchannel("R"), delta.getchannel("G")), ImageChops.lighter(delta.getchannel("B"), delta.getchannel("A"))).point(lambda value: 255 if value else 0)
        outside = ImageChops.multiply(changed, ImageChops.invert(hard_mask))
        if outside.getbbox() is not None:
            raise ValueError("Technical source overlay changed pixels outside its explicit mask")
        overlay_reports.append({"target": overlay["target"], "source": overlay["source"], "rect": overlay["rect"], "mask_bbox": hard_mask.getbbox(), "changed_pixels": changed.histogram()[255], "changed_outside_mask": 0, "operation": "Explicit polygon composite of an externally supplied patch. No inpainting or semantic pixel synthesis."})
        files[overlay["target"]] = target
    layers, provenance = [], []
    neutral = Image.new("RGBA", (width, height))
    for layer in spec["layers"]:
        source = files[layer["source"]].copy()
        source_box = [0, 0, source.width, source.height]
        if "cell" in layer:
            column, row = layer["cell"]
            columns, rows = layer.get("grid", spec.get("atlas_grid", [4, 3]))
            source_box = [round(column*source.width/columns), round(row*source.height/rows), round((column+1)*source.width/columns), round((row+1)*source.height/rows)]
            source = source.crop(source_box)
            source, bbox = alpha_crop(source)
        if "polygon" in layer:
            source = polygon_alpha(source, layer["polygon"])
            source, bbox = alpha_crop(source)
            destination = layer.get("rect", [bbox[0], bbox[1], source.width, source.height])
        else:
            destination = layer.get("rect", [0, 0, width, height])
        x, y, target_width, target_height = destination
        source = source.resize((round(target_width), round(target_height)), Image.Resampling.LANCZOS)
        path = output / (layer["id"] + ".png")
        source.save(path)
        record = {**layer, "file": path.relative_to(output).as_posix(), "rect": [x, y, source.width, source.height]}
        layers.append(record)
        provenance.append({"id": layer["id"], "source": spec["sources"][layer["source"]], "source_rect": source_box, "rect": record["rect"], "alpha_extrema": source.getchannel("A").getextrema(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "operation": "RGBA crop/resize; optional explicitly defined polygon alpha mask"})
        if layer.get("neutral_opacity", 1.0) > 0:
            visible = source.copy()
            visible.putalpha(visible.getchannel("A").point(lambda value: round(value*layer.get("neutral_opacity", 1.0))))
            if [round(x), round(y), visible.width, visible.height] == [0, 0, width, height] and neutral.getchannel("A").getbbox() is None:
                neutral = visible.copy()
            else:
                neutral.alpha_composite(visible, (round(x), round(y)))
    spec["layers"] = layers
    (output / "prepared-spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "texture-provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "source-overlay-report.json").write_text(json.dumps(overlay_reports, ensure_ascii=False, indent=2), encoding="utf-8")
    neutral.save(output / "neutral-composite.png")
    checker = Image.new("RGBA", (width, height), "#d4d6df")
    draw = ImageDraw.Draw(checker)
    for y in range(0, height, 64):
        for x in range(0, width, 64):
            if ((x//64)+(y//64)) % 2:
                draw.rectangle((x, y, x+63, y+63), fill="#f4f4f7")
    checker.alpha_composite(neutral)
    checker.convert("RGB").save(output / "neutral-checkerboard.jpg", quality=92)
    return spec, provenance


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result, _ = prepare(args.spec, args.out)
    print(json.dumps({"prepared_layers": len(result["layers"])}))
