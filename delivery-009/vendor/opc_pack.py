#!/usr/bin/env python3
"""Build one deterministic VIDEO-ID-DELIVERY.zip for one video (OPC R2 delivery format).

ZIP layout (exactly four entries, stored, fixed timestamps, fixed order):

    VIDEO-ID/VIDEO-ID.mp4
    VIDEO-ID/cover.jpg
    VIDEO-ID/weibo.txt
    VIDEO-ID/subtitle.srt

The same inputs always give the same ZIP bytes, so the ZIP SHA256 can be recorded
before publishing and re-checked after any rebuild. Input files are copied byte for
byte (no re-encode, no text normalisation).

Usage:
    python3 opc_pack.py --id VAR-011 --mp4 a.mp4 --cover c.jpg --weibo w.txt --srt s.srt \
        --out OUTDIR [--require-1920x1080]
Writes OUTDIR/VIDEO-ID/VIDEO-ID-DELIVERY.zip and OUTDIR/VIDEO-ID/video-entry.json
(the R2 `videos[]` entry for delivery-manifest.json: video_id, asset_name, size_bytes,
sha256, files).
"""
import argparse, hashlib, json, os, re, subprocess, sys, zipfile

SCHEMA_VERSION = 1
FIXED_TIME = (2026, 10, 13, 0, 0, 0)  # delivery system start date; keeps ZIP bytes reproducible
# same pattern as the original R2 DOWNLOAD.ps1 ($id -notmatch ...), so every id we pack is accepted there
ID_RE = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+)*$")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_type,codec_name,width,height:format=duration",
                          "-of", "json", path], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def check_inputs(vid, src, require_hd):
    problems = []
    mp4 = probe(src["mp4"])
    kinds = {s["codec_type"] for s in mp4.get("streams", [])}
    if not {"video", "audio"} <= kinds:
        problems.append("mp4 lacks a video or audio stream")
    cover = probe(src["cover"])["streams"][0]
    if require_hd and (cover.get("width"), cover.get("height")) != (1920, 1080):
        problems.append(f'cover is {cover.get("width")}x{cover.get("height")}, expected 1920x1080')
    for key in ("weibo", "srt"):
        try:
            text = open(src[key], encoding="utf-8-sig").read()
        except UnicodeDecodeError:
            problems.append(f"{key} is not UTF-8")
            continue
        if not text.strip():
            problems.append(f"{key} is empty")
    if not re.search(r"\d\d:\d\d:\d\d,\d\d\d --> \d\d:\d\d:\d\d,\d\d\d", open(src["srt"], encoding="utf-8-sig").read()):
        problems.append("subtitle.srt has no SRT timing lines")
    return problems, float(mp4["format"]["duration"])


def build(vid, src, outdir, require_hd=True):
    if not ID_RE.match(vid):
        raise SystemExit(f"invalid video id: {vid}")
    problems, duration = check_inputs(vid, src, require_hd)
    if problems:
        raise SystemExit(f"{vid}: input check failed: " + "; ".join(problems))
    entries = [(f"{vid}.mp4", src["mp4"]), ("cover.jpg", src["cover"]),
               ("weibo.txt", src["weibo"]), ("subtitle.srt", src["srt"])]
    pkg_dir = os.path.join(outdir, vid)
    os.makedirs(pkg_dir, exist_ok=True)
    asset_name = f"{vid}-DELIVERY.zip"
    zip_path = os.path.join(pkg_dir, asset_name)
    tmp = zip_path + ".tmp"
    files = []
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as z:
        for name, path in entries:
            size = os.path.getsize(path)
            zi = zipfile.ZipInfo(f"{vid}/{name}", date_time=FIXED_TIME)
            zi.compress_type = zipfile.ZIP_STORED
            zi.create_system = 3
            zi.external_attr = 0o100644 << 16
            h = hashlib.sha256()
            with open(path, "rb") as fin, z.open(zi, "w", force_zip64=size >= (1 << 31)) as fout:
                for block in iter(lambda: fin.read(1 << 20), b""):
                    h.update(block)
                    fout.write(block)
            # original R2 files[] fields only: name, size_bytes, sha256
            files.append(dict(name=name, size_bytes=size, sha256=h.hexdigest()))
    os.replace(tmp, zip_path)
    # re-open and confirm every entry reads back byte-exact
    with zipfile.ZipFile(zip_path) as z:
        names = [i.filename for i in z.infolist()]
        if names != [f"{vid}/{f['name']}" for f in files]:
            raise SystemExit(f"{vid}: zip entry list mismatch {names}")
        for f in files:
            h = hashlib.sha256()
            with z.open(f"{vid}/{f['name']}") as fin:
                for block in iter(lambda: fin.read(1 << 20), b""):
                    h.update(block)
            if h.hexdigest() != f["sha256"]:
                raise SystemExit(f'{vid}: read-back hash mismatch for {f["name"]}')
    entry = dict(video_id=vid, asset_name=asset_name, size_bytes=os.path.getsize(zip_path),
                 sha256=sha256_file(zip_path), files=files)
    with open(os.path.join(pkg_dir, "video-entry.json"), "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return entry


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--id", required=True)
    for k in ("mp4", "cover", "weibo", "srt"):
        ap.add_argument("--" + k, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--allow-non-hd-cover", action="store_true", help="skip the 1920x1080 cover check")
    a = ap.parse_args()
    src = dict(mp4=a.mp4, cover=a.cover, weibo=a.weibo, srt=a.srt)
    e = build(a.id, src, a.out, require_hd=not a.allow_non_hd_cover)
    print(json.dumps(dict(video_id=e["video_id"], asset_name=e["asset_name"], size_bytes=e["size_bytes"], sha256=e["sha256"]), ensure_ascii=False))


if __name__ == "__main__":
    main()
