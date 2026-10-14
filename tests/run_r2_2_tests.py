#!/usr/bin/env python3
"""Acceptance tests for the R2.2 employee downloader (r2.2/DOWNLOAD.ps1), byte-unmodified,
against a local GitHub simulation (see tests/r2_env.py for what is substituted).

LOCAL SIMULATION ON POWERSHELL 7 / LINUX. Not a substitute for Windows PowerShell 5.1.

    python3 tests/run_r2_2_tests.py --pwsh /path/to/pwsh --work DIR --assets PKGDIR
PKGDIR: packages from publisher/opc_pack.py named SIM-0001..SIM-0004, RES-0001, BAD-0001,
TEST-0001, TEST-0002, plus ALT-SIM-0001 (video id SIM-0001 packed from different content).
"""
import argparse, hashlib, json, os, shutil, signal, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "publisher"))
import opc_publish
from r2_env import TOOLS, ToolEnv

REPO = "xuelingshang/opc-video-deliveries"
PORT = 18768
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"\n     {detail}" if detail and not cond else ""), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pwsh", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--assets", required=True)
    a = ap.parse_args()
    tool_path, sha = TOOLS["r2.2"]
    work = os.path.abspath(a.work)
    shutil.rmtree(work, ignore_errors=True)
    sim = os.path.join(work, "sim")
    os.makedirs(sim)
    json.dump([], open(os.path.join(sim, "releases.json"), "w"))
    srv = subprocess.Popen([sys.executable, os.path.join(HERE, "github_sim.py"), str(PORT), sim])
    time.sleep(1)
    url = f"http://127.0.0.1:{PORT}"
    t = ToolEnv(work, url, a.pwsh, tool_path)
    base, run = t.base, t.run

    def add(tag, *pkgs):
        date = opc_publish.TAG_RE.match(tag).group(1)
        test = all(p.startswith("TEST-") for p in pkgs)
        videos = opc_publish.load_packages([os.path.join(a.assets, p) for p in pkgs], test)
        m = opc_publish.build_manifest(REPO, date, tag, videos, test)
        d = os.path.join(sim, "assets", tag)
        os.makedirs(d, exist_ok=True)
        for e, zp in videos:
            shutil.copyfile(zp, os.path.join(d, e["asset_name"]))
        with open(os.path.join(d, opc_publish.MANIFEST_NAME), "w", encoding="utf-8") as f:
            f.write(json.dumps(m, ensure_ascii=False, indent=2) + "\n")
        assets = [dict(name=n, size=os.path.getsize(os.path.join(d, n)),
                       browser_download_url=f"https://github.com/{REPO}/releases/download/{tag}/{n}")
                  for n in sorted(os.listdir(d))]
        rp = os.path.join(sim, "releases.json")
        rel = json.load(open(rp))
        rel.insert(0, dict(tag_name=tag, draft=False, prerelease=False, assets=assets))
        json.dump(rel, open(rp, "w"))

    def zips():
        """ZIP bodies fetched from the CDN since the last reset (manifest fetches excluded)."""
        return [l for l in open(os.path.join(sim, "access.log")) if l.startswith("GET /cdn/") and "DELIVERY.zip" in l]

    def reset():
        open(os.path.join(sim, "access.log"), "w").close()

    def ok_folder(day, vid, pkg=None):
        d = os.path.join(base, day, vid)
        e = json.load(open(os.path.join(a.assets, pkg or vid, "video-entry.json")))
        return os.path.isdir(d) and sorted(os.listdir(d)) == sorted(f["name"] for f in e["files"]) and all(
            hashlib.sha256(open(os.path.join(d, f["name"]), "rb").read()).hexdigest() == f["sha256"] for f in e["files"])

    try:
        check("0 r2.2 DOWNLOAD.ps1 has the recorded SHA256",
              hashlib.sha256(open(tool_path, "rb").read()).hexdigest() == sha)
        rc, out = run("2026-10-13")
        check("1 empty repository: clear 'no new videos' message, exit 0", rc == 0 and "没有新的交付视频" in out, out[-400:])

        # old R2/R2.1 receipts stay valid: a folder fetched by the ORIGINAL R2 is skipped by R2.2
        add("delivery-2026-10-13-01", "SIM-0001")
        old = ToolEnv(os.path.join(work, "old"), url, a.pwsh, TOOLS["original"][0])
        old.base = base
        old.env["USERPROFILE"] = t.env["USERPROFILE"]
        rc0, out0 = old.run("2026-10-13")
        reset()
        rc, out = run("2026-10-13")
        check("2 R2.2 accepts folders and records left by the original R2 (no re-download)",
              rc0 == 0 and rc == 0 and ok_folder("2026-10-13", "SIM-0001") and not zips() and "没有新的交付视频" in out, out0[-300:] + out[-300:])

        add("delivery-2026-10-13-02", "SIM-0002")       # same date, second batch
        add("delivery-2026-10-14-01", "SIM-0003")       # future delivery date, already published
        reset()
        rc, out = run("2026-10-13")
        check("3 several releases: same-day batch 02 downloaded", rc == 0 and ok_folder("2026-10-13", "SIM-0002"), out[-600:])
        check("4 future-dated published batch downloaded early on 10-13 into its 2026-10-14 folder",
              ok_folder("2026-10-14", "SIM-0003") and len(zips()) == 2, out[-600:])

        add("delivery-2026-10-15-01", "SIM-0004")       # added later, another date
        reset()
        rc, out = run("2026-10-13")
        check("5 newly added batch on another date is filled automatically, nothing else fetched",
              rc == 0 and ok_folder("2026-10-15", "SIM-0004") and len(zips()) == 1, out[-600:])

        reset()
        rc, out = run("2026-10-13")
        check("6 repeat run skips all verified videos and says there is nothing new",
              rc == 0 and not zips() and "没有新的交付视频" in out and "跳过已下载: 4" in out, out[-600:])

        # interrupted download resumes with HTTP Range
        open(os.path.join(sim, "throttle"), "w").write(str(1 << 20))
        add("delivery-2026-10-16-01", "RES-0001")
        reset()
        p = run("2026-10-13", background=True)
        part = os.path.join(base, "_DOWNLOAD-CACHE", "delivery-2026-10-16-01--RES-0001-DELIVERY.zip.partial")
        for _ in range(100):
            if os.path.exists(part) and os.path.getsize(part) > 1 << 20:
                break
            time.sleep(0.1)
        os.killpg(p.pid, signal.SIGKILL)
        p.wait()
        cut = os.path.getsize(part) if os.path.exists(part) else 0
        os.remove(os.path.join(sim, "throttle"))
        reset()
        rc, out = run("2026-10-13")
        check(f"7 interrupted download ({cut} bytes kept) resumes with Range and verifies",
              0 < cut and rc == 0 and f"range=bytes={cut}-" in open(os.path.join(sim, "access.log")).read()
              and ok_folder("2026-10-16", "RES-0001"), out[-600:])

        # server copy corrupted (same size, wrong bytes): refused, nothing delivered
        add("delivery-2026-10-17-01", "BAD-0001")
        zp = os.path.join(sim, "assets", "delivery-2026-10-17-01", "BAD-0001-DELIVERY.zip")
        data = bytearray(open(zp, "rb").read()); data[len(data) // 2] ^= 0xFF; open(zp, "wb").write(data)
        rc, out = run("2026-10-13")
        check("8a SHA256 mismatch on download: refused (exit 2), no folder, no record",
              rc == 2 and not os.path.exists(os.path.join(base, "2026-10-17", "BAD-0001"))
              and not os.path.exists(os.path.join(base, "_已完成记录", "BAD-0001.json")), out[-600:])
        shutil.rmtree(os.path.join(sim, "assets", "delivery-2026-10-17-01"))
        rel = json.load(open(os.path.join(sim, "releases.json")))
        json.dump([r for r in rel if r["tag_name"] != "delivery-2026-10-17-01"], open(os.path.join(sim, "releases.json"), "w"))

        # same id re-published with different content: refused, good copy untouched
        before = {f: hashlib.sha256(open(os.path.join(base, "2026-10-13", "SIM-0001", f), "rb").read()).hexdigest()
                  for f in os.listdir(os.path.join(base, "2026-10-13", "SIM-0001"))}
        add("delivery-2026-10-18-01", "ALT-SIM-0001")
        rc, out = run("2026-10-13")
        after = {f: hashlib.sha256(open(os.path.join(base, "2026-10-13", "SIM-0001", f), "rb").read()).hexdigest()
                 for f in os.listdir(os.path.join(base, "2026-10-13", "SIM-0001"))}
        check("8b same video id with different content: refused (exit 2), verified copy unchanged",
              rc == 2 and before == after and ok_folder("2026-10-13", "SIM-0001")
              and not os.path.exists(os.path.join(base, "2026-10-18", "SIM-0001")), out[-600:])
        rel = json.load(open(os.path.join(sim, "releases.json")))
        json.dump([r for r in rel if r["tag_name"] != "delivery-2026-10-18-01"], open(os.path.join(sim, "releases.json"), "w"))

        # local file damaged: never silently overwritten
        rcpt = os.path.join(base, "_已完成记录", "SIM-0002.json")
        os.remove(rcpt)
        w = os.path.join(base, "2026-10-13", "SIM-0002", "weibo.txt")
        orig = open(w, "rb").read()
        open(w, "wb").write(bytes([orig[0] ^ 1]) + orig[1:])
        rc, out = run("2026-10-13")
        check("8c damaged local file: SHA256 fails, tool refuses to overwrite (exit 2)",
              rc == 2 and open(w, "rb").read() != orig, out[-600:])
        open(w, "wb").write(orig)
        rc, out = run("2026-10-13")
        check("8d after restoring, the next run re-verifies and passes", rc == 0 and os.path.exists(rcpt), out[-600:])

        # TEST sandbox
        add("delivery-2099-12-31-01", "TEST-0001")
        reset()
        rc, out = run("2026-10-13")
        check("9a default run never downloads the 2099-12-31 TEST sandbox",
              rc == 0 and not zips() and not os.path.exists(os.path.join(base, "2099-12-31")), out[-600:])
        rc, out = run("2026-10-13", "-Tag", "delivery-2099-12-31-01")
        check("9b explicit -Tag downloads the TEST sample into one folder", rc == 0 and ok_folder("2099-12-31", "TEST-0001"), out[-600:])
        add("delivery-2099-12-31-02", "TEST-0002")
        rc, out = run("2026-10-13", "-Date", "2099-12-31")
        check("9c explicit -Date 2099-12-31 adds TEST-0002 and skips TEST-0001",
              rc == 0 and ok_folder("2099-12-31", "TEST-0002") and "跳过已下载: 1" in out, out[-600:])
        reset()
        rc, out = run("2026-10-13")
        check("9d default run after TEST batches still only reports formal videos, nothing new",
              rc == 0 and not zips() and "没有新的交付视频" in out, out[-600:])
    finally:
        srv.terminate()
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed (r2.2 DOWNLOAD.ps1, PowerShell 7 on Linux, local simulation)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
