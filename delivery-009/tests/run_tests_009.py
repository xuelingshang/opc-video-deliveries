#!/usr/bin/env python3
"""Offline tests for the AUTO-BATCH-009 delivery entry, with the fake `gh` from opc-video-deliveries (tests/fake_gh.py,
vendored unchanged). LOCAL SIMULATION ONLY - the live Release API is not touched.

    python3 delivery-009/tests/run_tests_009.py --work DIR          # needs ffmpeg, git, PyYAML

Synthetic samples (test pattern + tone, generated here) are packed into station-style ZIPs and split into parts.

  part 1  restore_009.py: the six station manifest shapes restore and re-store byte-exact; tampering is refused
  part 2  run_009.py end to end against a local "009" git repository with the six station branches
          (state -> fetch -> rebuild -> deliver, lock on a local "deliveries" repository)
  part 3  static checks of the workflow file (who gets which credential, no publish, 008 untouched)
"""
import argparse, hashlib, json, os, shutil, subprocess, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..")
REPO = "xuelingshang/opc-video-deliveries"
TAG = "delivery-009-2026-10-18-01"
sys.path.insert(0, TOOL)
import restore_009 as R  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def git(*args, cwd=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@x")
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout


# ------------------------------------------------------------------ synthetic station output

MEDIA = {}


def media(work, size="1920x1080", tone=440):
    key = (size, tone)
    if key not in MEDIA:
        d = os.path.join(work, "media", f"{size}-{tone}")
        os.makedirs(d, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration=1",
                        "-f", "lavfi", "-i", f"sine=frequency={tone}:sample_rate=48000:duration=1", "-c:v", "libx264",
                        "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", f"{d}/v.mp4"], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=1:duration=1",
                        "-frames:v", "1", f"{d}/cover.jpg"], check=True)
        MEDIA[key] = {"mp4": open(f"{d}/v.mp4", "rb").read(), "cover.jpg": open(f"{d}/cover.jpg", "rb").read()}
    return MEDIA[key]


def station_video(base, vid, fmt, work, *, size="1920x1080", tone=440, root=None, extra=None, part_bytes=40000,
                  weibo=None, layout=None):
    """Write OUTPUT/009/<vid>/... in station format `fmt` under `base`. Returns (manifest rel path, zip bytes)."""
    m = media(work, size, tone)
    root = root or (f"{vid}-R2" if fmt == "5r2" else vid)
    files = {f"{root}/{root}.mp4": m["mp4"], f"{root}/cover.jpg": m["cover.jpg"],
             f"{root}/weibo.txt": (weibo or f"测试 {vid}\n").encode(), f"{root}/subtitle.srt":
             "1\n00:00:00,100 --> 00:00:00,900\n测试\n".encode()}
    if layout:
        files = layout(files)
    if extra:
        files.update(extra)
    tmp = os.path.join(work, "zips", fmt + vid + ".zip")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in files.items():
            z.writestr(n, b)
    zb = open(tmp, "rb").read()
    vdir = f"OUTPUT/009/{vid}"
    sub, zname, pfx, mname = {
        "2": ("delivery", f"{vid}.zip", "part{:03d}", f"{vid}.zip.manifest.json"),
        "3": ("DELIVERY", f"{vid}_delivery.zip", "part{:03d}", "DELIVERY_MANIFEST.json"),
        "4": ("DELIVERY", f"{vid}_DELIVERY.zip", "part{:03d}", "DELIVERY_MANIFEST.json"),
        "5": ("DELIVERY", f"{vid}.zip", "{:03d}", "DELIVERY_MANIFEST.json"),
        "5r2": ("R2/DELIVERY", f"{vid}-R2.zip", "{:03d}", "DELIVERY_MANIFEST.json"),
        "A": ("delivery", f"{vid}.zip", "{:03d}", f"{vid}.zip.manifest.json"),
        "C": ("DELIVERY-PARTS", f"{vid}-DELIVERY.zip", "part{:02d}", "PARTS.json"),
    }[fmt]
    d = os.path.join(base, vdir, sub)
    os.makedirs(d, exist_ok=True)
    parts = []
    for i in range(0, len(zb), part_bytes):
        b = zb[i:i + part_bytes]
        pn = f"{zname}.{pfx.format(i // part_bytes + 1)}"
        open(os.path.join(d, pn), "wb").write(b)
        parts.append({"name": pn, "bytes": len(b), "sha256": sha(b)})
    mem = {n: {"bytes": len(b), "sha256": sha(b)} for n, b in files.items()}
    mp4n = f"{root}/{root}.mp4"
    if fmt == "2":
        man = {"video_id": vid, "zip": zname, "zip_bytes": len(zb), "zip_sha256": sha(zb), "members": mem, "parts": parts}
    elif fmt == "3":
        man = {"video_id": vid, "zip": zname, "zip_bytes": len(zb), "zip_sha256": sha(zb),
               "parts": [{"file": p["name"], "bytes": p["bytes"], "sha256": p["sha256"]} for p in parts],
               "zip_entries": [{"path": n, "bytes": v["bytes"]} for n, v in mem.items()],
               "mp4_sha256": mem[mp4n]["sha256"], "cover_sha256": mem[f"{root}/cover.jpg"]["sha256"]}
        st_extra = {"delivery_status": "PACKAGED_RESTORE_VERIFIED", "outputs": {"delivery_zip_sha256": sha(zb)}}
    elif fmt == "4":
        man = {"video_id": vid, "zip": {"name": zname, "bytes": len(zb), "sha256": sha(zb), "members": list(mem),
                                        "member_sha256": {n: v["sha256"] for n, v in mem.items()}}, "parts": parts}
        open(os.path.join(d, "RESTORE_VERIFICATION.json"), "w").write(json.dumps(
            {"restored_zip_sha256": sha(zb), "original_zip_sha256": sha(zb), "structure_pass": True}))
    elif fmt in ("5", "5r2"):
        man = {"video_id": vid, "zip": {"name": zname, "bytes": len(zb), "sha256": sha(zb)}, "parts": parts,
               "members": [{"path": n, **v} for n, v in mem.items()], "verification": {"pass": True}}
    elif fmt == "A":
        man = {"video_id": vid, "zip": zname, "zip_bytes": len(zb), "zip_sha256": sha(zb), "parts": parts,
               "zip_entries": [{"name": n, **v} for n, v in mem.items()], "verification": {"matches_original": True}}
    else:
        man = {"video_id": vid, "zip": zname, "zip_bytes": len(zb), "zip_sha256": sha(zb), "parts": parts,
               "zip_entries": [{"name": n.split("/", 1)[1], "size_bytes": v["bytes"], "sha256": v["sha256"]}
                               for n, v in mem.items()]}
        open(os.path.join(d, "RESTORE-TEST.json"), "w").write(json.dumps({"PASS": True}))
    open(os.path.join(d, mname), "w").write(json.dumps(man, indent=1))
    st = {"video_id": vid, "title": "不进日志的标题", "status": "DONE_INTERNAL_REVIEW", "fact_gate": "FACT_PASS",
          "rights_status": "UNVERIFIED", "public_release_authorized": False}
    if fmt == "2":
        st["delivery"] = {"zip_sha256": sha(zb), "restore_verified": True}
    if fmt == "3":
        st.update(st_extra)
    if fmt != "5r2" or not os.path.exists(os.path.join(base, vdir, "STATUS.json")):
        open(os.path.join(base, vdir, "STATUS.json"), "w").write(json.dumps(st, ensure_ascii=False))
    if fmt == "5r2":
        open(os.path.join(base, vdir, "R2", "STATUS-R2.json"), "w").write(json.dumps(
            {"status": "INTERNAL_REVIEW_R2_LATEST", "founder_review": {"decision": "ACCEPTED"},
             "public_release_authorized": False}))
    return f"{vdir}/{sub}/{mname}", zb, m["mp4"]


# ------------------------------------------------------------------ part 1: restore_009 per station format

def part1(work):
    base = os.path.join(work, "p1")
    out = os.path.join(work, "p1out")
    for fmt, vid in (("2", "009-001"), ("3", "009-021"), ("4", "009-043"), ("5", "009-084"), ("5r2", "009-081"),
                     ("A", "009-121"), ("C", "009-161")):
        mrel, _zb, mp4 = station_video(base, vid, fmt, work)
        try:
            rec = R.restore(vid, base, mrel, out, log=lambda m: None)
            zp = os.path.join(out, "pkg", vid, f"{vid}-DELIVERY.zip")
            with zipfile.ZipFile(zp) as z:
                names = z.namelist()
                same = z.read(f"{vid}/{vid}.mp4") == mp4
            ok = names == [f"{vid}/{vid}.mp4", f"{vid}/cover.jpg", f"{vid}/weibo.txt", f"{vid}/subtitle.srt"] and same \
                and rec["mp4_sha256"] == sha(mp4) and rec["zip_sha256"] == R.sha_file(zp)
            check(f"station format {fmt}: restored, verified, re-stored as {vid}-DELIVERY.zip with the same MP4 bytes", ok,
                  str(names))
        except SystemExit as e:
            check(f"station format {fmt}: restored", False, str(e))
    # determinism: the same station ZIP always gives the same delivery ZIP
    first = R.sha_file(os.path.join(out, "pkg", "009-043", "009-043-DELIVERY.zip"))
    R.restore("009-043", base, "OUTPUT/009/009-043/DELIVERY/DELIVERY_MANIFEST.json", out, log=lambda m: None)
    check("re-storing is deterministic (same delivery ZIP SHA256)",
          R.sha_file(os.path.join(out, "pkg", "009-043", "009-043-DELIVERY.zip")) == first)

    def refused(name, vid, fmt, mutate=None, expect="", **kw):
        b = os.path.join(work, "p1bad", name.replace(" ", "_"))
        mrel, zb, _ = station_video(b, vid, fmt, work, **kw)
        if mutate:
            mutate(b, mrel, zb)
        try:
            R.restore(vid, b, mrel, os.path.join(work, "p1badout"), log=lambda m: None)
            check(f"refused: {name}", False, "was accepted")
        except SystemExit as e:
            check(f"refused: {name}", expect in str(e), str(e))

    def edit(fn):
        def m(b, mrel, zb):
            p = os.path.join(b, mrel)
            j = json.load(open(p))
            fn(j, b, mrel)
            open(p, "w").write(json.dumps(j))
        return m

    def flip_part(b, mrel, zb):
        d = os.path.join(b, os.path.dirname(mrel))
        p = sorted(x for x in os.listdir(d) if ".zip.part" in x)[0]
        data = bytearray(open(os.path.join(d, p), "rb").read())
        data[100] ^= 1
        open(os.path.join(d, p), "wb").write(data)

    refused("a part's bytes changed", "009-002", "2", flip_part, "SHA256 differs")
    refused("ZIP SHA256 in the manifest wrong", "009-003", "2",
            edit(lambda j, b, m: j.update(zip_sha256="0" * 64)), "differs from the manifest")
    refused("part path traversal", "009-004", "2",
            edit(lambda j, b, m: j["parts"][0].update(name="../../x")), "bad part name")
    refused("member hash differs from the manifest", "009-005", "4",
            edit(lambda j, b, m: j["zip"]["member_sha256"].update({"009-005/weibo.txt": "1" * 64})), "weibo.txt")
    refused("MP4 SHA256 not recorded", "009-006", "3", edit(lambda j, b, m: j.pop("mp4_sha256")), "MP4 SHA256")
    refused("extra file inside the ZIP", "009-007", "A", expect="notes.txt", extra={"009-007/notes.txt": b"x"})
    refused("wrong ZIP top folder", "009-008", "A", expect="top folder", root="009-099")
    refused("MP4 not 1080p", "009-009", "A", expect="1920x1080", size="1280x720")

    def symlink_part(b, mrel, zb):
        d = os.path.join(b, os.path.dirname(mrel))
        p = sorted(x for x in os.listdir(d) if x.endswith(".001"))[0]
        os.rename(os.path.join(d, p), os.path.join(b, "moved"))
        os.symlink(os.path.join(b, "moved"), os.path.join(d, p))
    refused("a part is a symlink", "009-010", "A", symlink_part, "symlink")


# ------------------------------------------------------------------ part 2: run_009.py end to end

def part2(work, env):
    src = os.path.join(work, "src009")
    os.makedirs(src)
    git("init", "-q", "-b", "main", cwd=src)
    open(os.path.join(src, "README.md"), "w").write("009\n")
    git("add", "-A", cwd=src); git("commit", "-q", "-m", "init", cwd=src)

    def branch(name, build):
        git("checkout", "-q", "-B", name, "main", cwd=src)
        build()
        git("add", "-A", cwd=src); git("commit", "-q", "-m", name, "--allow-empty", cwd=src)
        git("checkout", "-q", "main", cwd=src)

    zips = {}

    def s2():
        for i, vid in enumerate(("009-001", "009-002")):
            zips[vid] = station_video(src, vid, "2", work, tone=300 + i)
        zips["009-006"] = station_video(src, "009-006", "2", work, tone=310)          # not in only_ids
        station_video(src, "009-121", "A", work, tone=320)                           # station A's number on station 2
    branch("claude/009-2-001-011", s2)
    branch("claude/009-3-013-036", lambda: zips.update({"009-021": station_video(src, "009-021", "3", work, tone=330)}))

    def s4():
        zips["009-043"] = station_video(src, "009-043", "4", work, tone=340)
        os.makedirs(os.path.join(src, "OUTPUT/009/009-049"))                         # no manifest: not restorable
        open(os.path.join(src, "OUTPUT/009/009-049/STATUS.json"), "w").write("{}")
    branch("claude/009-4-043-077", s4)

    def s5():
        station_video(src, "009-081", "5", work, tone=350)                          # R1 kept
        zips["009-081"] = station_video(src, "009-081", "5r2", work, tone=351)      # R2 preferred
    branch("claude/009-5-081-107", s5)
    branch("claude/009-a-121-134", lambda: zips.update({"009-121": station_video(src, "009-121", "A", work, tone=360)}))

    def sc():
        zips["009-161"] = station_video(src, "009-161", "C", work, tone=370)
        zips["009-162"] = station_video(src, "009-162", "C", work, tone=370)          # same MP4 as 009-161
    branch("claude/009-c-152-183", sc)
    git("checkout", "-q", "-B", "claude/009-9-evil", "main", cwd=src)               # not a configured branch
    station_video(src, "009-001", "2", work, tone=999)
    git("add", "-A", cwd=src); git("commit", "-q", "-m", "evil", cwd=src); git("checkout", "-q", "main", cwd=src)

    cfg = json.load(open(os.path.join(TOOL, "SOURCES.json")))
    cfg["only_ids"] = ["009-001", "009-002", "009-021", "009-043", "009-049", "009-081", "009-121", "009-161",
                       "009-162", "009-170"]
    cfgp = os.path.join(work, "SOURCES.test.json")
    json.dump(cfg, open(cfgp, "w"), ensure_ascii=False)

    lockrepo = os.path.join(work, "lock.git")
    git("init", "-q", "--bare", lockrepo)
    dlv = os.path.join(work, "dlv")
    git("init", "-q", dlv); git("remote", "add", "origin", lockrepo, cwd=dlv)
    w = os.path.join(work, "w")

    def step(*args):
        return subprocess.run([sys.executable, os.path.join(TOOL, "run_009.py"), *args], capture_output=True, text=True, env=env)

    def full(dry=False, ids=""):
        shutil.rmtree(w, ignore_errors=True)
        log = ""
        for args in (["state", "--repo", REPO, "--work", w, "--config", cfgp],
                     ["fetch", "--config", cfgp, "--work", w, "--source", src, "--ids", ids],
                     ["rebuild", "--work", w],
                     ["deliver", "--repo", REPO, "--config", cfgp, "--work", w, "--lock-dir", dlv, "--wait-s", "30"]
                     + (["--dry-run"] if dry else [])):
            p = step(*args)
            log += p.stdout + p.stderr
            if p.returncode and args[0] != "deliver":
                return p.returncode, log
        return p.returncode, log

    def state():
        return json.load(open(os.path.join(env["FAKE_GH_DIR"], "state.json")))["releases"]

    def rel():
        return next((r for r in state() if r["tag_name"] == TAG), None)

    def asset_json(r, name):
        return json.load(open(next(x for x in r["assets"] if x["name"] == name)["_file"]))

    snap008 = json.dumps([r for r in state() if r["tag_name"].startswith("delivery-008")], sort_keys=True)

    rc, log = full(dry=True)
    check("dry run: no 009 release written", rel() is None and "DRY RUN 009-001" in log, log[-800:])

    rc, log = full()
    r = rel()
    names = sorted(a["name"] for a in r["assets"]) if r else []
    want = sorted(["009-001-DELIVERY.zip", "009-002-DELIVERY.zip", "009-021-DELIVERY.zip", "009-043-DELIVERY.zip",
                   "009-081-DELIVERY.zip", "009-121-DELIVERY.zip", "delivery-manifest.json", "delivery-009-records.json"])
    check("first run: one 009 draft with one complete ZIP per good video", r and r["draft"] and names == want and
          r["name"] == "AUTO-BATCH-009｜2026-10-18交付", f"{names} {log[-1500:]}")
    check("first run is red because some videos were refused", rc == 1)
    for vid, why in (("009-049", "no delivery manifest"), ("009-170", "no directory"), ("009-161", "same MP4"),
                     ("009-162", "same MP4")):
        check(f"{vid} refused alone ({why})", f"REFUSED {vid}" in log and why in log.split(f"REFUSED {vid}", 1)[1][:200])
    man = asset_json(r, "delivery-manifest.json") if r else {}
    check("manifest is R2 schema_version 1 for the 009 tag", man.get("schema_version") == 1 and man.get("release_tag") == TAG
          and man.get("delivery_date") == "2026-10-18" and len(man.get("videos", [])) == 6)
    recs = asset_json(r, "delivery-009-records.json")["videos"] if r else {}
    check("records copy the station status as recorded and never authorise publishing",
          recs.get("009-001", {}).get("station_status", {}).get("rights_status") == "UNVERIFIED" and
          all(v["public_release_authorized"] is False for v in recs.values()) and len(recs) == 6)
    check("R2 round preferred over R1 and its status recorded", recs.get("009-081", {}).get("source_zip_root") == "009-081-R2"
          and recs["009-081"]["station_status"].get("status") == "INTERNAL_REVIEW_R2_LATEST")
    check("station restore records found", recs.get("009-043", {}).get("station_restore_record", {}).get("where") ==
          "RESTORE_VERIFICATION.json" and recs.get("009-001", {}).get("station_restore_record", {}).get("pass") is True
          and recs.get("009-021", {}).get("station_restore_record", {}).get("where") == "STATUS.json delivery_status")
    with zipfile.ZipFile(next(a["_file"] for a in r["assets"] if a["name"] == "009-081-DELIVERY.zip")) as z:
        check("R2 ZIP re-stored in the 009-NNN layout with the R2 MP4 bytes",
              z.namelist()[0] == "009-081/009-081.mp4" and z.read("009-081/009-081.mp4") == zips["009-081"][2])
    check("other stations' numbers and unconfigured branches ignored",
          "009-006" not in log and recs.get("009-001", {}).get("mp4_sha256") == sha(zips["009-001"][2]))
    check("public log carries no titles", "不进日志的标题" not in log)
    check("lock taken and released on delivery-009-lock",
          git("log", "-1", "--format=%s", "delivery-009-lock", cwd=lockrepo).startswith("OPC-009-LOCK FREE"))
    ids_before = {a["name"]: a["id"] for a in r["assets"]}

    rc2, log2 = full()
    r2 = rel()
    check("second run uploads nothing (same name + SHA256 skipped)",
          {a["name"]: a["id"] for a in r2["assets"]} == ids_before and "already on the draft" in log2, log2[-600:])

    # station republishes a delivered video with different bytes -> CONFLICT, nothing overwritten
    git("checkout", "-q", "claude/009-3-013-036", cwd=src)
    shutil.rmtree(os.path.join(src, "OUTPUT/009/009-021"))
    station_video(src, "009-021", "3", work, tone=331)
    git("add", "-A", cwd=src); git("commit", "-q", "-m", "changed", cwd=src); git("checkout", "-q", "main", cwd=src)
    rc3, log3 = full()
    check("changed bytes of a delivered video: CONFLICT reported, nothing overwritten",
          {a["name"]: a["id"] for a in rel()["assets"]} == ids_before and rc3 == 1 and "REFUSED 009-021: CONFLICT" in log3,
          log3[-600:])

    # a new video committed later goes into the same draft automatically
    git("checkout", "-q", "claude/009-c-152-183", cwd=src)
    shutil.rmtree(os.path.join(src, "OUTPUT/009/009-162"))
    station_video(src, "009-162", "C", work, tone=380)
    git("add", "-A", cwd=src); git("commit", "-q", "-m", "fix 162", cwd=src); git("checkout", "-q", "main", cwd=src)
    rc4, log4 = full(ids="009-161,009-162")
    r4 = rel()
    check("--ids limits the run; a fixed video is appended to the same draft",
          "009-162-DELIVERY.zip" in {a["name"] for a in r4["assets"]} and "009-161-DELIVERY.zip" in
          {a["name"] for a in r4["assets"]} and len(asset_json(r4, "delivery-manifest.json")["videos"]) == 8
          and all(ids_before[n] == a["id"] for a in r4["assets"] for n in [a["name"]] if n in ids_before
                  and n.endswith(".zip")), log4[-800:])
    p = step("fetch", "--config", cfgp, "--work", w, "--source", src, "--ids", "009-006")
    check("--ids outside only_ids refused", p.returncode != 0 and "outside" in p.stderr)
    check("008 releases untouched", json.dumps([r for r in state() if r["tag_name"].startswith("delivery-008")],
                                               sort_keys=True) == snap008)


# ------------------------------------------------------------------ part 3: workflow file

def part3():
    import yaml
    root = os.path.join(TOOL, "..")
    path = os.path.join(root, ".github", "workflows", "delivery-009-draft.yml")
    text = open(path).read()
    wf = yaml.safe_load(text)
    job = wf["jobs"]["deliver"]
    steps = job["steps"]
    who = {s["name"].split(" ")[0] if s["name"][0].isdigit() else s["name"]: json.dumps(s.get("env", {})) for s in steps}
    check("only step 2 sees OPC009_READ_TOKEN", [k for k, v in who.items() if "OPC009_READ_TOKEN" in v] == ["2"])
    check("GITHUB_TOKEN only in steps 1 and 4", sorted(k for k, v in who.items() if "github.token" in v) == ["1", "4"])
    check("step 3 (restore) has no credentials", who["3"] == "{}")
    check("environment delivery-009, main only, contents:write only",
          job["environment"] == "delivery-009" and "refs/heads/main" in job["if"] and wf["permissions"] == {"contents": "write"})
    check("schedule needs the owner's DELIVERY_009_SCHEDULE switch; manual runs default to dry run",
          "vars.DELIVERY_009_SCHEDULE == 'on'" in job["if"] and wf[True]["workflow_dispatch"]["inputs"]["dry_run"]["default"] is True)
    check("no publish path and no artifacts", "draft=false" not in text and "upload-artifact" not in text
          and "releases/" not in text)
    check("checkout keeps no credentials", steps[0]["with"]["persist-credentials"] is False)
    base = subprocess.run(["git", "rev-parse", "--verify", "-q", "origin/main"], cwd=root, capture_output=True, text=True).stdout.strip()
    if base:
        diff = subprocess.run(["git", "diff", "--name-only", base, "--", "delivery-008", ".github/workflows/delivery-008-draft.yml"],
                              cwd=root, capture_output=True, text=True).stdout.strip()
        check("delivery-008/ and its workflow unchanged against origin/main", diff == "", diff)
    for f in ("opc_pack.py", "opc_publish.py"):
        check(f"vendor/{f} byte-identical to delivery-008/vendor/{f}",
              open(os.path.join(TOOL, "vendor", f), "rb").read() == open(os.path.join(root, "delivery-008", "vendor", f), "rb").read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    a = ap.parse_args()
    shutil.rmtree(a.work, ignore_errors=True)
    gh_dir, bindir = os.path.join(a.work, "gh"), os.path.join(a.work, "bin")
    os.makedirs(gh_dir); os.makedirs(bindir)
    os.symlink(os.path.join(HERE, "fake_gh.py"), os.path.join(bindir, "gh"))
    env = dict(os.environ, PATH=bindir + os.pathsep + os.environ["PATH"], FAKE_GH_DIR=gh_dir,
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@x")
    # an 008 draft exists and must never be touched
    json.dump({"next_id": 100, "releases": [{"id": 1, "tag_name": "delivery-008-2026-10-18-01", "name": "AUTO-BATCH-008｜2026-10-18交付",
                                             "draft": True, "prerelease": False, "assets": [], "html_url": "x"}]},
              open(os.path.join(gh_dir, "state.json"), "w"), ensure_ascii=False)
    print("== part 1: restore_009 per station format"); part1(a.work)
    print("== part 2: run_009 end to end"); part2(a.work, env)
    print("== part 3: workflow file"); part3()
    bad = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
