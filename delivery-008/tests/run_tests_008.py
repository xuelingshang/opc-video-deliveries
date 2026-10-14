#!/usr/bin/env python3
"""Offline tests for the AUTO-BATCH-008 delivery entry with the fake `gh` from opc-video-deliveries
(tests/fake_gh.py, vendored unchanged). LOCAL SIMULATION ONLY - the live Release API is not touched.

    python3 tests/run_tests_008.py --work DIR
Synthetic samples (test pattern + tone, generated here) are packed with the vendored opc_pack.py.

  part 1  opc_daily_008.py: 008-only draft, serial append, same-SHA256 skip, conflict without overwrite (14 checks)
  part 2  run_008.py, the owner-controlled workflow driver, end to end against a local "008" git repository with
          station branches (state -> fetch -> rebuild -> deliver, lock on a local "deliveries" repository)
  part 3  static checks of the two workflow files (who gets which credential, no publish, no artifacts)
"""
import argparse, hashlib, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..")
REPO = "xuelingshang/opc-video-deliveries"
DATE = "2099-12-30"
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
        os.makedirs(s, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=2",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2", "-c:v", "libx264", "-preset",
                        "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", os.path.join(s, vid + ".mp4")], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=1:duration=1",
                        "-frames:v", "1", os.path.join(s, "cover.jpg")], check=True)
        open(os.path.join(s, "weibo.txt"), "w", encoding="utf-8").write(f"测试 {vid}{variant}\n")
        open(os.path.join(s, "subtitle.srt"), "w", encoding="utf-8").write("1\n00:00:00,100 --> 00:00:01,500\n测试\n")
        o = out + variant
        subprocess.run([sys.executable, os.path.join(TOOL, "vendor", "opc_pack.py"), "--id", vid, "--mp4", os.path.join(s, vid + ".mp4"),
                        "--cover", os.path.join(s, "cover.jpg"), "--weibo", os.path.join(s, "weibo.txt"),
                        "--srt", os.path.join(s, "subtitle.srt"), "--out", o], check=True, capture_output=True)
        return os.path.join(o, vid)

    def run(*args):
        return subprocess.run([sys.executable, os.path.join(TOOL, "opc_daily_008.py"), "--repo", REPO, "--date", DATE, *args],
                              capture_output=True, text=True, env=env)

    def state():
        return json.load(open(os.path.join(gh_dir, "state.json")))["releases"]

    def rel008():
        return next((r for r in state() if r["tag_name"] == f"delivery-008-{DATE}-01"), None)

    def manifest(r):
        m = next(x for x in r["assets"] if x["name"] == "delivery-manifest.json")
        return json.load(open(m["_file"]))

    # a 007-style daily release of the same date exists and must never be touched
    p007 = os.path.join(a.work, "p007")
    st = {"next_id": 100, "releases": [{"id": 1, "tag_name": f"delivery-{DATE}-01", "name": f"OPC 交付 {DATE}", "draft": True,
                                         "prerelease": False, "assets": [], "html_url": "x"}]}
    json.dump(st, open(os.path.join(gh_dir, "state.json"), "w"))
    snap007 = json.dumps(state()[0], sort_keys=True)

    r = run("--init")
    rel = rel008()
    check("init creates the 008 draft", r.returncode == 0 and rel and rel["draft"] and rel["name"] == f"AUTO-BATCH-008｜{DATE}交付",
          r.stderr[-300:])
    r = run("--init")
    check("init is idempotent (no second release)", r.returncode == 0 and sum(x["tag_name"].startswith("delivery-008") for x in state()) == 1)

    p1, p2 = make("008-901"), make("008-902")
    r = run("--pkg", p1, "--pkg", p2)
    rel = rel008()
    names = sorted(x["name"] for x in rel["assets"])
    check("append two videos", r.returncode == 0 and names == ["008-901-DELIVERY.zip", "008-902-DELIVERY.zip", "delivery-manifest.json"],
          r.stderr[-400:])
    m1 = manifest(rel)
    check("manifest lists both, tag is 008", [v["video_id"] for v in m1["videos"]] == ["008-901", "008-902"] and m1["release_tag"] == f"delivery-008-{DATE}-01")
    check("release stays draft", rel["draft"])

    r = run("--pkg", p1, "--pkg", p2)
    check("re-run skips identical ZIPs", r.returncode == 0 and '"skipped": ["008-901", "008-902"]' in r.stdout, r.stdout[-300:])
    check("manifest unchanged by re-run", manifest(rel008()) == m1)

    p3 = make("008-903")
    r = run("--pkg", p3)
    check("second station appends (merge keeps order)", r.returncode == 0 and [v["video_id"] for v in manifest(rel008())["videos"]] == ["008-901", "008-902", "008-903"], r.stderr[-300:])

    p1b = make("008-901", variant="-v2")
    before = json.dumps(rel008(), sort_keys=True)
    r = run("--pkg", p1b)
    check("different bytes for a recorded id -> CONFLICT, nothing changed", r.returncode != 0 and "CONFLICT" in (r.stderr + r.stdout)
          and json.dumps(rel008(), sort_keys=True) == before, (r.stderr + r.stdout)[-300:])

    # another station left a complete ZIP that is not in the manifest, with different bytes than ours
    p4 = make("008-904"); p4b = make("008-904", variant="-v2")
    e4b = json.load(open(os.path.join(p4b, "video-entry.json")))
    subprocess.run(["gh", "api", "--method", "POST", "--input", os.path.join(p4b, "008-904-DELIVERY.zip"),
                    f"https://uploads.github.com/repos/{REPO}/releases/{rel008()['id']}/assets?name=008-904-DELIVERY.zip"],
                   env=env, check=True, capture_output=True)
    r = run("--pkg", p4)
    a4 = next(x for x in rel008()["assets"] if x["name"] == "008-904-DELIVERY.zip")
    check("complete foreign asset with other bytes -> CONFLICT, not overwritten",
          r.returncode != 0 and "CONFLICT" in (r.stderr + r.stdout)
          and a4["digest"] == "sha256:" + e4b["sha256"] and a4["size"] == e4b["size_bytes"], (r.stderr + r.stdout)[-300:])
    check("manifest still 3 videos", len(manifest(rel008())["videos"]) == 3)

    r = subprocess.run([sys.executable, os.path.join(TOOL, "opc_daily_008.py"), "--repo", REPO, "--date", DATE, "--pkg", make("007-041")],
                       capture_output=True, text=True, env=env)
    check("non-008 id refused", r.returncode != 0 and "only 008-NNN" in (r.stderr + r.stdout))

    check("007 release untouched", json.dumps(next(x for x in state() if x["tag_name"] == f"delivery-{DATE}-01"), sort_keys=True) == snap007)

    # published 008 release is refused
    s = json.load(open(os.path.join(gh_dir, "state.json")))
    for x in s["releases"]:
        if x["tag_name"].startswith("delivery-008"):
            x["draft"] = False
    json.dump(s, open(os.path.join(gh_dir, "state.json"), "w"))
    r = run("--pkg", p3)
    check("published 008 release refused", r.returncode != 0 and "PUBLISHED" in (r.stderr + r.stdout))

    part2(a.work, env, make, state)
    part3()

    ok = all(c for _, c in results)
    print(f"\n{sum(c for _, c in results)}/{len(results)} passed")
    sys.exit(0 if ok else 1)


# ------------------------------------------------------------------ part 2: owner-controlled driver end to end
DATE2, DATE3 = "2099-12-29", "2099-12-28"
PART = 64 * 1024


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def part2(work, env, make, state):
    wt, bare, dlv_bare, dlv = (os.path.join(work, x) for x in ("src-wt", "src.git", "dlv.git", "dlv-wt"))
    w2 = os.path.join(work, "w2")
    git("init", "-q", "-b", "main", wt)
    git("config", "user.email", "t@example.invalid", cwd=wt); git("config", "user.name", "t", cwd=wt)
    open(os.path.join(wt, "README.md"), "w").write("008 test source\n")
    git("add", "-A", cwd=wt); git("commit", "-qm", "init", cwd=wt)

    def stage(vid, variant="", sub="OUTPUT/T"):
        pkg = make(vid, out=os.path.join(work, "pkg2"), variant=variant)
        s = os.path.join(work, "src" + variant, vid)
        d = os.path.join(wt, *sub.split("/"), vid)
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(os.path.join(d, "MASTER-PARTS"))
        data = open(os.path.join(s, vid + ".mp4"), "rb").read()
        parts = []
        for i in range(0, len(data), PART):
            b = data[i:i + PART]; name = f"{vid}.mp4.part{len(parts) + 1:02d}"
            open(os.path.join(d, "MASTER-PARTS", name), "wb").write(b)
            parts.append({"name": name, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()})
        mph = hashlib.sha256(data).hexdigest()
        json.dump({"video_id": vid, "bytes": len(data), "sha256": mph, "parts": parts},
                  open(os.path.join(d, "MASTER-PARTS", "MASTER-PARTS.json"), "w"))
        side = {}
        for n, k in (("cover.jpg", "COVER"), ("weibo.txt", "WEIBO"), ("subtitle.srt", "SRT")):
            shutil.copyfile(os.path.join(s, n), os.path.join(d, n))
            side[k] = {"sha256": hashlib.sha256(open(os.path.join(d, n), "rb").read()).hexdigest()}
        json.dump({"STATUS": "TEST", "DELIVERABLES": side}, open(os.path.join(d, "STATUS.json"), "w"))
        e = json.load(open(os.path.join(pkg, "video-entry.json")))
        return {"video_id": vid, "dir": f"{sub}/{vid}", "title": f"标题 {vid}", "mp4_bytes": len(data), "mp4_sha256": mph,
                "zip_asset": e["asset_name"], "zip_bytes": e["size_bytes"], "zip_sha256": e["sha256"]}

    def request(date, station, rows):
        p = os.path.join(wt, "DELIVERY-008", "requests", f"{date}-{station}.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump({"date": date, "station": station, "videos": rows,   # the release field as stage_delivery writes it
                   "release": f"xuelingshang/opc-video-deliveries delivery-008-{date}-01 (AUTO-BATCH-008｜{date}交付, DRAFT)"},
                  open(p, "w"), ensure_ascii=False)

    def branch(name, build):
        git("checkout", "-q", "-B", name, "main", cwd=wt)
        build()
        git("add", "-A", cwd=wt); git("commit", "-qm", name, cwd=wt)
        git("checkout", "-q", "main", cwd=wt)

    rows = {}
    def b_test():
        rows["066"], rows["067"] = stage("008-066"), stage("008-067")
        request(DATE2, "B", [rows["066"], rows["067"]])
    def s2_test():
        rows["086"] = stage("008-086", sub="OUTPUT/I3")
        request(DATE2, "2", [rows["086"]])
        request(DATE2, "B", [stage("008-066", variant="-stale")])          # stale copy of B's request: ignored here
    def b_evil():
        r68, r69, r71 = stage("008-068"), stage("008-069"), stage("008-071")
        rows["068"] = r68
        pd = os.path.join(wt, "OUTPUT", "T", "008-068", "MASTER-PARTS")
        os.remove(os.path.join(pd, "008-068.mp4.part02")); os.symlink("/etc/hostname", os.path.join(pd, "008-068.mp4.part02"))
        os.symlink("T", os.path.join(wt, "OUTPUT", "L"))                     # symlinked directory
        r71["dir"] = "OUTPUT/L/008-071"
        rows["071"] = r71
        request(DATE2, "B", [r68, r69, r71])
    def b_dotdot():
        r = stage("008-073"); r["dir"] = "OUTPUT/../T/008-073"
        request(DATE2, "B", [r])
    def b_foreign():
        request(DATE2, "B", [stage("008-087")])
    def b_badparts():
        r = stage("008-074")
        json.dump([], open(os.path.join(wt, "OUTPUT", "T", "008-074", "MASTER-PARTS", "MASTER-PARTS.json"), "w"))
        request(DATE2, "B", [r])
    def b_x():
        request(DATE2, "B", [stage("008-070")])
    def b_y():
        request(DATE2, "B", [stage("008-070", variant="-v2")])
    branch("claude/008-b-test", b_test)
    branch("claude/008-2-test", s2_test)
    branch("claude/008-b-evil", b_evil)
    branch("claude/008-b-dotdot", b_dotdot)
    branch("claude/008-b-foreign", b_foreign)
    branch("claude/008-b-badparts", b_badparts)
    branch("claude/008-b-x", b_x)
    branch("claude/008-b-y", b_y)
    git("checkout", "-q", "main", cwd=wt)
    request(DATE2, "B", [rows["066"], rows["067"]])                       # merged copy on main: main is no station branch
    git("add", "-A", cwd=wt); git("commit", "-qm", "main copy", cwd=wt)

    def publish_src():
        shutil.rmtree(bare, ignore_errors=True)
        git("clone", "-q", "--bare", wt, bare)
        git("config", "uploadpack.allowFilter", "true", cwd=bare)
        git("config", "uploadpack.allowAnySHA1InWant", "true", cwd=bare)
    publish_src()
    git("init", "-q", "--bare", "-b", "main", dlv_bare)
    git("clone", "-q", dlv_bare, dlv)

    cfg = os.path.join(TOOL, "STATIONS.json")
    def step(*args):
        return subprocess.run([sys.executable, os.path.join(TOOL, "run_008.py"), *args], capture_output=True, text=True, env=env)
    def full(dry=False):
        logs, codes = [], []
        for args in (("state", "--repo", REPO, "--work", w2),
                     ("fetch", "--config", cfg, "--work", w2, "--source", "file://" + bare),
                     ("rebuild", "--work", w2),
                     ("deliver", "--repo", REPO, "--work", w2, "--lock-dir", dlv, "--wait-s", "30") + (("--dry-run",) if dry else ())):
            r = step(*args)
            logs.append(r.stdout + r.stderr); codes.append(r.returncode)
        return codes, "\n".join(logs)

    def rel(date):
        return next((r for r in state() if r["tag_name"] == f"delivery-008-{date}-01"), None)
    def manifest(r):
        return json.load(open(next(x for x in r["assets"] if x["name"] == "delivery-manifest.json")["_file"]))
    def zips(date):
        return {x["name"]: x["digest"] for x in rel(date)["assets"] if x["name"].endswith("-DELIVERY.zip")}
    snap007 = json.dumps(next(x for x in state() if x["tag_name"] == f"delivery-{DATE}-01"), sort_keys=True)

    codes, out = full()
    plan = json.load(open(os.path.join(w2, "plan-built.json")))
    want = {f"{v}-DELIVERY.zip": "sha256:" + rows[v[4:]]["zip_sha256"] for v in ("008-066", "008-067", "008-086")}
    got = zips(DATE2) if rel(DATE2) else {}
    check("driver: B and station 2 delivered into one 008 draft, remote SHA256 = request SHA256",
          all(got.get(k) == v for k, v in want.items()) and "008-069-DELIVERY.zip" in got, out[-1500:])
    check("driver: draft stays draft, manifest lists every delivered video",
          rel(DATE2)["draft"] and sorted(v["video_id"] for v in manifest(rel(DATE2))["videos"]) == ["008-066", "008-067", "008-069", "008-086"])
    check("driver: symlinked part refused (git mode 120000)", "mode 120000" in out and "008-068-DELIVERY.zip" not in got)
    check("driver: path through a symlinked directory refused", "missing OUTPUT/L/008-071/" in out and "008-071-DELIVERY.zip" not in got)
    check("driver: '..' in a request path refused", "unsafe path" in out and "008-073-DELIVERY.zip" not in got)
    check("driver: another station's number refused", "not station B's number" in out and "008-087-DELIVERY.zip" not in got)
    check("driver: two requests disagreeing on one video -> neither delivered", "disagree" in out and "008-070-DELIVERY.zip" not in got)
    check("driver: malformed MASTER-PARTS.json refuses only that video (no crash)", codes[1] == 0 and "008-074" in out
          and "008-074-DELIVERY.zip" not in got)
    check("driver: stale copy of another station's request ignored, main ignored",
          plan["ignored_copies"] == 1 and not any(r["request"].endswith("@" + git("rev-parse", "--short=7", "main", cwd=wt).strip())
                                                  for r in plan["requests"]))
    check("driver: refused items make the run red (exit 1), the rest is delivered", codes[3] == 1 and codes[:3] == [0, 0, 0], codes)
    tip = git("log", "-1", "--format=%B", "delivery-008-lock", cwd=dlv_bare).strip()
    hist = git("log", "--format=%s", "delivery-008-lock", cwd=dlv_bare)
    check("driver: serial lock taken and released on the deliveries repository", tip.startswith("OPC-008-LOCK FREE") and "OPC-008-LOCK LOCKED" in hist, tip)
    check("driver: public log has no branch names, titles or copy text",
          "claude/008-" not in out and "标题" not in out and "测试 008-" not in out, [x for x in ("claude/008-", "标题", "测试 008-") if x in out])
    check("driver: 007 release untouched", json.dumps(next(x for x in state() if x["tag_name"] == f"delivery-{DATE}-01"), sort_keys=True) == snap007)

    m_before = manifest(rel(DATE2))
    codes, out = full()
    plan = json.load(open(os.path.join(w2, "plan.json")))
    b = next(r for r in plan["requests"] if "008-066" in r["delivered"])
    fetched = [os.path.join(dp, f) for dp, _, fs in os.walk(os.path.join(w2, "data")) for f in fs]
    check("driver: re-run fetches nothing already delivered and changes nothing",
          sorted(b["delivered"]) == ["008-066", "008-067"] and not b["todo"] and manifest(rel(DATE2)) == m_before
          and not any(v in f for f in fetched for v in ("008-066", "008-067", "008-069", "008-086", "008-070")), out[-800:])

    digest067 = zips(DATE2)["008-067-DELIVERY.zip"]
    def b_change():
        rows["067b"] = stage("008-067", variant="-v2")
        request(DATE2, "B", [rows["066"], rows["067b"]])
    git("checkout", "-q", "claude/008-b-test", cwd=wt); b_change()
    git("add", "-A", cwd=wt); git("commit", "-qm", "067 changed", cwd=wt); git("checkout", "-q", "main", cwd=wt)
    publish_src()
    codes, out = full()
    check("driver: same name, different SHA256 -> CONFLICT, remote asset kept", "CONFLICT" in out and zips(DATE2)["008-067-DELIVERY.zip"] == digest067
          and codes[3] == 1, out[-800:])

    def b_more():
        rows["072"] = stage("008-072")
        request(DATE2, "B", [rows["066"], rows["067"], rows["072"]])
        request(DATE3, "B", [])
    git("checkout", "-q", "claude/008-b-test", cwd=wt); b_more()
    git("add", "-A", cwd=wt); git("commit", "-qm", "072 + empty request", cwd=wt); git("checkout", "-q", "main", cwd=wt)
    publish_src()
    before = json.dumps(state(), sort_keys=True)
    codes, out = full(dry=True)
    check("driver: dry run writes nothing", json.dumps(state(), sort_keys=True) == before and "DRY RUN" in out, out[-600:])
    codes, out = full()
    check("driver: later video appended to the same draft", zips(DATE2).get("008-072-DELIVERY.zip") == "sha256:" + rows["072"]["zip_sha256"], out[-800:])
    check("driver: empty request creates the empty 008 draft of its date",
          rel(DATE3) is not None and rel(DATE3)["draft"] and rel(DATE3)["name"] == f"AUTO-BATCH-008｜{DATE3}交付" and not rel(DATE3)["assets"])

    sys.path.insert(0, TOOL)
    import run_008 as R
    cfg_ = R.load_cfg(cfg)
    def verdict(release):
        try:
            R.validate_request(f"{DATE2}-B.json", json.dumps({"date": DATE2, "station": "B", "release": release, "videos": []}).encode(), cfg_)
            return "accepted"
        except R.Reject as e:
            return str(e)
    check("driver: a request naming another release (007's) is refused",
          verdict(f"delivery-{DATE2}-01") != "accepted" and verdict(f"delivery-008-{DATE2}-01") == "accepted")
    row = dict(rows["066"])
    bad = []
    for kw in ({"dir": "OUTPUT/T\n/008-066"}, {"video_id": "008-066\n", "dir": "OUTPUT/T/008-066\n"},
               {"zip_sha256": row["zip_sha256"] + "\n"}, {"mp4_bytes": True}, {"dir": "OUTPUT/.git/008-066"}):
        try:
            R.validate_request(f"{DATE2}-B.json", json.dumps({"date": DATE2, "station": "B", "videos": [dict(row, **kw)]}).encode(), cfg_)
            bad.append(kw)
        except R.Reject:
            pass
    check("driver: trailing newlines, bool sizes and dot-directories in request fields are refused", not bad, bad)

    # the same path rules guard the read-only check in the 008 repository, which works on a real checkout
    sys.path.insert(0, TOOL)
    import rebuild_from_parts as RB
    evil = os.path.join(work, "src-wt-evil")
    git("clone", "-q", "-b", "claude/008-b-evil", wt, evil)
    for name, row, want in (("symlinked part", rows["068"], "symlink not allowed"),
                            ("symlinked directory", rows["071"], "symlink not allowed"),
                            ("'..' path", dict(rows["068"], dir="OUTPUT/../OUTPUT/T/008-068"), "unsafe path")):
        try:
            RB.rebuild({"videos": [row]}, evil, os.path.join(work, "rb"), log=lambda m: None)
            err = "accepted"
        except SystemExit as e:
            err = str(e)
        check(f"rebuild_from_parts refuses a {name} in a checkout", want in err, err)


def part3():
    import yaml
    root = os.path.abspath(os.path.join(TOOL, ".."))
    cands = [os.path.join(root, ".github", "workflows", "delivery-008-draft.yml"),
             os.path.join(TOOL, "deliveries-workflow", "delivery-008-draft.yml")]
    root2 = os.path.abspath(os.path.join(TOOL, "..", ".."))
    cands.insert(1, os.path.join(root2, ".github", "workflows", "delivery-008-draft.yml"))
    path = next(p for p in cands if os.path.exists(p) and "OPC008_READ_TOKEN" in open(p).read())
    wf = yaml.safe_load(open(path))
    on = wf.get("on", wf.get(True))
    job = wf["jobs"]["deliver"]
    steps = job["steps"]
    texts = [json.dumps(s, ensure_ascii=False) for s in steps]
    check("workflow: only schedule + manual dispatch (no push / pull_request trigger)", set(on) == {"schedule", "workflow_dispatch"}, list(on))
    check("workflow: contents: write is its only permission", wf["permissions"] == {"contents": "write"})
    check("workflow: default branch only, protected environment delivery-008",
          "refs/heads/main" in job["if"] and job["environment"] == "delivery-008")
    check("workflow: checkout keeps no credentials on disk", steps[0]["with"].get("persist-credentials") is False)
    check("workflow: read token only in the fetch step", [i for i, t in enumerate(texts) if "secrets." in t] ==
          [i for i, t in enumerate(texts) if "OPC008_READ_TOKEN" in t and "run_008.py fetch" in t])
    check("workflow: GITHUB_TOKEN only in the state and deliver steps",
          [i for i, t in enumerate(texts) if "github.token" in t] ==
          [i for i, t in enumerate(texts) if "run_008.py state" in t or "run_008.py deliver" in t])
    check("workflow: no artifacts, no publish", not any("upload-artifact" in t for t in texts)
          and "draft=false" not in open(os.path.join(TOOL, "opc_daily_008.py")).read()
          and "PATCH" not in open(os.path.join(TOOL, "opc_daily_008.py")).read() + open(os.path.join(TOOL, "run_008.py")).read())
    check008 = os.path.join(root2, ".github", "workflows", "delivery-008-request-check.yml")
    if os.path.exists(check008):
        w8 = yaml.safe_load(open(check008))
        allwf = "".join(open(os.path.join(root2, ".github", "workflows", f)).read()
                        for f in os.listdir(os.path.join(root2, ".github", "workflows")))
        check("008 repository: request check is read-only and uses no secret",
              w8["permissions"] == {"contents": "read"} and "${{ secrets." not in open(check008).read()
              and "DELIVERY_TOKEN }}" not in allwf and "secrets.DELIVERY_TOKEN" not in allwf)


if __name__ == "__main__":
    main()
