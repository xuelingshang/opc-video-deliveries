#!/usr/bin/env python3
"""AUTO-BATCH-008 serial delivery, manual path: lock -> create/verify the 008 draft -> append -> unlock.

The normal path is the owner-controlled workflow in opc-video-deliveries (.github/workflows/delivery-008-draft.yml
-> delivery-008/run_008.py), which reads the stations' requests from the 008 repository as data and writes with
that repository's own GITHUB_TOKEN. This script is the same append for a person who runs it by hand:

    python3 delivery-008/deliver_008.py --station B --date 2026-10-14 --pkg PKG/008-066 [--pkg ...]
    python3 delivery-008/deliver_008.py --station B --date 2026-10-14 --init       # empty draft only
    python3 delivery-008/deliver_008.py --station B --date 2026-10-14 --status     # lock + release state

Run it from a clone of xuelingshang/opc-video-deliveries (the lock branch delivery-008-lock lives there, the same
one the workflow uses) with `gh` authenticated for that repository (contents: write). Re-running is always safe:
verified ZIPs are skipped, conflicts stop the run without overwriting. A JSON record of every run is written to
--records-dir (default ./delivery-008-records/<date>, outside git; never commit records to the public repository).
"""
import argparse, datetime, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lock008  # noqa: E402
import opc_daily_008 as D  # noqa: E402


def repo_root():
    return subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=HERE, capture_output=True, text=True,
                          check=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--station", required=True, help="A / B / C ... (written into the lock and the record)")
    ap.add_argument("--date", required=True)
    ap.add_argument("--repo", default="xuelingshang/opc-video-deliveries")
    ap.add_argument("--pkg", action="append", default=[])
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--wait-s", type=int, default=3600)
    ap.add_argument("--lock-branch", default=lock008.BRANCH)
    ap.add_argument("--records-dir")
    a = ap.parse_args()
    root = repo_root()
    lk = lock008.Lock(root, a.station, wait_s=a.wait_s, note=f"delivery-008-{a.date}-01", branch=a.lock_branch)
    if a.status:
        sha, msg = lk.tip()
        rel = D.find_release(a.repo, D.tag_for(a.date))
        print(json.dumps({"lock": msg, "lock_sha": sha,
                          "release": rel and {"tag": rel["tag_name"], "name": rel["name"], "draft": rel["draft"],
                                              "id": rel["id"], "url": rel["html_url"],
                                              "assets": [(x["name"], x["size"], x.get("digest")) for x in rel["assets"]]}},
                         ensure_ascii=False, indent=1))
        return
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rec_dir = a.records_dir or os.path.join(os.getcwd(), "delivery-008-records", a.date)
    with lk:
        if a.init or not a.pkg:
            rel, created = D.ensure_draft(a.repo, a.date)
            rep = {"station": a.station, "action": "init", "tag": rel["tag_name"], "name": rel["name"], "draft": rel["draft"],
                   "id": rel["id"], "url": rel["html_url"], "created": created, "lock": lk.mine}
            os.makedirs(rec_dir, exist_ok=True)
            json.dump(rep, open(os.path.join(rec_dir, f"{a.station}-{stamp}-init.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            print(json.dumps(rep, ensure_ascii=False))
            return
        rep_path = os.path.join(rec_dir, f"{a.station}-{stamp}.json")
        rep = D.append(a.repo, a.date, a.pkg, backup_dir=os.path.join(rec_dir, "manifest-backups"), report_path=rep_path)
        rep["station"], rep["lock"] = a.station, lk.mine
        json.dump(rep, open(rep_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
