#!/usr/bin/env python3
"""Offline scenario tests for tool/opc-download.ps1 against tests/github_sim.py.

This is a LOCAL SIMULATION of GitHub (same URL shapes, 302 redirect, HTTP Range). It proves
the tool's logic; it is not a test against the real GitHub Release or a real Windows PC.

    python3 tests/run_sim_tests.py --pwsh /path/to/pwsh --work /tmp/simwork --assets DIR
DIR must contain package folders built by publisher/opc_pack.py: SIM-0001..SIM-0004, TEST-0001.
"""
import argparse, json, os, shutil, signal, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tool", "opc-download.ps1")
PORT = 18765
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pwsh", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--assets", required=True)
    a = ap.parse_args()
    shutil.rmtree(a.work, ignore_errors=True)
    sim, root = os.path.join(a.work, "sim"), os.path.join(a.work, "OPC-DELIVERIES")
    os.makedirs(sim)
    json.dump([], open(os.path.join(sim, "releases.json"), "w"))
    srv = subprocess.Popen([sys.executable, os.path.join(HERE, "github_sim.py"), str(PORT), sim])
    time.sleep(1)
    base = f"http://127.0.0.1:{PORT}"

    def add(tag, *ids):
        subprocess.run([sys.executable, os.path.join(HERE, "sim_add_batch.py"), sim, tag] +
                       [os.path.join(a.assets, i) for i in ids], check=True, capture_output=True)

    def run(today, *extra, root_dir=None, background=False):
        cmd = [a.pwsh, "-NoProfile", "-File", TOOL, "-Root", root_dir or root, "-Today", today,
               "-ApiBase", base + "/api", "-WebBase", base + "/web", *extra]
        if background:
            return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        p = subprocess.run(cmd, capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    def files(vdir):
        return sorted(os.listdir(vdir)) if os.path.isdir(vdir) else []

    want = lambda vid: sorted([f"{vid}.mp4", "cover.jpg", "subtitle.srt", "weibo.txt"])
    try:
        # 1. first batch of the first day
        add("delivery-2026-10-13-01", "SIM-0001")
        rc, out = run("2026-10-13")
        check("1 first run downloads batch 01", rc == 0 and files(f"{root}/2026-10-13/SIM-0001") == want("SIM-0001"), out[-600:])
        # 2. re-run skips without network for the completed batch
        open(os.path.join(sim, "access.log"), "w").close()
        rc, out = run("2026-10-13")
        cdn_hits = [l for l in open(os.path.join(sim, "access.log")) if "/cdn/" in l]
        check("2 re-run skips verified video, no ZIP download", rc == 0 and "本批已全部校验完成，跳过" in out and not cdn_hits, out[-400:])
        # 3. same-day second batch + 4. not-yet-due batch
        add("delivery-2026-10-13-02", "SIM-0002")
        add("delivery-2026-10-20-01", "SIM-0004")
        rc, out = run("2026-10-13")
        check("3 same-day second batch downloaded", rc == 0 and files(f"{root}/2026-10-13/SIM-0002") == want("SIM-0002"), out[-600:])
        check("4 future batch not downloaded before its date", not os.path.exists(f"{root}/2026-10-20") and "未到期批次 1 个" in out, out[-400:])
        # 5. late fill: a 2026-10-13 batch published later, run on 10-15
        add("delivery-2026-10-13-03", "SIM-0003")
        rc, out = run("2026-10-15")
        check("5 late batch filled into its own date folder", rc == 0 and files(f"{root}/2026-10-13/SIM-0003") == want("SIM-0003"), out[-600:])
        # 6. due later
        rc, out = run("2026-10-20")
        check("6 batch downloaded once due", rc == 0 and files(f"{root}/2026-10-20/SIM-0004") == want("SIM-0004"), out[-600:])
        # 7. corruption: same size, different bytes -> quarantine + re-download
        cov = f"{root}/2026-10-13/SIM-0001/cover.jpg"
        data = bytearray(open(cov, "rb").read()); data[100] ^= 0xFF; open(cov, "wb").write(bytes(data))
        rc, out = run("2026-10-20")
        q = os.listdir(os.path.join(root, ".opc", "quarantine"))
        check("7 tampered file detected, old folder kept in quarantine, fresh copy installed",
              rc == 0 and len(q) == 1 and files(f"{root}/2026-10-13/SIM-0001") == want("SIM-0001") and "新下载 1 条" in out, out[-600:])
        # 8. resume after interruption (throttled server, process killed mid-download)
        root2 = os.path.join(a.work, "OPC-RESUME")
        open(os.path.join(sim, "throttle"), "w").write(str(1024 * 1024))
        p = run("2026-10-13", root_dir=root2, background=True)
        time.sleep(4)
        p.send_signal(signal.SIGKILL); p.wait()
        parts = [f for f in os.listdir(os.path.join(root2, ".opc", "downloads")) if f.endswith(".partial")]
        size_before = os.path.getsize(os.path.join(root2, ".opc", "downloads", parts[0])) if parts else 0
        os.remove(os.path.join(sim, "throttle"))
        os.remove(os.path.join(root2, ".opc", "lock")) if os.path.exists(os.path.join(root2, ".opc", "lock")) else None
        open(os.path.join(sim, "access.log"), "w").close()
        rc, out = run("2026-10-13", root_dir=root2)
        ranged = [l for l in open(os.path.join(sim, "access.log")) if "range=bytes=" in l]
        check("8 interrupted download resumes with HTTP Range and completes",
              bool(parts) and size_before > 0 and rc == 0 and "断点续传" in out and ranged
              and files(f"{root2}/2026-10-13/SIM-0001") == want("SIM-0001"), f"partial={size_before} " + out[-600:])
        # 9. API unavailable -> per-date fallback discovery
        root3 = os.path.join(a.work, "OPC-FALLBACK")
        open(os.path.join(sim, "api_down"), "w").close()
        rc, out = run("2026-10-20", root_dir=root3)
        os.remove(os.path.join(sim, "api_down"))
        got = sorted(os.listdir(os.path.join(root3, "2026-10-13"))) if os.path.isdir(os.path.join(root3, "2026-10-13")) else []
        check("9 API down: fallback finds all due batches", rc == 0 and "改为按日期逐批查找" in out
              and got == ["SIM-0001", "SIM-0002", "SIM-0003"] and os.path.isdir(f"{root3}/2026-10-20/SIM-0004"), out[-600:])
        # 10. TEST batch: skipped by default, separate folder with -IncludeTest
        add("delivery-2026-10-13-04", "TEST-0001")
        rc, out = run("2026-10-20")
        check("10a TEST sample not downloaded by default", rc == 0 and not os.path.exists(f"{root}/2026-10-13/TEST-0001")
              and not os.path.exists(f"{root}/_TEST") and "测试样片，未下载" in out, out[-600:])
        rc, out = run("2026-10-20", "-IncludeTest")
        check("10b -IncludeTest puts TEST sample under _TEST only", rc == 0 and files(f"{root}/_TEST/2026-10-13/TEST-0001") == want("TEST-0001")
              and not os.path.exists(f"{root}/2026-10-13/TEST-0001"), out[-600:])
        # 11. malicious / malformed entry is refused, nothing written outside the date folder
        bad_tag = "delivery-2026-10-14-01"
        add(bad_tag, "SIM-0001")
        mp = os.path.join(sim, "assets", bad_tag, "delivery-manifest.json")
        m = json.load(open(mp)); m["videos"][0]["files"][1]["path"] = "SIM-0001/../../evil.txt"; json.dump(m, open(mp, "w"))
        rc, out = run("2026-10-20")
        check("11 manifest with path outside the folder is refused", rc == 1 and "规范外的文件" in out
              and not os.path.exists(os.path.join(a.work, "evil.txt")) and not os.path.exists(f"{root}/2026-10-14"), out[-600:])
        # 12. second instance refused while one is running
        open(os.path.join(sim, "throttle"), "w").write(str(256 * 1024))
        root4 = os.path.join(a.work, "OPC-LOCK")
        p = run("2026-10-13", root_dir=root4, background=True)
        time.sleep(3)
        rc, out = run("2026-10-13", root_dir=root4)
        p.send_signal(signal.SIGKILL); p.wait()
        os.remove(os.path.join(sim, "throttle"))
        check("12 second concurrent run exits with code 3", rc == 3, out[-300:])
    finally:
        srv.terminate()
    ok = sum(1 for _, c, _ in results if c)
    print(f"\n{ok}/{len(results)} scenarios passed (local simulation)")
    json.dump([dict(name=n, passed=c) for n, c, _ in results], open(os.path.join(a.work, "sim-results.json"), "w"), ensure_ascii=False, indent=1)
    sys.exit(0 if ok == len(results) else 1)


if __name__ == "__main__":
    main()
