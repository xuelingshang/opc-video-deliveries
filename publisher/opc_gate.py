#!/usr/bin/env python3
"""Automatic public gate for one delivery batch (no per-video human viewing).

A video is PUBLIC when, in the records, all of these hold:
  * machine_qa_pass is true                      (automatic technical QA, from --qa)
  * rights_confirmed is true                     (from --approvals, the private rights record)
  * public_distribution_approved is true         (from --approvals)
`founder_visual_pass` is no longer required. Nothing is ever set to true here: a video whose
rights are not recorded as confirmed stays PRIVATE_PENDING, with the reason in the report.

    python3 opc_gate.py --approvals approvals.json --qa qa.json --pkg DIR [--pkg DIR ...] \
        --report gate-report.json [--publish --repo OWNER/REPO --date YYYY-MM-DD]
qa.json: {"VIDEO-ID": {"machine_qa_pass": true}, ...}
With --publish, only the PUBLIC videos are handed to opc_publish.py as one batch.
"""
import argparse, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
NEEDED = (("machine_qa_pass", "qa"), ("rights_confirmed", "rights"), ("public_distribution_approved", "rights"))


def decide(vid, qa, rights):
    rec = {"machine_qa_pass": (qa.get(vid) or {}).get("machine_qa_pass"),
           "rights_confirmed": (rights.get(vid) or {}).get("rights_confirmed"),
           "public_distribution_approved": (rights.get(vid) or {}).get("public_distribution_approved")}
    missing = [k for k, _ in NEEDED if rec[k] is not True]   # only a literal true counts
    return ("PUBLIC" if not missing else "PRIVATE_PENDING"), missing


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--approvals", required=True)
    ap.add_argument("--qa", required=True)
    ap.add_argument("--pkg", action="append", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--repo")
    ap.add_argument("--date")
    ap.add_argument("--web-base", help=argparse.SUPPRESS)  # tests only, passed to opc_publish
    a = ap.parse_args()
    rights = json.load(open(a.approvals, encoding="utf-8-sig"))
    qa = json.load(open(a.qa, encoding="utf-8-sig"))
    report, public = {}, []
    for d in a.pkg:
        vid = json.load(open(os.path.join(d, "video-entry.json"), encoding="utf-8"))["video_id"]
        state, missing = decide(vid, qa, rights)
        report[vid] = {"state": state, "missing": missing}
        if state == "PUBLIC":
            public.append(d)
        print(f"{vid}: {state}" + (f" (missing: {', '.join(missing)})" if missing else ""), flush=True)
    with open(a.report, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"gate: {len(public)} public, {len(report) - len(public)} private pending")
    if a.publish and public:
        if not (a.repo and a.date):
            raise SystemExit("--publish needs --repo and --date")
        cmd = [sys.executable, os.path.join(HERE, "opc_daily.py"), "--repo", a.repo, "--date", a.date,
               "--confirm-public-gate", "--full-anon-verify"]   # gate decided above; appends to delivery-DATE-01
        for d in public:
            cmd += ["--pkg", d]
        if a.web_base:
            cmd += ["--web-base", a.web_base]
        sys.exit(subprocess.run(cmd).returncode)


if __name__ == "__main__":
    main()
