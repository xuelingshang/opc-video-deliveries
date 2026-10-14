#!/usr/bin/env python3
"""Rebuild 008 delivery ZIPs from the byte parts committed in git (no re-encode, no re-render, no re-dub).

    python3 rebuild_from_parts.py DELIVERY-008/requests/2026-10-14-B.json REPO_DIR OUT_DIR

For every video of the request: join <dir>/MASTER-PARTS/<id>.mp4.partNN (each part and the whole MP4 checked
against MASTER-PARTS.json and the request), check cover.jpg / weibo.txt / subtitle.srt against STATUS.json, pack
with the vendored opc_pack.py (deterministic: fixed timestamps, stored entries) and require the ZIP to equal the
size + SHA256 recorded in the request. Writes OUT_DIR/pkg/<id>/{<id>-DELIVERY.zip, video-entry.json} and
OUT_DIR/rebuild-report.json. Same contract as 007's DELIVERY-PENDING/*/rebuild_packages.py.

Request, parts and sidecars are DATA from a production branch and are treated as untrusted: every path is built
from validated components only (no absolute paths, no "." / "..", no symlinks anywhere on the way, regular files
only, resolved path must stay inside REPO_DIR), part names must be <id>.mp4.partNN, and sizes are checked before
anything is read. Nothing from the production branch is ever executed.
"""
import hashlib, json, os, re, stat, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PACK = os.path.join(HERE, "vendor", "opc_pack.py")
ID_RE = re.compile(r"^008-\d{3}$")
COMP_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
MAX_PARTS = 64
MAX_MP4 = 2 * 1024 ** 3


class Unsafe(SystemExit):
    pass


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def check_rel(rel):
    """A repo-relative path from request data: plain components only."""
    if not isinstance(rel, str) or rel.startswith("/") or "\\" in rel:
        raise Unsafe(f"unsafe path {rel!r}")
    parts = rel.split("/")
    if not parts or any(p in ("", ".", "..") or not COMP_RE.fullmatch(p) for p in parts):
        raise Unsafe(f"unsafe path {rel!r}")
    return parts


def safe_file(root, rel):
    """Absolute path of a regular file at root/rel; refuses symlinks on the way and anything outside root."""
    parts = check_rel(rel)
    cur = os.path.abspath(root)
    for i, p in enumerate(parts):
        cur = os.path.join(cur, p)
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            raise Unsafe(f"missing {rel}")
        if stat.S_ISLNK(st.st_mode):
            raise Unsafe(f"symlink not allowed: {rel}")
        last = i == len(parts) - 1
        if last and not stat.S_ISREG(st.st_mode):
            raise Unsafe(f"not a regular file: {rel}")
        if not last and not stat.S_ISDIR(st.st_mode):
            raise Unsafe(f"not a directory: {rel}")
    real_root = os.path.realpath(root)
    if os.path.commonpath([os.path.realpath(cur), real_root]) != real_root:
        raise Unsafe(f"outside the source tree: {rel}")
    return cur


def video_dir(v):
    vid, d = v.get("video_id"), v.get("dir")
    if not isinstance(vid, str) or not ID_RE.fullmatch(vid):
        raise Unsafe(f"bad video_id {vid!r}")
    if check_rel(d)[-1] != vid:
        raise Unsafe(f"{vid}: dir {d!r} must end in /{vid}")
    return vid, d


def rebuild(req, repo, out, pack=PACK, log=print):
    """Rebuild every video of `req` from `repo` into `out`; returns {video_id: report}. Raises SystemExit on any mismatch."""
    report = {}
    for v in req.get("videos", []):
        vid, d = video_dir(v)
        f = lambda name: safe_file(repo, f"{d}/{name}")  # noqa: E731
        mp = json.load(open(f("MASTER-PARTS/MASTER-PARTS.json"), encoding="utf-8"))
        st = json.load(open(f("STATUS.json"), encoding="utf-8"))
        parts = mp.get("parts") or []
        if not 0 < len(parts) <= MAX_PARTS:
            raise SystemExit(f"{vid}: {len(parts)} parts (1..{MAX_PARTS} allowed)")
        if not (isinstance(v.get("mp4_bytes"), int) and 0 < v["mp4_bytes"] < MAX_MP4):
            raise SystemExit(f"{vid}: bad mp4_bytes in the request")
        if sum(int(p["bytes"]) for p in parts) != v["mp4_bytes"]:
            raise SystemExit(f"{vid}: parts do not add up to the request's mp4_bytes")
        src = os.path.join(out, "src", vid)
        os.makedirs(src, exist_ok=True)
        mp4 = os.path.join(src, f"{vid}.mp4")
        h, n = hashlib.sha256(), 0
        with open(mp4, "wb") as fo:
            for p in parts:
                if not re.fullmatch(re.escape(vid) + r"\.mp4\.part\d{2,4}", str(p.get("name"))):
                    raise SystemExit(f"{vid}: bad part name {p.get('name')!r}")
                pp = f(f"MASTER-PARTS/{p['name']}")
                if os.path.getsize(pp) != p["bytes"]:
                    raise SystemExit(f"{vid}: part mismatch {p['name']}")
                b = open(pp, "rb").read()
                if len(b) != p["bytes"] or hashlib.sha256(b).hexdigest() != p["sha256"]:
                    raise SystemExit(f"{vid}: part mismatch {p['name']}")
                h.update(b); n += len(b); fo.write(b)
        if not (n == mp["bytes"] == v["mp4_bytes"] and h.hexdigest() == mp["sha256"] == v["mp4_sha256"]):
            raise SystemExit(f"{vid}: whole MP4 differs from MASTER-PARTS.json / request")
        side = {}
        for name, key in (("cover.jpg", "COVER"), ("weibo.txt", "WEIBO"), ("subtitle.srt", "SRT")):
            side[name] = sha_file(f(name))
            if side[name] != st["DELIVERABLES"][key]["sha256"]:
                raise SystemExit(f"{vid}: {name} differs from STATUS.json")
        r = subprocess.run([sys.executable, pack, "--id", vid, "--mp4", mp4, "--cover", f("cover.jpg"),
                            "--weibo", f("weibo.txt"), "--srt", f("subtitle.srt"),
                            "--out", os.path.join(out, "pkg")], capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"{vid}: pack failed {r.stderr[-600:]}")
        entry = json.loads(r.stdout)
        os.remove(mp4)
        if entry["size_bytes"] != v["zip_bytes"] or entry["sha256"] != v["zip_sha256"]:
            raise SystemExit(f"{vid}: rebuilt ZIP {entry['sha256']} differs from the request {v['zip_sha256']}")
        report[vid] = dict(source=d, parts=len(parts), mp4_bytes=n, mp4_sha256=mp["sha256"], sidecar_sha256=side,
                           zip=entry, status=st.get("STATUS"), qa=(st.get("QA") or {}).get("verdict"))
        log(f"{vid} OK {n} {mp['sha256'][:12]} -> {entry['asset_name']} {entry['size_bytes']} {entry['sha256'][:12]}")
    return report


def main():
    req_path, repo, out = sys.argv[1:4]
    req = json.load(open(req_path, encoding="utf-8"))
    report = rebuild(req, repo, out, log=lambda m: print(m, flush=True))
    os.makedirs(out, exist_ok=True)
    json.dump(report, open(os.path.join(out, "rebuild-report.json"), "w"), ensure_ascii=False, indent=1)
    print(f"rebuilt {len(report)}/{len(req.get('videos', []))}")


if __name__ == "__main__":
    main()
