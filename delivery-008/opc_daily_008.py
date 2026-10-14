#!/usr/bin/env python3
"""AUTO-BATCH-008 delivery release: create the batch's own DRAFT release and append packaged videos to it.

Derived from opc-video-deliveries@0803e424 publisher/opc_daily.py (the 007 daily append tool, unchanged there and
vendored here only as its helper module vendor/opc_publish.py). Differences, all deliberate:

  * Release identity is 008-only: tag  delivery-008-YYYY-MM-DD-01,  name  AUTO-BATCH-008｜YYYY-MM-DD交付.
    The tool refuses any other tag, so it can never touch 007's delivery-YYYY-MM-DD-01 releases.
  * DRAFT only. There is no publish switch at all; a published 008 release is refused (rights are UNVERIFIED).
  * Only 008-NNN video ids are accepted.
  * Conflicts never overwrite: an asset of the same name is skipped when size + SHA256 match, and the run stops
    when a complete asset with a different SHA256 exists (in the manifest or not). Only a broken upload
    (asset state != uploaded) is removed and re-sent.
  * The caller (run_008.py in the owner-controlled workflow, or deliver_008.py for a local run from a clone of
    opc-video-deliveries) holds the cross-station lock (lock008.py) for the whole read-merge-write, and the
    manifest is still only replaced if it equals the copy read at the start (second guard against lost updates).

    python3 opc_daily_008.py --repo xuelingshang/opc-video-deliveries --date 2026-10-14 --pkg PKG/008-066 [--pkg ...]
    python3 opc_daily_008.py --repo ... --date 2026-10-14 --init        # create the empty draft only
"""
import argparse, datetime, hashlib, json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "vendor"))
import opc_publish as P  # noqa: E402

MAX_ASSETS = 1000
ID_RE = re.compile(r"^008-\d{3}$")
TAG_RE = re.compile(r"^delivery-008-(\d{4}-\d{2}-\d{2})-01$")


def tag_for(date):
    return f"delivery-008-{date}-01"


def name_for(date):
    return f"AUTO-BATCH-008｜{date}交付"


BODY = ("AUTO-BATCH-008 专用交付草稿（与 007 的 delivery-YYYY-MM-DD-01 完全分开）。\n\n"
        "每条视频一个 008-NNN-DELIVERY.zip（MP4、cover.jpg、weibo.txt、subtitle.srt），清单 delivery-manifest.json"
        "（schema_version 1）。各 008 工位只提交交付请求；由 opc-video-deliveries 仓库所有者控制的 delivery-008 工作流"
        "串行追加：同名同 SHA256 跳过，冲突不覆盖。\n\n"
        "素材及成片的对外发布权限：待验证（RIGHTS UNVERIFIED）。本 Release 只保留草稿，不自动发布。")


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


def find_release(repo, tag):
    return next((r for r in P.list_releases(repo) if r["tag_name"] == tag), None)


def ensure_draft(repo, date, target="main"):
    tag = tag_for(date)
    rel = find_release(repo, tag)
    if rel:
        if not rel["draft"]:
            raise SystemExit(f"{tag} is PUBLISHED; this tool only works on the 008 draft")
        if rel["name"] != name_for(date):
            raise SystemExit(f"{tag} exists with name {rel['name']!r}, expected {name_for(date)!r}; not adopting it")
        return rel, False
    rel = P.gh([f"repos/{repo}/releases", "-f", f"tag_name={tag}", "-f", f"target_commitish={target}",
                "-f", f"name={name_for(date)}", "-f", f"body={BODY}", "-F", "draft=true", "-F", "prerelease=false"],
               method="POST")
    P.log(f"  008 draft release created: id {rel['id']} {tag} {rel['name']}")
    return rel, True


def safe_upload(repo, rel, name, path, size, sha, content_type):
    """Like opc_publish.upload, but a complete asset with a different SHA256 is a conflict, never replaced."""
    for a in rel.get("assets", []):
        if a["name"] != name:
            continue
        if P.asset_ok(repo, a, size, sha):
            P.log(f"  {name}: present and verified (same size + SHA256), skip")
            return "skipped"
        if a.get("state") == "uploaded":
            raise SystemExit(f"CONFLICT {name}: a complete asset with different bytes is already on the release "
                             f"(digest {a.get('digest')}, size {a.get('size')}); nothing overwritten")
        P.log(f"  {name}: broken upload (state {a.get('state')}), removing it before re-sending")
        P.gh([f"repos/{repo}/releases/assets/{a['id']}"], method="DELETE")
    P.upload(repo, {**rel, "assets": [x for x in rel.get("assets", []) if x["name"] != name]}, name, path, size, sha,
             content_type)
    return "uploaded"


def append(repo, date, pkgs, backup_dir=None, report_path=None, dry_run=False):
    if datetime.date.fromisoformat(date).isoformat() != date:
        raise SystemExit("date must be YYYY-MM-DD")
    tag = tag_for(date)
    assert TAG_RE.match(tag)
    incoming = P.load_packages(pkgs, False) if pkgs else []
    for e, _ in incoming:
        if not ID_RE.match(e["video_id"]):
            raise SystemExit(f"{e['video_id']}: only 008-NNN ids go into {tag}")
    report = {"release_tag": tag, "release_name": name_for(date), "skipped": [], "uploaded": []}
    if dry_run:
        rel = find_release(repo, tag)
        P.log(f"{tag}: {'exists, draft=' + str(rel['draft']) if rel else 'missing (would be created as draft)'}; "
              f"{len(incoming)} package(s): {[e['video_id'] for e, _ in incoming]}")
        return report
    rel, created = ensure_draft(repo, date)
    report["created"] = created
    with tempfile.TemporaryDirectory() as td:
        cur, cur_bytes = read_manifest(repo, rel, td)
        zips = [x for x in rel.get("assets", []) if x["name"].endswith("-DELIVERY.zip")]
        if zips and not cur:
            raise SystemExit(f"{tag} has ZIPs but no {P.MANIFEST_NAME}; refusing to guess its records")
        if cur and (cur.get("release_tag") != tag or cur.get("delivery_date") != date):
            raise SystemExit(f"{tag}: manifest records {cur.get('release_tag')} / {cur.get('delivery_date')}")
        entries = list((cur or {}).get("videos", []))
        by_id = {e["video_id"]: e for e in entries}
        by_name = {e["asset_name"]: e for e in entries}
        seen = set()
        todo = []
        for e, zp in incoming:
            if e["video_id"] in seen:
                raise SystemExit(f"{e['video_id']} given twice")
            seen.add(e["video_id"])
            old = by_id.get(e["video_id"]) or by_name.get(e["asset_name"])
            if old:
                if (old["video_id"], old["asset_name"], old["size_bytes"], old["sha256"]) != \
                        (e["video_id"], e["asset_name"], e["size_bytes"], e["sha256"]):
                    raise SystemExit(f"CONFLICT {e['video_id']}: {tag} already records {old['asset_name']} sha256 "
                                     f"{old['sha256']}, new is {e['sha256']}; nothing overwritten")
                report["skipped"].append(e["video_id"])
            todo.append((e, zp, bool(old)))
        new_entries = entries + [e for e, _, had in todo if not had]
        if len(new_entries) + 1 > MAX_ASSETS:
            raise SystemExit(f"{tag} would hold {len(new_entries) + 1} assets (> {MAX_ASSETS})")
        manifest = P.build_manifest(repo, date, tag, [(e, None) for e in new_entries], False)
        mbytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        P.log(f"{tag} (draft {rel['id']}): {len(entries)} recorded, {len(todo) - len(report['skipped'])} to add, "
              f"{len(report['skipped'])} already there")
        for e, zp, _had in todo:
            rel = P.gh([f"repos/{repo}/releases/{rel['id']}"])
            if not rel["draft"]:
                raise SystemExit(f"{tag} became published during the run; stopping")
            if safe_upload(repo, rel, e["asset_name"], zp, e["size_bytes"], e["sha256"], "application/zip") == "uploaded":
                report["uploaded"].append(e["video_id"])
        rel = P.gh([f"repos/{repo}/releases/{rel['id']}"])
        got = {x["name"]: x for x in rel["assets"]}
        for e in new_entries:
            if e["asset_name"] not in got or not P.asset_ok(repo, got[e["asset_name"]], e["size_bytes"], e["sha256"]):
                raise SystemExit(f"verification failed for {e['asset_name']}; manifest left unchanged")
        extra = set(got) - {e["asset_name"] for e in new_entries} - {P.MANIFEST_NAME}
        if extra:
            raise SystemExit(f"unexpected assets on {tag} (another station's unfinished upload?): {sorted(extra)}; "
                             f"manifest left unchanged")
        now, now_bytes = read_manifest(repo, rel, td)
        if now_bytes != cur_bytes:
            raise SystemExit("the manifest changed while this run was uploading (another writer); rerun to merge again")
        if now_bytes != mbytes:
            if now_bytes and backup_dir:
                os.makedirs(backup_dir, exist_ok=True)
                open(os.path.join(backup_dir, f"{tag}.previous-{P.MANIFEST_NAME}"), "wb").write(now_bytes)
            old_m = got.get(P.MANIFEST_NAME)
            if old_m:
                P.gh([f"repos/{repo}/releases/assets/{old_m['id']}"], method="DELETE")
            mp = os.path.join(td, P.MANIFEST_NAME)
            open(mp, "wb").write(mbytes)
            rel = P.gh([f"repos/{repo}/releases/{rel['id']}"])
            P.upload(repo, rel, P.MANIFEST_NAME, mp, len(mbytes), hashlib.sha256(mbytes).hexdigest(), "application/json")
        expected = {e["asset_name"]: (e["size_bytes"], e["sha256"]) for e in new_entries}
        expected[P.MANIFEST_NAME] = (len(mbytes), hashlib.sha256(mbytes).hexdigest())
        rel = P.verify_assets(repo, rel["id"], expected)
        if not rel["draft"]:
            raise SystemExit(f"{tag} is not a draft after the run; investigate")
        assets = {x["name"]: {"size": x["size"], "digest": x.get("digest"), "state": x["state"]} for x in rel["assets"]}
        report.update(release_id=rel["id"], url=rel["html_url"], draft=rel["draft"], videos=len(new_entries),
                      video_ids=[e["video_id"] for e in new_entries], assets=assets,
                      manifest_sha256=expected[P.MANIFEST_NAME][1])
    P.log(json.dumps({k: v for k, v in report.items() if k != "assets"}, ensure_ascii=False))
    if report_path:
        os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)
        json.dump(report, open(report_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default="xuelingshang/opc-video-deliveries")
    ap.add_argument("--date", required=True)
    ap.add_argument("--pkg", action="append", default=[])
    ap.add_argument("--init", action="store_true", help="only create (or verify) the empty 008 draft")
    ap.add_argument("--backup-dir")
    ap.add_argument("--report")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.init:
        rel, created = ensure_draft(a.repo, a.date)
        print(json.dumps({"tag": rel["tag_name"], "name": rel["name"], "draft": rel["draft"], "id": rel["id"],
                          "url": rel["html_url"], "created": created}, ensure_ascii=False))
        return
    if not a.pkg:
        raise SystemExit("nothing to add: give --pkg (or --init)")
    append(a.repo, a.date, a.pkg, a.backup_dir, a.report, a.dry_run)


if __name__ == "__main__":
    main()
