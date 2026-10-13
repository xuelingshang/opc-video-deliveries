#!/usr/bin/env python3
"""Remove TEST delivery releases (and their tags) after the R2 download test.

Only a release that is provably a test batch is deleted:
  * tag delivery-2099-12-31-NN (the sandbox date, see opc_publish.TEST_DATE)
  * title starts with "[TEST]"
  * every asset is TEST-*-DELIVERY.zip or delivery-manifest.json
  * the manifest lists only TEST-* video ids
Anything else is refused and left untouched. Afterwards the release list is checked
again: no sandbox-date tag and no TEST-* asset may remain on any release.

    python3 opc_cleanup_test.py --repo OWNER/REPO [--tag delivery-2099-12-31-01] [--dry-run]
"""
import argparse, json, os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from opc_publish import MANIFEST_NAME, TEST_DATE, gh, list_releases, log

TEST_TAG_RE = re.compile(rf"^delivery-{TEST_DATE}-\d{{2,3}}$")
TEST_ASSET_RE = re.compile(r"^TEST(?:-[A-Z0-9]+)+-DELIVERY\.zip$")


def is_test_release(repo, r):
    if not TEST_TAG_RE.match(r["tag_name"]):
        return False, "tag is not on the sandbox date"
    if not (r.get("name") or "").startswith("[TEST]"):
        return False, "title does not start with [TEST]"
    names = [a["name"] for a in r.get("assets", [])]
    bad = [n for n in names if n != MANIFEST_NAME and not TEST_ASSET_RE.match(n)]
    if bad:
        return False, f"non-test assets {bad}"
    m = [a for a in r.get("assets", []) if a["name"] == MANIFEST_NAME]
    if m:
        with tempfile.NamedTemporaryFile() as tmp:
            subprocess.run(["gh", "api", "-H", "Accept: application/octet-stream",
                            f"repos/{repo}/releases/assets/{m[0]['id']}"], stdout=tmp, check=True)
            ids = [v["video_id"] for v in json.load(open(tmp.name, encoding="utf-8"))["videos"]]
        if not ids or any(not i.startswith("TEST-") for i in ids):
            return False, f"manifest lists non-test ids {ids}"
    return True, ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--tag", help="only this tag; default: every sandbox-date release")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    targets = [r for r in list_releases(a.repo)
               if (r["tag_name"] == a.tag if a.tag else TEST_TAG_RE.match(r["tag_name"]))]
    if a.tag and not targets:
        log(f"no release with tag {a.tag}")
    for r in targets:   # check every target before deleting any
        ok, why = is_test_release(a.repo, r)
        if not ok:
            raise SystemExit(f"refused, nothing deleted: {r['tag_name']}: {why}")
    for r in targets:
        log(f"deleting TEST release {r['tag_name']} ({r['html_url']})")
        if not a.dry_run:
            gh([f"repos/{a.repo}/releases/{r['id']}"], method="DELETE")
            gh([f"repos/{a.repo}/git/refs/tags/{r['tag_name']}"], method="DELETE", allow_fail=True)

    if a.dry_run:
        return
    left = list_releases(a.repo)
    dirty = [r["tag_name"] for r in left if TEST_TAG_RE.match(r["tag_name"]) or
             any(TEST_ASSET_RE.match(x["name"]) for x in r.get("assets", []))]
    if dirty:
        raise SystemExit(f"test content still present on releases: {dirty}")
    log(f"clean: {len(left)} release(s) remain, none on {TEST_DATE}, no TEST-* assets: "
        + json.dumps([r["tag_name"] for r in left]))


if __name__ == "__main__":
    main()
