#!/usr/bin/env python3
"""Run the R2 friend tool, byte-unmodified, against Releases built by this repository's
publisher, in a local GitHub simulation (see tests/r2_env.py for what is substituted).

  --tool original : r2-original/01-给朋友/DOWNLOAD.ps1, byte-identical to the Founder's R2 ZIP
  --tool r2.1     : r2.1-patch/DOWNLOAD.ps1, the original plus the one-line release-list fix

LOCAL SIMULATION ON POWERSHELL 7 / LINUX. Not a substitute for Windows PowerShell 5.1.

    python3 tests/run_r2_tool_tests.py --pwsh /path/to/pwsh --work DIR --assets PKGDIR [--tool r2.1]
PKGDIR: packages from publisher/opc_pack.py named SIM-0001..SIM-0004, TEST-0001, TEST-0002.
"""
import argparse, hashlib, json, os, shutil, signal, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "publisher"))
import opc_publish
from r2_env import TOOLS, ToolEnv

REPO = "xuelingshang/opc-video-deliveries"
PORT = 18767
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"\n     {detail}" if detail and not cond else ""), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pwsh", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--assets", required=True)
    ap.add_argument("--tool", choices=sorted(TOOLS), default="original")
    a = ap.parse_args()
    TOOL, sha = TOOLS[a.tool]
    check(f"0 {a.tool} DOWNLOAD.ps1 has the recorded SHA256 (original = byte-identical to the R2 ZIP)",
          hashlib.sha256(open(TOOL, "rb").read()).hexdigest() == sha)

    work = os.path.abspath(a.work)
    shutil.rmtree(work, ignore_errors=True)
    sim = os.path.join(work, "sim")
    os.makedirs(sim)
    srv_url = f"http://127.0.0.1:{PORT}"
    tool = ToolEnv(work, srv_url, a.pwsh, TOOL)
    base, run = tool.base, tool.run
    json.dump([], open(os.path.join(sim, "releases.json"), "w"))
    srv = subprocess.Popen([sys.executable, os.path.join(HERE, "github_sim.py"), str(PORT), sim])
    time.sleep(1)

    def add(tag, *ids):
        """Publish one batch exactly as opc_publish would (same manifest builder)."""
        date = opc_publish.TAG_RE.match(tag).group(1)
        test = all(i.startswith("TEST-") for i in ids)
        videos = opc_publish.load_packages([os.path.join(a.assets, i) for i in ids], test)
        m = opc_publish.build_manifest(REPO, date, tag, videos, test)
        d = os.path.join(sim, "assets", tag)
        os.makedirs(d, exist_ok=True)
        assets = []
        for e, zp in videos:
            shutil.copyfile(zp, os.path.join(d, e["asset_name"]))
        with open(os.path.join(d, opc_publish.MANIFEST_NAME), "w", encoding="utf-8") as f:
            f.write(json.dumps(m, ensure_ascii=False, indent=2) + "\n")
        for n in sorted(os.listdir(d)):
            assets.append(dict(name=n, size=os.path.getsize(os.path.join(d, n)), state="uploaded",
                               browser_download_url=f"https://github.com/{REPO}/releases/download/{tag}/{n}"))
        rp = os.path.join(sim, "releases.json")
        rel = json.load(open(rp))
        rel.insert(0, dict(tag_name=tag, draft=False, prerelease=False, assets=assets))
        json.dump(rel, open(rp, "w"), indent=1)
        return m

    def log_reset():
        open(os.path.join(sim, "access.log"), "w").close()

    def log_text():
        return open(os.path.join(sim, "access.log")).read()

    def ok_folder(day, vid):
        """All four files in ONE folder base/day/vid, each matching the manifest SHA256."""
        d = os.path.join(base, day, vid)
        want = sorted([f"{vid}.mp4", "cover.jpg", "subtitle.srt", "weibo.txt"])
        if not os.path.isdir(d) or sorted(os.listdir(d)) != want:
            return False
        e = json.load(open(os.path.join(a.assets, vid, "video-entry.json")))
        return all(hashlib.sha256(open(os.path.join(d, f["name"]), "rb").read()).hexdigest() == f["sha256"]
                   for f in e["files"])

    try:
        # manifest shape = original prepare_release.py shape
        m = add("delivery-2026-10-13-01", "SIM-0001")
        check("1a manifest keys are exactly the R2 keys",
              sorted(m) == ["delivery_date", "release_tag", "repository", "schema_version", "videos"]
              and m["schema_version"] == 1
              and all(sorted(v) == ["asset_name", "files", "sha256", "size_bytes", "video_id"] for v in m["videos"])
              and all(sorted(f) == ["name", "sha256", "size_bytes"] for v in m["videos"] for f in v["files"]), m)
        rc, out = run("2026-10-13")
        check("1b first run: four files in D:\\...\\2026-10-13\\SIM-0001, SHA256 verified", rc == 0 and ok_folder("2026-10-13", "SIM-0001"), out[-800:])

        log_reset()
        rc, out = run("2026-10-13")
        check("2 repeat run skips verified video, no ZIP download", rc == 0 and "-DELIVERY.zip" not in log_text() and ok_folder("2026-10-13", "SIM-0001"), out[-800:])

        add("delivery-2026-10-13-02", "SIM-0002")
        log_reset()
        rc, out = run("2026-10-13")
        lt = log_text()
        check("3 same-day batch 02 adds only the new video", rc == 0 and ok_folder("2026-10-13", "SIM-0002")
              and "SIM-0002-DELIVERY.zip" in lt and "SIM-0001-DELIVERY.zip" not in lt, out[-800:])

        add("delivery-2026-10-14-01", "SIM-0003")          # uploaded on the 13th for the 14th
        rc, out = run("2026-10-13")
        check("4a advance delivery for tomorrow is not downloaded today",
              rc == 0 and not os.path.exists(os.path.join(base, "2026-10-14")), out[-800:])
        rc, out = run("2026-10-14")
        check("4b advance delivery is downloaded on its delivery date", rc == 0 and ok_folder("2026-10-14", "SIM-0003"), out[-800:])

        add("delivery-2026-10-14-02", "SIM-0004")          # late batch for the 14th, uploaded on the 15th
        rc, out = run("2026-10-15")
        check("5 late batch fills its original date folder 2026-10-14", rc == 0 and ok_folder("2026-10-14", "SIM-0004")
              and not os.path.exists(os.path.join(base, "2026-10-15")), out[-800:])

        # interrupted download resumes with HTTP Range
        add("delivery-2026-10-16-01", "TEST-0002")
        open(os.path.join(sim, "throttle"), "w").write(str(1 << 20))
        log_reset()
        p = run("2026-10-16", background=True)
        part = os.path.join(base, "_DOWNLOAD-CACHE", "delivery-2026-10-16-01--TEST-0002-DELIVERY.zip.partial")
        for _ in range(100):
            if os.path.exists(part) and os.path.getsize(part) > 1 << 20:
                break
            time.sleep(0.1)
        os.killpg(p.pid, signal.SIGKILL)
        p.wait()
        cut = os.path.getsize(part) if os.path.exists(part) else 0
        os.remove(os.path.join(sim, "throttle"))
        log_reset()
        rc, out = run("2026-10-16")
        check(f"6 interrupted download ({cut} bytes kept) resumes with Range and verifies",
              0 < cut and rc == 0 and f"range=bytes={cut}-" in log_text() and ok_folder("2026-10-16", "TEST-0002"), out[-800:] + log_text()[-400:])

        # sandbox TEST batch: never in a default run, only via the date entry tool
        add("delivery-2099-12-31-01", "TEST-0001")
        rc, out = run("2026-10-16")
        check("7a default run ignores the 2099-12-31 TEST batch",
              rc == 0 and not os.path.exists(os.path.join(base, "2099-12-31")), out[-800:])
        rc, out = run("2026-10-16", "-Date", "2099-12-31")
        check("7b -Date 2099-12-31 downloads TEST-0001 into one folder", rc == 0 and ok_folder("2099-12-31", "TEST-0001"), out[-800:])
        log_reset()
        rc, out = run("2026-10-16", "-Date", "2099-12-31")
        check("7c repeat -Date run skips TEST-0001", rc == 0 and "-DELIVERY.zip" not in log_text(), out[-800:])

        # tampered local file is detected and never silently overwritten
        rcpt = os.path.join(base, "_已完成记录", "SIM-0001.json")
        os.remove(rcpt)
        w = os.path.join(base, "2026-10-13", "SIM-0001", "weibo.txt")
        data = bytearray(open(w, "rb").read()); data[0] ^= 1; open(w, "wb").write(data)
        rc, out = run("2026-10-16")
        check("8 tampered file fails SHA256, tool refuses to overwrite (exit 2)", rc == 2 and "SIM-0001" in out, out[-800:])
        data[0] ^= 1; open(w, "wb").write(data)
        rc, out = run("2026-10-16")
        check("8b after restoring the file the next run re-verifies and passes", rc == 0 and os.path.exists(rcpt), out[-800:])

        # publisher refuses to publish an id that is already published
        rel = json.load(open(os.path.join(sim, "releases.json")))
        check("9 publisher dedup: SIM-0001 already published is detected",
              "SIM-0001" in opc_publish.already_published_ids(rel))
    finally:
        srv.terminate()
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed ({a.tool} R2 DOWNLOAD.ps1, PowerShell 7 on Linux, local simulation)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
