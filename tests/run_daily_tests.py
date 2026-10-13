#!/usr/bin/env python3
"""Offline tests for publisher/opc_daily.py (daily release, append-only) with tests/fake_gh.py.
LOCAL SIMULATION ONLY — the live GitHub Release API is not exercised here.

    python3 tests/run_daily_tests.py --work DIR
Builds original TEST-* samples with publisher/make_test_asset.sh + opc_pack.py.
"""
import argparse, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PUB = os.path.join(HERE, "..", "publisher")
REPO = "xuelingshang/opc-video-deliveries"
D = "2099-12-31"
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    a = ap.parse_args()
    shutil.rmtree(a.work, ignore_errors=True)
    gh_dir, bindir, src, pkg = (os.path.join(a.work, x) for x in ("gh", "bin", "src", "pkg"))
    for d in (gh_dir, bindir, src, pkg):
        os.makedirs(d)
    os.symlink(os.path.join(HERE, "fake_gh.py"), os.path.join(bindir, "gh"))
    env = dict(os.environ, PATH=bindir + os.pathsep + os.environ["PATH"], FAKE_GH_DIR=gh_dir)

    def make(vid, out=pkg, variant=""):
        s = os.path.join(src + variant, vid)
        if not os.path.exists(s):
            subprocess.run(["bash", os.path.join(PUB, "make_test_asset.sh"), vid, src + variant], check=True, capture_output=True)
            if variant:
                open(os.path.join(s, "weibo.txt"), "a", encoding="utf-8").write("（另一版本）\n")
        r = subprocess.run([sys.executable, os.path.join(PUB, "opc_pack.py"), "--id", vid, "--mp4", os.path.join(s, vid + ".mp4"),
                            "--cover", os.path.join(s, "cover.jpg"), "--weibo", os.path.join(s, "weibo.txt"),
                            "--srt", os.path.join(s, "subtitle.srt"), "--out", out], check=True, capture_output=True, text=True)
        return os.path.join(out, vid)

    def run(script, *args, extra_env=None):
        return subprocess.run([sys.executable, os.path.join(PUB, script), "--repo", REPO, *args], capture_output=True, text=True,
                              env=dict(env, **(extra_env or {})))

    def state():
        return json.load(open(os.path.join(gh_dir, "state.json")))["releases"]

    def rel(tag):
        return next((r for r in state() if r["tag_name"] == tag), None)

    def manifest(tag):
        r = rel(tag)
        m = next(x for x in r["assets"] if x["name"] == "delivery-manifest.json")
        return json.load(open(m["_file"]))

    p = {v: make(v) for v in ("TEST-0101", "TEST-0102", "TEST-0103", "TEST-0104", "TEST-0105", "TEST-0106")}
    # day release A (-01) and an old-style second batch B (-02), both drafts, like 2026-10-14
    r = run("opc_publish.py", "--date", D, "--test", "--keep-draft", "--pkg", p["TEST-0101"], "--pkg", p["TEST-0102"])
    check("setup A = delivery-2099-12-31-01", r.returncode == 0 and rel(f"delivery-{D}-01"), r.stderr[-300:])
    r = run("opc_publish.py", "--date", D, "--test", "--keep-draft", "--nn", "2", "--pkg", p["TEST-0103"], "--pkg", p["TEST-0104"])
    check("setup B = delivery-2099-12-31-02", r.returncode == 0 and rel(f"delivery-{D}-02"), r.stderr[-300:])
    ids_a = {x["name"]: x["id"] for x in rel(f"delivery-{D}-01")["assets"]}

    # 1. merge B into A, delete B
    r = run("opc_daily.py", "--date", D, "--test", "--keep-draft", "--from-release", f"delivery-{D}-02", "--delete-source")
    A = rel(f"delivery-{D}-01")
    names = sorted(x["name"] for x in A["assets"])
    check("merge: A holds 4 ZIP + manifest", r.returncode == 0 and len(names) == 5, r.stderr[-400:] + str(names))
    check("merge: original ZIPs untouched (same asset ids)",
          all(ids_a[n] == next(x["id"] for x in A["assets"] if x["name"] == n) for n in ids_a if n.endswith(".zip")))
    m = manifest(f"delivery-{D}-01")
    check("merge: manifest lists 4 videos in order, tag -01",
          [v["video_id"] for v in m["videos"]] == ["TEST-0101", "TEST-0102", "TEST-0103", "TEST-0104"] and m["release_tag"] == f"delivery-{D}-01")
    check("merge: duplicate release B deleted", rel(f"delivery-{D}-02") is None)
    check("merge: still draft", A["draft"] is True)

    # 2. rerun of an append with the same packages: skip, nothing changes
    before = json.dumps(rel(f"delivery-{D}-01"), sort_keys=True)
    r = run("opc_daily.py", "--date", D, "--test", "--keep-draft", "--pkg", p["TEST-0103"], "--pkg", p["TEST-0104"])
    check("same name + same SHA256 -> skipped, release unchanged", r.returncode == 0 and json.dumps(rel(f"delivery-{D}-01"), sort_keys=True) == before, r.stderr[-300:])

    # 3. append a new station's video
    r = run("opc_daily.py", "--date", D, "--test", "--keep-draft", "--pkg", p["TEST-0105"])
    check("append TEST-0105 -> 5 videos + manifest", r.returncode == 0 and len(manifest(f"delivery-{D}-01")["videos"]) == 5
          and len(rel(f"delivery-{D}-01")["assets"]) == 6, r.stderr[-300:])

    # 4. same name, different SHA256 -> error, nothing overwritten
    other = make("TEST-0105", out=os.path.join(a.work, "pkg2"), variant="-v2")
    before = json.dumps(rel(f"delivery-{D}-01"), sort_keys=True)
    r = run("opc_daily.py", "--date", D, "--test", "--keep-draft", "--pkg", other)
    check("same name + different SHA256 -> CONFLICT error", r.returncode != 0 and "CONFLICT" in r.stderr, r.stderr[-300:])
    check("conflict: release unchanged", json.dumps(rel(f"delivery-{D}-01"), sort_keys=True) == before)

    # 5. upload failure keeps the old manifest; rerun resumes
    r = run("opc_daily.py", "--date", D, "--test", "--keep-draft", "--pkg", p["TEST-0106"],
            extra_env={"FAKE_GH_FAIL_UPLOAD": "TEST-0106-DELIVERY.zip:5"})
    check("failed upload -> run fails, manifest still 5 videos", r.returncode != 0 and len(manifest(f"delivery-{D}-01")["videos"]) == 5)
    os.remove(os.path.join(gh_dir, "fail-count"))
    r = run("opc_daily.py", "--date", D, "--test", "--keep-draft", "--pkg", p["TEST-0105"], "--pkg", p["TEST-0106"])
    m = manifest(f"delivery-{D}-01")
    check("rerun resumes -> 6 videos + manifest, old entries kept", r.returncode == 0 and len(m["videos"]) == 6
          and len(rel(f"delivery-{D}-01")["assets"]) == 7 and m["videos"][0]["video_id"] == "TEST-0101", r.stderr[-300:])

    # 6. old flow can no longer open a second batch for a formal date, nor touch the day's manifest
    sim = make_formal = None
    fdate = "2099-12-30"
    fp = {}
    for v in ("SIM-0201", "SIM-0202"):
        s = os.path.join(src, v)
        shutil.copytree(os.path.join(src, "TEST-0101"), s)
        os.rename(os.path.join(s, "TEST-0101.mp4"), os.path.join(s, v + ".mp4"))
        subprocess.run([sys.executable, os.path.join(PUB, "opc_pack.py"), "--id", v, "--mp4", os.path.join(s, v + ".mp4"),
                        "--cover", os.path.join(s, "cover.jpg"), "--weibo", os.path.join(s, "weibo.txt"), "--srt",
                        os.path.join(s, "subtitle.srt"), "--out", pkg], check=True, capture_output=True)
        fp[v] = os.path.join(pkg, v)
    r1 = run("opc_daily.py", "--date", fdate, "--keep-draft", "--pkg", fp["SIM-0201"])
    r2 = run("opc_publish.py", "--date", fdate, "--keep-draft", "--pkg", fp["SIM-0202"])
    check("formal date: opc_daily creates delivery-2099-12-30-01", r1.returncode == 0 and rel(f"delivery-{fdate}-01"), r1.stderr[-300:])
    check("old opc_publish refuses to open -02 (daily rule)", r2.returncode != 0 and "opc_daily" in r2.stderr
          and rel(f"delivery-{fdate}-02") is None, r2.stderr[-300:])
    r3 = run("opc_daily.py", "--date", fdate, "--keep-draft", "--pkg", fp["SIM-0202"])
    check("second station appends to the same formal-date release", r3.returncode == 0
          and len(manifest(f"delivery-{fdate}-01")["videos"]) == 2, r3.stderr[-300:])

    # 7. a published day release never receives unapproved (keep-draft) videos
    rid = rel(f"delivery-{fdate}-01")["id"]
    subprocess.run(["gh", "api", "--method", "PATCH", f"repos/{REPO}/releases/{rid}", "-F", "draft=false"], env=env, capture_output=True)
    r = run("opc_daily.py", "--date", fdate, "--keep-draft", "--pkg", fp["SIM-0202"])
    check("published release + --keep-draft -> refused", r.returncode != 0 and "published" in r.stderr, r.stderr[-300:])

    ok = all(c for _, c in results)
    print(f"{sum(c for _, c in results)}/{len(results)} PASS")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
