#!/usr/bin/env python3
"""Offline tests for publisher/opc_publish.py using tests/fake_gh.py (Releases API stand-in)
and tests/github_sim.py (public download URLs), then the friend tool on the result.

LOCAL SIMULATION ONLY — the live GitHub Release API is not exercised here.

    python3 tests/run_publisher_tests.py --pwsh /path/to/pwsh --work DIR --assets PKGDIR
PKGDIR must contain packages TEST-0001 and TEST-0002 built by publisher/opc_pack.py.
"""
import argparse, json, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
PUB = os.path.join(HERE, "..", "publisher", "opc_publish.py")
TOOL = os.path.join(HERE, "..", "tool", "opc-download.ps1")
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

    def pub(*extra, **envx):
        e = dict(env, **envx)
        p = subprocess.run([sys.executable, PUB, "--repo", REPO, "--web-base", web, *extra], capture_output=True, text=True, env=e)
        return p.returncode, p.stdout + p.stderr

    t1, t2 = os.path.join(a.assets, "TEST-0001"), os.path.join(a.assets, "TEST-0002")
    try:
        rc, out = pub("--date", "2026-10-13", "--pkg", t1, "--test", "--full-anon-verify")
        rel = state()["releases"]
        r0 = rel[0] if rel else {}
        names = [x["name"] for x in r0.get("assets", [])]
        check("P1 test batch published as delivery-2026-10-13-01, ZIP before manifest, anon download verified",
              rc == 0 and r0.get("tag_name") == "delivery-2026-10-13-01" and not r0.get("draft")
              and names == ["TEST-0001-DELIVERY.zip", "delivery-manifest.json"] and "full SHA256 match" in out, out[-800:])
        m = json.load(open(os.path.join(sim, "assets", "delivery-2026-10-13-01", "delivery-manifest.json")))
        check("P1b manifest has the R2 fields", m["schema_version"] == 1 and m["repository"] == REPO
              and m["delivery_date"] == "2026-10-13" and m["release_tag"] == "delivery-2026-10-13-01"
              and set(m["videos"][0]) >= {"video_id", "asset_name", "size_bytes", "sha256", "files"}, json.dumps(m)[:300])
        rc, out = pub("--date", "2026-10-13", "--pkg", t1, "--test")
        check("P2 same video is never uploaded twice", rc != 0 and "already published" in out and len(state()["releases"]) == 1, out[-300:])
        rc, out = pub("--date", "2026-10-13", "--nn", "01", "--pkg", t2, "--test")
        check("P3 published tag is never overwritten", rc != 0 and "never overwritten" in out, out[-300:])
        rc, out = pub("--date", "2026-10-13", "--pkg", t2, "--test", FAKE_GH_FAIL_UPLOAD="delivery-manifest.json:3")
        s = state()["releases"]
        check("P4a interrupted publish leaves an unpublished draft (friends see nothing)",
              rc != 0 and s[0]["draft"] and s[0]["tag_name"] == "delivery-2026-10-13-02"
              and not os.path.exists(os.path.join(sim, "assets", "delivery-2026-10-13-02")), out[-400:])
        rc, out = pub("--date", "2026-10-13", "--pkg", t2, "--test", FAKE_GH_NO_DIGEST="1")
        s = state()["releases"]
        check("P4b re-run resumes the same draft, skips the uploaded ZIP, verifies by download when no digest",
              rc == 0 and len(s) == 2 and not s[0]["draft"] and "TEST-0002-DELIVERY.zip: already uploaded and verified, skip" in out
              and "uploading TEST-0002-DELIVERY.zip" not in out and "resuming draft" in out
              and "verified TEST-0002-DELIVERY.zip" in out, out[-800:])
        # friend tool reads what the publisher produced
        root = os.path.join(a.work, "OPC-DELIVERIES")
        p = subprocess.run([a.pwsh, "-NoProfile", "-File", TOOL, "-Root", root, "-Today", "2026-10-13", "-IncludeTest",
                            "-ApiBase", f"http://127.0.0.1:{PORT}/api", "-WebBase", web], capture_output=True, text=True)
        ok = all(os.path.isfile(os.path.join(root, "_TEST", "2026-10-13", v, f))
                 for v in ("TEST-0001", "TEST-0002") for f in (f"{v}.mp4", "cover.jpg", "weibo.txt", "subtitle.srt"))
        check("P5 friend tool downloads both publisher-made batches", p.returncode == 0 and ok, (p.stdout + p.stderr)[-600:])
    finally:
        srv.terminate()
    ok = sum(1 for _, c in results if c)
    print(f"\n{ok}/{len(results)} publisher checks passed (local simulation)")
    sys.exit(0 if ok == len(results) else 1)


if __name__ == "__main__":
    main()
