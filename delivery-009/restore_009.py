#!/usr/bin/env python3
"""Restore one AUTO-BATCH-009 station ZIP from its byte parts, verify it, and re-store it as 009-NNN-DELIVERY.zip.

    python3 restore_009.py --id 009-043 --root DATA --manifest OUTPUT/009/009-043/DELIVERY/DELIVERY_MANIFEST.json --out OUT

The stations wrote different manifest shapes (normalize() reads all of them). For every video:

  1. join the parts in manifest order; each part and the whole ZIP must match the manifest's bytes + SHA256;
  2. the ZIP must pass a CRC test and hold exactly ROOT/ROOT.mp4, ROOT/cover.jpg, ROOT/weibo.txt, ROOT/subtitle.srt
     (ROOT = 009-NNN, or 009-NNN-R<k> for a later internal round); every member hash the manifest records must match,
     and the MP4 hash must be recorded;
  3. the MP4 must hold a 1920x1080 video stream and an audio stream (ffprobe);
  4. the four member files are copied out byte for byte and packed with the vendored opc_pack.py (stored entries, fixed
     timestamps) as 009-NNN/009-NNN.mp4 + cover.jpg + weibo.txt + subtitle.srt, the 008 delivery layout; the packed
     MP4 must hash to the same value. Nothing is re-encoded, re-rendered, re-dubbed or downloaded.

Writes OUT/pkg/<id>/{<id>-DELIVERY.zip, video-entry.json} and returns a record (source ZIP, parts, member hashes).
All inputs are untrusted DATA from a production branch: paths are built from validated components only, part names
must extend the ZIP name, symlinks are refused, sizes are checked before reading. Nothing from the branch is run.
"""
import argparse, hashlib, json, os, re, shutil, stat, subprocess, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PACK = os.path.join(HERE, "vendor", "opc_pack.py")
ID_RE = re.compile(r"^009-\d{3}$")
COMP_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_PARTS = 64
MAX_ZIP = 2 * 1024 ** 3 - 1
SIDES = ("cover.jpg", "weibo.txt", "subtitle.srt")


class Bad(SystemExit):
    pass


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def check_rel(rel):
    if not isinstance(rel, str) or rel.startswith("/") or "\\" in rel:
        raise Bad(f"unsafe path {rel!r}")
    parts = rel.split("/")
    if any(p in ("", ".", "..") or not COMP_RE.fullmatch(p) for p in parts):
        raise Bad(f"unsafe path {rel!r}")
    return parts


def safe_file(root, rel):
    """root/rel as a regular file reached through real directories only."""
    parts = check_rel(rel)
    cur = os.path.abspath(root)
    for i, p in enumerate(parts):
        cur = os.path.join(cur, p)
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            raise Bad(f"missing {rel}")
        if stat.S_ISLNK(st.st_mode):
            raise Bad(f"symlink not allowed: {rel}")
        if (i == len(parts) - 1) != stat.S_ISREG(st.st_mode) or (i < len(parts) - 1 and not stat.S_ISDIR(st.st_mode)):
            raise Bad(f"not a regular file: {rel}")
    return cur


def _hex(v):
    return v if isinstance(v, str) and HEX64.fullmatch(v) else None


def _int(v):
    return v if type(v) is int and 0 < v <= MAX_ZIP else None


def member_key(name):
    """'009-043/cover.jpg', 'cover.jpg', '009-081-R2/009-081-R2.mp4' -> 'cover.jpg' / 'mp4'."""
    base = str(name).rsplit("/", 1)[-1]
    return "mp4" if base.endswith(".mp4") else base


def normalize(m, vid):
    """The station manifest shapes -> {zip_name, zip_bytes, zip_sha256, parts[{name,bytes,sha256}], members{key: {...}}}."""
    if not isinstance(m, dict):
        raise Bad("manifest is not an object")
    z = m.get("zip")
    if isinstance(z, dict):
        name, size, sha = z.get("name"), z.get("bytes"), z.get("sha256")
    else:
        name, size, sha = z, m.get("zip_bytes"), m.get("zip_sha256")
    if not (isinstance(name, str) and COMP_RE.fullmatch(name) and name.startswith(vid) and name.endswith(".zip")):
        raise Bad(f"bad ZIP name {name!r}")
    if not (_int(size) and _hex(sha)):
        raise Bad("manifest lacks the ZIP bytes / SHA256")
    parts = []
    raw = m.get("parts")
    if not (isinstance(raw, list) and 0 < len(raw) <= MAX_PARTS):
        raise Bad("manifest has no parts list")
    for p in raw:
        pn = p.get("name", p.get("file")) if isinstance(p, dict) else None
        if not (isinstance(pn, str) and COMP_RE.fullmatch(pn) and pn.startswith(name + ".")):
            raise Bad(f"bad part name {pn!r}")
        if not (_int(p.get("bytes")) and _hex(p.get("sha256"))):
            raise Bad(f"{pn}: bad bytes / sha256")
        parts.append({"name": pn, "bytes": p["bytes"], "sha256": p["sha256"]})
    if len({p["name"] for p in parts}) != len(parts) or sum(p["bytes"] for p in parts) != size:
        raise Bad("parts are repeated or do not add up to the ZIP size")
    members = {}

    def put(key, **kv):
        cur = members.setdefault(key, {})
        for k, v in kv.items():
            if v is None:
                continue
            if k in cur and cur[k] != v:
                raise Bad(f"manifest gives two values for {key} {k}")
            cur[k] = v

    mem = m.get("members")
    if isinstance(mem, dict):                                    # Cloud2: {path: {bytes, sha256}}
        for path, v in mem.items():
            put(member_key(path), bytes=_int((v or {}).get("bytes")), sha256=_hex((v or {}).get("sha256")))
    for lst in (mem if isinstance(mem, list) else [], m.get("zip_entries") or []):   # Cloud5 / 3 / A / C
        for v in lst:
            if isinstance(v, dict):
                put(member_key(v.get("path", v.get("name"))), bytes=_int(v.get("bytes", v.get("size_bytes"))),
                    sha256=_hex(v.get("sha256")))
    if isinstance(z, dict):                                      # Cloud4: zip.member_sha256
        for path, v in (z.get("member_sha256") or {}).items():
            put(member_key(path), sha256=_hex(v))
    for key, field in (("mp4", "mp4_sha256"), ("cover.jpg", "cover_sha256"), ("weibo.txt", "weibo_sha256"),
                       ("subtitle.srt", "subtitle_sha256")):  # Cloud3: top-level hashes
        put(key, sha256=_hex(m.get(field)))
    extra = set(members) - {"mp4", *SIDES}
    if extra:
        raise Bad(f"manifest lists unexpected members {sorted(extra)}")
    if not (members.get("mp4") or {}).get("sha256"):
        raise Bad("manifest does not record the MP4 SHA256")
    return {"zip_name": name, "zip_bytes": size, "zip_sha256": sha, "parts": parts, "members": members}


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "json", path],
                       capture_output=True, text=True)
    if r.returncode:
        raise Bad(f"ffprobe failed: {r.stderr.strip()[-200:]}")
    st = json.loads(r.stdout).get("streams", [])
    v = [s for s in st if s.get("codec_type") == "video"]
    if not v or (v[0].get("width"), v[0].get("height")) != (1920, 1080):
        raise Bad(f"MP4 is not 1920x1080 ({[(s.get('width'), s.get('height')) for s in v]})")
    if not any(s.get("codec_type") == "audio" for s in st):
        raise Bad("MP4 has no audio stream")


def restore(vid, root, manifest_rel, out, pack=PACK, log=print):
    if not ID_RE.fullmatch(vid):
        raise Bad(f"bad video id {vid!r}")
    mdir = manifest_rel.rsplit("/", 1)[0]
    with open(safe_file(root, manifest_rel), encoding="utf-8") as f:
        n = normalize(json.load(f), vid)
    work = os.path.join(out, "src", vid)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    zp = os.path.join(work, "station.zip")
    h, size = hashlib.sha256(), 0
    with open(zp, "wb") as fo:
        for p in n["parts"]:
            pp = safe_file(root, f"{mdir}/{p['name']}")
            if os.path.getsize(pp) != p["bytes"]:
                raise Bad(f"part {p['name']}: size differs from the manifest")
            ph = hashlib.sha256()
            with open(pp, "rb") as fi:
                for b in iter(lambda: fi.read(1 << 22), b""):
                    ph.update(b); h.update(b); fo.write(b); size += len(b)
            if ph.hexdigest() != p["sha256"]:
                raise Bad(f"part {p['name']}: SHA256 differs from the manifest")
    if size != n["zip_bytes"] or h.hexdigest() != n["zip_sha256"]:
        raise Bad(f"joined ZIP {h.hexdigest()} differs from the manifest {n['zip_sha256']}")
    got = {}
    with zipfile.ZipFile(zp) as z:
        if z.testzip() is not None:
            raise Bad("ZIP CRC test failed")
        files = [i for i in z.infolist() if not i.is_dir()]
        top = {i.filename.split("/", 1)[0] for i in files}
        rootname = top.pop() if len(top) == 1 else None
        if not (rootname and re.fullmatch(re.escape(vid) + r"(-R\d{1,2})?", rootname)):
            raise Bad(f"ZIP top folder must be {vid}[-R<k>], got {sorted(top | {rootname} - {None})}")
        want = [f"{rootname}/{rootname}.mp4"] + [f"{rootname}/{s}" for s in SIDES]
        if sorted(i.filename for i in files) != sorted(want):
            raise Bad(f"ZIP entries {[i.filename for i in files]} != {want}")
        for i in files:
            key = member_key(i.filename)
            dst = os.path.join(work, "m", "video.mp4" if key == "mp4" else key)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with z.open(i) as fi, open(dst, "wb") as fo:
                shutil.copyfileobj(fi, fo, 1 << 22)
            got[key] = {"bytes": os.path.getsize(dst), "sha256": sha_file(dst), "path": dst}
    for key, rec in n["members"].items():
        for k in ("bytes", "sha256"):
            if k in rec and rec[k] != got[key][k]:
                raise Bad(f"ZIP member {key}: {k} differs from the manifest")
    os.remove(zp)
    probe(got["mp4"]["path"])
    r = subprocess.run([sys.executable, pack, "--id", vid, "--mp4", got["mp4"]["path"], "--cover", got["cover.jpg"]["path"],
                        "--weibo", got["weibo.txt"]["path"], "--srt", got["subtitle.srt"]["path"],
                        "--out", os.path.join(out, "pkg")], capture_output=True, text=True)
    if r.returncode:
        raise Bad(f"pack failed: {(r.stderr or r.stdout).strip()[-400:]}")
    entry = json.load(open(os.path.join(out, "pkg", vid, "video-entry.json"), encoding="utf-8"))
    fs = {member_key(f["name"]): f for f in entry["files"]}
    for key in got:
        if (fs[key]["size_bytes"], fs[key]["sha256"]) != (got[key]["bytes"], got[key]["sha256"]):
            raise Bad(f"packed {key} differs from the station ZIP member")
    shutil.rmtree(work)
    rec = {"video_id": vid, "manifest": manifest_rel, "source_zip": n["zip_name"], "source_zip_bytes": size,
           "source_zip_sha256": n["zip_sha256"], "source_zip_root": rootname, "parts": len(n["parts"]),
           "mp4_bytes": got["mp4"]["bytes"], "mp4_sha256": got["mp4"]["sha256"],
           "asset_name": entry["asset_name"], "zip_bytes": entry["size_bytes"], "zip_sha256": entry["sha256"]}
    log(f"{vid} OK {len(n['parts'])} parts -> {n['zip_name']} {size} {n['zip_sha256'][:12]} (root {rootname}) "
        f"-> {entry['asset_name']} {entry['size_bytes']} {entry['sha256'][:12]}")
    return rec


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--id", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    print(json.dumps(restore(a.id, a.root, a.manifest, a.out, log=lambda m: print(m, file=sys.stderr)), indent=1))


if __name__ == "__main__":
    main()
