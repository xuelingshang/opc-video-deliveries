#!/usr/bin/env python3
"""Tests for publisher/opc_gate.py (automatic QA + rights gate), with tests/fake_gh.py.

    python3 tests/run_gate_tests.py --work DIR --assets PKGDIR    (PKGDIR: SIM-0001, SIM-0002, SIM-0003)
"""
import argparse, json, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "publisher"))
import opc_gate

GATE = os.path.join(HERE, "..", "publisher", "opc_gate.py")
REPO = "xuelingshang/opc-video-deliveries"
PORT = 18769
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"\n     {detail}" if detail and not cond else ""), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--assets", required=True)
    a = ap.parse_args()
    ok = {"rights_confirmed": True, "public_distribution_approved": True}
    qa = {"V": {"machine_qa_pass": True}}
    check("G1 QA pass + rights confirmed + distribution approved -> PUBLIC (no Founder viewing needed)",
          opc_gate.decide("V", qa, {"V": dict(ok, founder_visual_pass=False)}) == ("PUBLIC", []))
    check("G2 rights not confirmed -> PRIVATE_PENDING", opc_gate.decide("V", qa, {"V": dict(ok, rights_confirmed=False)})[0] == "PRIVATE_PENDING")
    check("G3 QA missing -> PRIVATE_PENDING", opc_gate.decide("V", {}, {"V": ok})[0] == "PRIVATE_PENDING")
    check("G4 no rights record -> PRIVATE_PENDING", opc_gate.decide("V", qa, {})[0] == "PRIVATE_PENDING")
    check('G5 string "true" is not accepted as approval', opc_gate.decide("V", qa, {"V": dict(ok, rights_confirmed="true")})[0] == "PRIVATE_PENDING")

    work = os.path.abspath(a.work)
    shutil.rmtree(work, ignore_errors=True)
    gh_dir, sim, bindir = (os.path.join(work, x) for x in ("gh", "sim", "bin"))
    for d in (gh_dir, sim, bindir):
        os.makedirs(d)
    json.dump([], open(os.path.join(sim, "releases.json"), "w"))
    os.symlink(os.path.join(HERE, "fake_gh.py"), os.path.join(bindir, "gh"))
    env = dict(os.environ, PATH=bindir + os.pathsep + os.environ["PATH"], FAKE_GH_DIR=gh_dir, FAKE_GH_SIM=sim)
    srv = subprocess.Popen([sys.executable, os.path.join(HERE, "github_sim.py"), str(PORT), sim])
    time.sleep(1)
    try:
        json.dump({"SIM-0001": ok, "SIM-0002": dict(ok, rights_confirmed=False)}, open(os.path.join(work, "approvals.json"), "w"))
        json.dump({v: {"machine_qa_pass": True} for v in ("SIM-0001", "SIM-0002", "SIM-0003")}, open(os.path.join(work, "qa.json"), "w"))
        rep = os.path.join(work, "gate-report.json")
        sim_args = ["--web-base", f"http://127.0.0.1:{PORT}/web"]
        p = subprocess.run([sys.executable, GATE, *sim_args, "--approvals", os.path.join(work, "approvals.json"),
                            "--qa", os.path.join(work, "qa.json"), "--report", rep, "--publish", "--repo", REPO,
                            "--date", "2026-10-14"] + sum((["--pkg", os.path.join(a.assets, v)] for v in ("SIM-0001", "SIM-0002", "SIM-0003")), []),
                           capture_output=True, text=True, env=env)
        r = json.load(open(rep))
        st = json.load(open(os.path.join(gh_dir, "state.json")))["releases"]
        names = sorted(x["name"] for x in st[0]["assets"]) if st else []
        check("G6 batch: 1 PUBLIC, 2 PRIVATE_PENDING with reasons",
              r["SIM-0001"]["state"] == "PUBLIC" and r["SIM-0002"]["missing"] == ["rights_confirmed"]
              and r["SIM-0003"]["missing"] == ["rights_confirmed", "public_distribution_approved"], json.dumps(r))
        check("G7 release delivery-2026-10-14-01 holds only the PUBLIC video, published and anonymously verified",
              p.returncode == 0 and len(st) == 1 and st[0]["tag_name"] == "delivery-2026-10-14-01" and not st[0]["draft"]
              and names == ["SIM-0001-DELIVERY.zip", "delivery-manifest.json"] and "full SHA256 match" in p.stdout,
              (p.stdout + p.stderr)[-600:])
        json.dump({}, open(os.path.join(work, "approvals.json"), "w"))
        p = subprocess.run([sys.executable, GATE, *sim_args, "--approvals", os.path.join(work, "approvals.json"), "--qa",
                            os.path.join(work, "qa.json"), "--report", rep, "--publish", "--repo", REPO, "--date", "2026-10-15",
                            "--pkg", os.path.join(a.assets, "SIM-0002")], capture_output=True, text=True, env=env)
        check("G8 nothing publishable -> no release created", p.returncode == 0 and len(json.load(open(os.path.join(gh_dir, "state.json")))["releases"]) == 1,
              (p.stdout + p.stderr)[-300:])
    finally:
        srv.terminate()
    failed = [n for n, c in results if not c]
    print(f"\n{len(results) - len(failed)}/{len(results)} gate checks passed (local simulation)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
