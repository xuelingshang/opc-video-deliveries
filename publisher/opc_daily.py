#!/usr/bin/env python3
"""Daily delivery release: one release per delivery date, `delivery-YYYY-MM-DD-01`, and every
production station APPENDS its videos to it. Never creates -02, -03 ... for the same date.

    # append packaged videos (opc_pack.py output dirs) to the day's release, kept as draft
    python3 opc_daily.py --repo OWNER/REPO --date 2026-10-15 --pkg out/pkg/007-071 [--pkg ...] --keep-draft
    # move the videos of an older same-day batch release into the day's release, then remove it
    python3 opc_daily.py --repo OWNER/REPO --date 2026-10-14 --from-release delivery-2026-10-14-02 --keep-draft --delete-source
    # after the public gate passed (opc_gate.py passes this), append and publish
    python3 opc_daily.py ... --confirm-public-gate --full-anon-verify

Rules
  * The release is found by tag (draft or published); created as a draft only if missing.
  * Existing ZIPs and manifest entries are never modified: same name + same size + SHA256 -> skip;
    same name or video id with a different SHA256 -> error, nothing is overwritten.
  * The manifest is the merge of the release's current manifest and the new entries (old order kept).
    It is replaced only after every ZIP is uploaded and verified, and only if it still equals the
    manifest read at the start (a concurrent writer makes this run stop; rerun to continue).
  * Re-running after a failure resumes: verified uploads are skipped, broken ones replaced.
  * Adding to a PUBLISHED release requires --confirm-public-gate (nothing unapproved is exposed);
    --keep-draft never publishes and refuses a published release.
  * --delete-source removes the source release only if it is a draft and every one of its videos is
    in the day's verified manifest with the same SHA256.
  * Limits: GitHub allows up to 1000 assets per release and < 2 GiB per asset (checked).
Uses `gh api` like opc_publish.py (GH_TOKEN with contents:write).
"""
import argparse, datetime, hashlib, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import opc_publish as P  # noqa: E402  (gh, upload, verify_assets, load_packages, anonymous_check, ...)

MAX_ASSETS = 1000


def download(repo, asset, dst):
    with open(dst, "wb") as f:
        subprocess.run(["gh", "api", "-H", "Accept: application/octet-stream", f"repos/{repo}/releases/assets/{asset['id']}"],
                       stdout=f, check=True)
    return dst


def read_manifest(repo, rel, td):
    a = next((x for x in rel.get("assets", []) if x["name"] == P.MANIFEST_NAME), None)
    if not a:
        return None, None
    b = open(download(repo, a, os.path.join(td, f"manifest-{rel['id']}.json")), "rb").read()
    return json.loads(b), b


def find(releases, tag):
    return next((r for r in releases if r["tag_name"] == tag), None)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--date", required=True, help="delivery date YYYY-MM-DD (may be in the future)")
    ap.add_argument("--pkg", action="append", default=[], help="package dir with video-entry.json + ZIP")
    ap.add_argument("--from-release", help="tag of another same-day release whose videos are moved in")
    ap.add_argument("--delete-source", action="store_true", help="remove --from-release after full verification")
    ap.add_argument("--keep-draft", action="store_true", help="never publish; refuse a published release")
    ap.add_argument("--confirm-public-gate", action="store_true", help="only from opc_gate.py after the gate passed")
    ap.add_argument("--test", action="store_true", help="TEST-* ids on the sandbox date only")
    ap.add_argument("--target", default="main")
    ap.add_argument("--full-anon-verify", action="store_true")
    ap.add_argument("--backup-dir", help="keep the previous manifest here before it is replaced")
    ap.add_argument("--report", help="write a JSON report here")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--web-base", default="https://github.com", help=argparse.SUPPRESS)
    a = ap.parse_args()

    if datetime.date.fromisoformat(a.date).isoformat() != a.date:
        raise SystemExit("date must be YYYY-MM-DD")
    if a.test != (a.date == P.TEST_DATE):
        raise SystemExit(f"test batches use delivery date {P.TEST_DATE} only, formal batches never")
    if a.keep_draft == a.confirm_public_gate:
        raise SystemExit("choose exactly one of --keep-draft / --confirm-public-gate")
    if not a.pkg and not a.from_release:
        raise SystemExit("nothing to add: give --pkg and/or --from-release")
    tag = f"delivery-{a.date}-01"
    if a.from_release == tag:
        raise SystemExit("--from-release is the day's release itself")

    releases = P.list_releases(a.repo)
    rel = find(releases, tag)
    if rel and not rel["draft"] and a.keep_draft:
        raise SystemExit(f"{tag} is published; appending unapproved videos would expose them (needs --confirm-public-gate)")
    report = {"release_tag": tag, "skipped": [], "uploaded": [], "moved_from": a.from_release}
    with tempfile.TemporaryDirectory() as td:
        # ---- current state of the day's release
        cur, cur_bytes = (read_manifest(a.repo, rel, td) if rel else (None, None))
        zips = [x for x in (rel or {}).get("assets", []) if x["name"].endswith("-DELIVERY.zip")]
        if zips and not cur:
            raise SystemExit(f"{tag} has ZIPs but no {P.MANIFEST_NAME}; refusing to guess its records")
        if cur and (cur.get("release_tag") != tag or cur.get("delivery_date") != a.date):
            raise SystemExit(f"{tag}: manifest records {cur.get('release_tag')} / {cur.get('delivery_date')}")
        entries = list((cur or {}).get("videos", []))
        by_id = {e["video_id"]: e for e in entries}
        by_name = {e["asset_name"]: e for e in entries}

        # ---- incoming videos: packages and/or another release
        incoming = [(e, zp) for e, zp in P.load_packages(a.pkg, a.test)] if a.pkg else []
        src = src_entries = None
        if a.from_release:
            src = find(releases, a.from_release)
            if not src:
                raise SystemExit(f"source release {a.from_release} not found")
            sm, _ = read_manifest(a.repo, src, td)
            if not sm:
                raise SystemExit(f"source release {a.from_release} has no manifest")
            src_assets = {x["name"]: x for x in src["assets"]}
            src_entries = sm["videos"]
            for e in src_entries:
                sa = src_assets.get(e["asset_name"])
                if not sa or not P.asset_ok(a.repo, sa, e["size_bytes"], e["sha256"]):
                    raise SystemExit(f"source asset {e['asset_name']} missing or not matching its manifest")
                incoming.append((e, ("release", sa)))
        names_seen = set()
        for e, _ in incoming:
            if e["video_id"] in names_seen:
                raise SystemExit(f"{e['video_id']} given twice")
            names_seen.add(e["video_id"])
            if a.test != e["video_id"].startswith("TEST-"):
                raise SystemExit(f"{e['video_id']}: test batches hold only TEST-* ids, formal batches none")
            if e["asset_name"] != f"{e['video_id']}-DELIVERY.zip" or e["size_bytes"] >= 2 * 1024 ** 3:
                raise SystemExit(f"{e['video_id']}: bad asset name or size")
        # a video already published in ANOTHER release is never uploaded twice
        published = {v: t for v, t in P.already_published_ids(releases).items() if t != tag}
        dup = {e["video_id"]: published[e["video_id"]] for e, _ in incoming if e["video_id"] in published}
        if dup:
            raise SystemExit(f"already published in another release: {dup}")

        todo = []
        for e, src_ref in incoming:
            old = by_id.get(e["video_id"]) or by_name.get(e["asset_name"])
            if old:
                if (old["video_id"], old["asset_name"], old["size_bytes"], old["sha256"]) != \
                        (e["video_id"], e["asset_name"], e["size_bytes"], e["sha256"]):
                    raise SystemExit(f"CONFLICT {e['video_id']}: {tag} already holds {old['asset_name']} "
                                     f"sha256 {old['sha256']}, new is {e['sha256']}; nothing overwritten")
                report["skipped"].append(e["video_id"])
            todo.append((e, src_ref, bool(old)))
        new_entries = entries + [e for e, _, had in todo if not had]
        if len(new_entries) + 1 > MAX_ASSETS:
            raise SystemExit(f"{tag} would hold {len(new_entries) + 1} assets (> {MAX_ASSETS})")
        manifest = P.build_manifest(a.repo, a.date, tag, [(e, None) for e in new_entries], a.test)
        mbytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        P.log(f"{tag}: {'existing ' + ('draft' if rel['draft'] else 'PUBLISHED') if rel else 'new draft'}; "
              f"{len(entries)} recorded, {len(todo) - len(report['skipped'])} to add, {len(report['skipped'])} already there")
        if a.dry_run:
            P.log(mbytes.decode())
            return

        if not rel:
            rel = P.gh([f"repos/{a.repo}/releases", "-f", f"tag_name={tag}", "-f", f"target_commitish={a.target}",
                        "-f", f"name={('[TEST] ' if a.test else '')}OPC 交付 {a.date}", "-f",
                        "body=每日交付：当天全部视频都在本 Release；清单 delivery-manifest.json（schema_version 1）。",
                        "-F", "draft=true", "-F", "prerelease=false"], method="POST")
            P.log(f"  draft release created: id {rel['id']}")

        # ---- ZIPs first (resumable). Existing verified copies are skipped by upload().
        for e, src_ref, _had in todo:
            rel = P.gh([f"repos/{a.repo}/releases/{rel['id']}"])
            have = next((x for x in rel["assets"] if x["name"] == e["asset_name"]), None)
            if have and P.asset_ok(a.repo, have, e["size_bytes"], e["sha256"]):
                P.log(f"  {e['asset_name']}: present and verified, skip")
                continue
            if have and any(x["asset_name"] == e["asset_name"] for x in entries):
                raise SystemExit(f"{e['asset_name']} is recorded in the manifest but the asset is damaged; not touching it")
            path = src_ref
            if isinstance(src_ref, tuple):        # copy from the source release, checked before upload
                path = download(a.repo, src_ref[1], os.path.join(td, e["asset_name"]))
                if os.path.getsize(path) != e["size_bytes"] or P.sha256_file(path) != e["sha256"]:
                    raise SystemExit(f"downloaded {e['asset_name']} does not match its record")
            P.upload(a.repo, rel, e["asset_name"], path, e["size_bytes"], e["sha256"], "application/zip")
            report["uploaded"].append(e["video_id"])
            if isinstance(src_ref, tuple):
                os.remove(path)

        # ---- verify every ZIP before the manifest changes
        rel = P.gh([f"repos/{a.repo}/releases/{rel['id']}"])
        got = {x["name"]: x for x in rel["assets"]}
        for e in new_entries:
            if e["asset_name"] not in got or not P.asset_ok(a.repo, got[e["asset_name"]], e["size_bytes"], e["sha256"]):
                raise SystemExit(f"verification failed for {e['asset_name']}; manifest left unchanged")
        extra = set(got) - {e["asset_name"] for e in new_entries} - {P.MANIFEST_NAME}
        if extra:
            raise SystemExit(f"unexpected assets on {tag}: {sorted(extra)}")

        # ---- manifest last: replace only if nobody changed it meanwhile
        now, now_bytes = read_manifest(a.repo, rel, td)
        if now_bytes != cur_bytes:
            raise SystemExit("the manifest changed while this run was uploading (another writer); rerun to merge again")
        if now_bytes != mbytes:
            if now_bytes and a.backup_dir:
                os.makedirs(a.backup_dir, exist_ok=True)
                open(os.path.join(a.backup_dir, f"{tag}.previous-{P.MANIFEST_NAME}"), "wb").write(now_bytes)
            old_m = got.get(P.MANIFEST_NAME)
            if old_m:
                P.gh([f"repos/{a.repo}/releases/assets/{old_m['id']}"], method="DELETE")
            mp = os.path.join(td, P.MANIFEST_NAME)
            open(mp, "wb").write(mbytes)
            rel = P.gh([f"repos/{a.repo}/releases/{rel['id']}"])
            P.upload(a.repo, rel, P.MANIFEST_NAME, mp, len(mbytes), hashlib.sha256(mbytes).hexdigest(), "application/json")
        expected = {e["asset_name"]: (e["size_bytes"], e["sha256"]) for e in new_entries}
        expected[P.MANIFEST_NAME] = (len(mbytes), hashlib.sha256(mbytes).hexdigest())
        rel = P.verify_assets(a.repo, rel["id"], expected)

        # ---- publish only through the gate
        if a.confirm_public_gate and rel["draft"]:
            rel = P.gh([f"repos/{a.repo}/releases/{rel['id']}", "-F", "draft=false", "-f",
                        f"make_latest={'false' if a.test else 'true'}"], method="PATCH")
            P.log(f"  published: {rel['html_url']}")
        if not rel["draft"]:
            P.anonymous_check(a.repo, tag, mbytes, [(e, None) for e in new_entries], a.full_anon_verify, a.web_base)

        # ---- remove the moved-from release only when everything is verified
        if a.from_release and a.delete_source:
            srel = P.gh([f"repos/{a.repo}/releases/{src['id']}"])
            if not srel["draft"]:
                raise SystemExit(f"{a.from_release} is published; not deleting it")
            rec = {e["video_id"]: e["sha256"] for e in new_entries}
            if any(rec.get(e["video_id"]) != e["sha256"] for e in src_entries):
                raise SystemExit(f"{a.from_release} holds videos not verified in {tag}; kept")
            P.gh([f"repos/{a.repo}/releases/{src['id']}"], method="DELETE")
            P.gh([f"repos/{a.repo}/git/refs/tags/{a.from_release}"], method="DELETE", allow_fail=True)  # drafts have none
            report["source_deleted"] = True
            P.log(f"  removed duplicate release {a.from_release}")

        report.update(release_id=rel["id"], url=rel["html_url"], draft=rel["draft"], videos=len(new_entries),
                      assets=len(expected), manifest_sha256=expected[P.MANIFEST_NAME][1])
        P.log(json.dumps(report, ensure_ascii=False))
        if a.report:
            json.dump(report, open(a.report, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
