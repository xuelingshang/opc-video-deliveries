#!/usr/bin/env python3
"""Offline tests for publisher/opc_publish.py using tests/fake_gh.py (Releases API stand-in)
and tests/github_sim.py (public download URLs), then the friend tool on the result.

LOCAL SIMULATION ONLY — the live GitHub Release API is not exercised here.

    python3 tests/run_publisher_tests.py --pwsh /path/to/pwsh --work DIR --assets PKGDIR
PKGDIR must contain packages TEST-0001, TEST-0002 and SIM-0001 built by publisher/opc_pack.py.
"""
import argparse, json, os, shutil, subprocess, sys, time
from r2_env import TOOLS, ToolEnv

HERE = os.path.dirname(os.path.abspath(__file__))
PUB = os.path.join(HERE, "..", "publisher", "opc_publish.py")
CLEAN = os.path.join(HERE, "..", "publisher", "opc_cleanup_test.py")
PORT = 18766
REPO = "xuelingshang/opc-video-deliveries"
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pwsh", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--assets", required=True)
    a = ap.parse_args()
    shutil.rmtree(a.work, ignore_errors=True)
    gh_dir, sim, bindir = (os.path.join(a.work, x) for x in ("gh", "sim", "bin"))
    for d in (gh_dir, sim, bindir):
        os.makedirs(d)
    json.dump([], open(os.path.join(sim, "releases.json"), "w"))
    os.symlink(os.path.join(HERE, "fake_gh.py"), os.path.join(bindir, "gh"))
    env = dict(os.environ, PATH=bindir + os.pathsep + os.environ["PATH"], FAKE_GH_DIR=gh_dir, FAKE_GH_SIM=sim)
    srv = subprocess.Popen([sys.executable, os.path.join(HERE, "github_sim.py"), str(PORT), sim])
    time.sleep(1)
    web = f"http://127.0.0.1:{PORT}/web"
    state = lambda: json.load(open(os.path.join(gh_dir, "state.json")))
    state_ok = lambda: os.path.exists(os.path.join(gh_dir, "state.json")) and state()["releases"]

    def pub(*extra, **envx):
        e = dict(env, **envx)
        p = subprocess.run([sys.executable, PUB, "--repo", REPO, "--web-base", web, *extra], capture_output=True, text=True, env=e)
        return p.returncode, p.stdout + p.stderr

    t1, t2 = os.path.join(a.assets, "TEST-0001"), os.path.join(a.assets, "SIM-0001")
    t3 = os.path.join(a.assets, "TEST-0002")
    D, T1, T2 = "2099-12-31", "delivery-2099-12-31-01", "delivery-2099-12-31-02"
    try:
        rc, out = pub("--date", "2026-10-13", "--pkg", t2)
        check("P0a formal batch without --confirm-public-gate is refused", rc != 0 and "refused" in out and not state_ok(), out[-300:])
        rc, out = pub("--date", "2026-10-13", "--pkg", t1, "--test")
        check("P0b test batch outside the sandbox date 2099-12-31 is refused", rc != 0 and D in out and not state_ok(), out[-300:])
        rc, out = pub("--date", D, "--pkg", t2, "--confirm-public-gate")
        check("P0c formal batch on the sandbox date is refused", rc != 0 and D in out and not state_ok(), out[-300:])
        rc, out = pub("--date", D, "--pkg", t1, "--test", "--full-anon-verify")
        rel = state()["releases"]
        r0 = rel[0] if rel else {}
        names = [x["name"] for x in r0.get("assets", [])]
        check(f"P1 test batch published as {T1}, title [TEST], ZIP before manifest, anon download verified",
              rc == 0 and r0.get("tag_name") == T1 and not r0.get("draft") and r0.get("name", "").startswith("[TEST]")
              and names == ["TEST-0001-DELIVERY.zip", "delivery-manifest.json"] and "full SHA256 match" in out, out[-800:])
        m = json.load(open(os.path.join(sim, "assets", T1, "delivery-manifest.json")))
        check("P1b manifest has exactly the original R2 keys", list(m) == ["schema_version", "delivery_date", "release_tag", "repository", "videos"]
              and m["schema_version"] == 1 and m["repository"] == REPO and m["delivery_date"] == D and m["release_tag"] == T1
              and sorted(m["videos"][0]) == ["asset_name", "files", "sha256", "size_bytes", "video_id"]
              and all(sorted(f) == ["name", "sha256", "size_bytes"] for f in m["videos"][0]["files"]), json.dumps(m)[:300])
        rc, out = pub("--date", D, "--pkg", t1, "--test")
        check("P2 same video is never uploaded twice", rc != 0 and "already published" in out and len(state()["releases"]) == 1, out[-300:])
        rc, out = pub("--date", D, "--nn", "01", "--pkg", t3, "--test")
        check("P3 published tag is never overwritten", rc != 0 and "never overwritten" in out, out[-300:])
        rc, out = pub("--date", D, "--pkg", t3, "--test", FAKE_GH_FAIL_UPLOAD="delivery-manifest.json:3")
        s = state()["releases"]
        check("P4a interrupted publish leaves an unpublished draft (friends see nothing)",
              rc != 0 and s[0]["draft"] and s[0]["tag_name"] == T2
              and not os.path.exists(os.path.join(sim, "assets", T2)), out[-400:])
        rc, out = pub("--date", D, "--pkg", t3, "--test", FAKE_GH_NO_DIGEST="1")
        s = state()["releases"]
        check("P4b re-run resumes the same draft, skips the uploaded ZIP, verifies by download when no digest",
              rc == 0 and len(s) == 2 and not s[0]["draft"] and "TEST-0002-DELIVERY.zip: already uploaded and verified, skip" in out
              and "uploading TEST-0002-DELIVERY.zip" not in out and "resuming draft" in out
              and "verified TEST-0002-DELIVERY.zip" in out, out[-800:])
        # the R2 friend tool (R2.1: two releases now exist) reads what the publisher produced
        tool = ToolEnv(os.path.join(a.work, "tool"), f"http://127.0.0.1:{PORT}", a.pwsh, TOOLS["r2.1"][0])
        rc, out = tool.run("2026-10-13")
        check("P5a default run on a real date ignores the sandbox TEST batches",
              rc == 0 and not os.path.exists(os.path.join(tool.base, D)), out[-600:])
        rc, out = tool.run("2026-10-13", "-Date", D)
        ok = all(os.path.isfile(os.path.join(tool.base, D, v, f))
                 for v in ("TEST-0001", "TEST-0002") for f in (f"{v}.mp4", "cover.jpg", "weibo.txt", "subtitle.srt"))
        check("P5b R2 tool -Date 2099-12-31 downloads both publisher-made batches", rc == 0 and ok, out[-600:])
        # cleanup: a non-test release on the sandbox date is refused, then the TEST releases go
        clean = lambda *x: subprocess.run([sys.executable, CLEAN, "--repo", REPO, *x], capture_output=True, text=True, env=env)
        st = state(); st["releases"].append(dict(id=999, tag_name="delivery-2099-12-31-03", name="OPC 交付", draft=False,
                                                 prerelease=False, assets=[], html_url="x"))
        json.dump(st, open(os.path.join(gh_dir, "state.json"), "w"))
        p = clean()
        check("P6a cleanup refuses a sandbox-date release that is not titled [TEST]", p.returncode != 0 and "refused" in p.stdout + p.stderr
              and len(state()["releases"]) == 3 and os.listdir(os.path.join(sim, "assets")), (p.stdout + p.stderr)[-300:])
        st = state(); st["releases"] = [r for r in st["releases"] if r["id"] != 999]
        json.dump(st, open(os.path.join(gh_dir, "state.json"), "w"))
        p = clean()
        check("P6b cleanup deletes the TEST releases and confirms none remain", p.returncode == 0 and "clean:" in p.stdout
              and state()["releases"] == [] and json.load(open(os.path.join(sim, "releases.json"))) == [], (p.stdout + p.stderr)[-300:])
    finally:
        srv.terminate()
    ok = sum(1 for _, c in results if c)
    print(f"\n{ok}/{len(results)} publisher checks passed (local simulation)")
    sys.exit(0 if ok == len(results) else 1)


if __name__ == "__main__":
    main()
