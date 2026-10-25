"""Download the pinned MeloTTS conversion and verify every file."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
REPOSITORY = "csukuangfj/vits-melo-tts-zh_en"
REVISION = "a0d5c6a264c0ef92d70d8661d8cc502d79627cd6"
DESTINATION = ROOT / "models" / "melo-zh-en"


def fetch_json(url):
    with urlopen(Request(url, headers={"User-Agent": "AIRI-local-speech-installer"}), timeout=60) as response:
        return json.load(response)


def download(entry):
    path = entry["path"]
    target = DESTINATION / path
    target.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{path}"
    if not target.exists() or target.stat().st_size != entry["size"]:
        temporary = target.with_name(target.name + ".part")
        with urlopen(Request(url, headers={"User-Agent": "AIRI-local-speech-installer"}), timeout=180) as source, temporary.open("wb") as output:
            while block := source.read(1024 * 1024):
                output.write(block)
        temporary.replace(target)
    data = target.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    if len(data) != entry["size"]:
        raise RuntimeError(f"Size mismatch: {path}")
    lfs_sha = (entry.get("lfs") or {}).get("oid")
    git_sha = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    if lfs_sha and sha256 != lfs_sha:
        raise RuntimeError(f"SHA256 mismatch: {path}")
    if not lfs_sha and git_sha != entry["oid"]:
        raise RuntimeError(f"Git blob checksum mismatch: {path}")
    return {"path": path, "size": len(data), "sha256": sha256, "verified_against": "Hugging Face LFS SHA256" if lfs_sha else "Hugging Face Git blob SHA1", "remote_hash": lfs_sha or entry["oid"], "url": url}


if __name__ == "__main__":
    entries = fetch_json(f"https://huggingface.co/api/models/{REPOSITORY}/tree/{REVISION}?recursive=true")
    entries = [entry for entry in entries if entry["type"] == "file" and entry["path"] not in {"model.onnx", ".gitattributes"}]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        verified = list(pool.map(download, entries))
    manifest = {"repository": REPOSITORY, "revision": REVISION, "files": verified}
    (ROOT / "model-source-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Verified {len(verified)} model files, {sum(item['size'] for item in verified):,} bytes.")
