#!/usr/bin/env python3
"""AUTO-BATCH-009 delivery release: create the batch's own DRAFT release and append packaged videos to it.

Same append as delivery-008/opc_daily_008.py (itself derived from publisher/opc_daily.py@0803e424), for 009:

  * Release identity is 009-only: the tag and name come from delivery-009/SOURCES.json (delivery-009-YYYY-MM-DD-NN,
    "AUTO-BATCH-009｜YYYY-MM-DD交付"). Any other tag is refused, so no 007 or 008 release can be touched.
  * DRAFT only. There is no publish switch; a published 009 release is refused (rights are UNVERIFIED).
  * Only 009-NNN video ids are accepted.
  * Conflicts never overwrite: an asset of the same name is skipped when size + SHA256 match, and the run stops when
    a complete asset with a different SHA256 exists. Only a broken upload (state != uploaded) is removed and re-sent.
  * Besides delivery-manifest.json (R2 schema_version 1, unchanged), the draft carries delivery-009-records.json:
    per video the source branch, commit, station ZIP, MP4 hash and the station's own fact / rights / review status,
    copied as recorded. It is replaced together with the manifest, under the same lock.

    python3 opc_daily_009.py --config SOURCES.json --pkg PKG/009-043 [--pkg ...]
    python3 opc_daily_009.py --config SOURCES.json --init        # create the empty draft only
"""
import argparse, datetime, hashlib, json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "vendor"))
import opc_publish as P  # noqa: E402

MAX_ASSETS = 1000
ID_RE = re.compile(r"^009-\d{3}$")
TAG_RE = re.compile(r"^delivery-009-(\d{4}-\d{2}-\d{2})-(\d{2})$")
RECORDS_NAME = "delivery-009-records.json"

BODY = ("AUTO-BATCH-009 专用交付草稿（与 007、008 的 Release 完全分开）。\n\n"
        "每条视频一个完整的 009-NNN-DELIVERY.zip（1080p MP4、cover.jpg、weibo.txt、subtitle.srt），直接下载即可，"
        "无需合并分片。ZIP 由 opc-video-deliveries 仓库所有者控制的 delivery-009 工作流从各工位已提交的分片恢复，"
        "逐片与整包核对 SHA256、检查内部结构后原样重新存放（未重新配音、剪辑、渲染）。\n\n"
        "清单 delivery-manifest.json（schema_version 1）；delivery-009-records.json 逐条记录来源分支、提交、"
        "工位 ZIP 与各工位自己记录的事实核验、版权与内部审片状态。\n\n"
        "Founder 本轮接受现有制作质量，不代表公开发布授权。素材及成片的对外发布权限：待验证（RIGHTS UNVERIFIED）。"
        "本 Release 只保留草稿，不自动发布。")


def release_cfg(cfg):
    r = cfg["release"]
    m = TAG_RE.fullmatch(r["tag"])
    if not m or m.group(1) != r["date"] or datetime.date.fromisoformat(r["date"]).isoformat() != r["date"]:
        raise SystemExit(f"bad 009 release config {r}")
    if not r["name"].startswith("AUTO-BATCH-009｜"):
        raise SystemExit(f"009 release name must start with AUTO-BATCH-009｜: {r['name']!r}")
    return r["tag"], r["name"], r["date"]


def download(repo, asset, dst):
    with open(dst, "wb") as f:
        subprocess.run(["gh", "api", "-H", "Accept: application/octet-stream", f"repos/{repo}/releases/assets/{asset['id']}"],
                       stdout=f, check=True)
    return dst


def read_asset_json(repo, rel, name, td):
    a = next((x for x in rel.get("assets", []) if x["name"] == name), None)
    if not a:
        return None, None
    b = open(download(repo, a, os.path.join(td, f"{rel['id']}-{name}")), "rb").read()
    return json.loads(b), b


def find_release(repo, tag):
    return next((r for r in P.list_releases(repo) if r["tag_name"] == tag), None)


def ensure_draft(repo, cfg, target="main"):
    tag, name, _ = release_cfg(cfg)
    rel = find_release(repo, tag)
    if rel:
        if not rel["draft"]:
            raise SystemExit(f"{tag} is PUBLISHED; this tool only works on the 009 draft")
        if rel["name"] != name:
            raise SystemExit(f"{tag} exists with name {rel['name']!r}, expected {name!r}; not adopting it")
        return rel, False
    rel = P.gh([f"repos/{repo}/releases", "-f", f"tag_name={tag}", "-f", f"target_commitish={target}",
                "-f", f"name={name}", "-f", f"body={BODY}", "-F", "draft=true", "-F", "prerelease=false"], method="POST")
    P.log(f"  009 draft release created: id {rel['id']} {tag}")
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


def _replace(repo, rel, got, name, data, td):
    old = got.get(name)
    if old:
        P.gh([f"repos/{repo}/releases/assets/{old['id']}"], method="DELETE")
    p = os.path.join(td, name)
    open(p, "wb").write(data)
    rel = P.gh([f"repos/{repo}/releases/{rel['id']}"])
    P.upload(repo, rel, name, p, len(data), hashlib.sha256(data).hexdigest(), "application/json")


def append(repo, cfg, pkgs, records=None, report_path=None):
    """Append packages (dirs with video-entry.json + ZIP); `records` = {video_id: record} for delivery-009-records.json."""
    tag, _name, date = release_cfg(cfg)
    incoming = P.load_packages(pkgs, False) if pkgs else []
    for e, _ in incoming:
        if not ID_RE.match(e["video_id"]):
            raise SystemExit(f"{e['video_id']}: only 009-NNN ids go into {tag}")
    report = {"release_tag": tag, "skipped": [], "uploaded": []}
    rel, created = ensure_draft(repo, cfg)
    report["created"] = created
    with tempfile.TemporaryDirectory() as td:
        cur, cur_bytes = read_asset_json(repo, rel, P.MANIFEST_NAME, td)
        cur_rec, cur_rec_bytes = read_asset_json(repo, rel, RECORDS_NAME, td)
        zips = [x for x in rel.get("assets", []) if x["name"].endswith("-DELIVERY.zip")]
        if zips and not cur:
            raise SystemExit(f"{tag} has ZIPs but no {P.MANIFEST_NAME}; refusing to guess its records")
        if cur and (cur.get("release_tag") != tag or cur.get("delivery_date") != date):
            raise SystemExit(f"{tag}: manifest records {cur.get('release_tag')} / {cur.get('delivery_date')}")
        entries = list((cur or {}).get("videos", []))
        by_id = {e["video_id"]: e for e in entries}
        by_name = {e["asset_name"]: e for e in entries}
        by_sha = {e["sha256"]: e["video_id"] for e in entries}
        seen, todo = set(), []
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
            elif e["sha256"] in by_sha:
                raise SystemExit(f"{e['video_id']}: the same ZIP SHA256 is already on {tag} as {by_sha[e['sha256']]}")
            todo.append((e, zp, bool(old)))
        new_entries = entries + [e for e, _, had in todo if not had]
        if len(new_entries) + 2 > MAX_ASSETS:
            raise SystemExit(f"{tag} would hold {len(new_entries) + 2} assets (> {MAX_ASSETS})")
        manifest = P.build_manifest(repo, date, tag, [(e, None) for e in new_entries], False)
        mbytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        recs = dict((cur_rec or {}).get("videos", {}))
        for vid, r in (records or {}).items():
            if vid in {e["video_id"] for e in new_entries} and vid not in recs:
                recs[vid] = r
        rbytes = (json.dumps({"schema": "OPC-DELIVERY-009-RECORDS/1", "release_tag": tag,
                              "videos": dict(sorted(recs.items()))}, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
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
        extra = set(got) - {e["asset_name"] for e in new_entries} - {P.MANIFEST_NAME, RECORDS_NAME}
        if extra:
            raise SystemExit(f"unexpected assets on {tag}: {sorted(extra)}; manifest left unchanged")
        now, now_bytes = read_asset_json(repo, rel, P.MANIFEST_NAME, td)
        if now_bytes != cur_bytes:
            raise SystemExit("the manifest changed while this run was uploading (another writer); rerun to merge again")
        if now_bytes != mbytes:
            _replace(repo, rel, got, P.MANIFEST_NAME, mbytes, td)
        if cur_rec_bytes != rbytes:
            _replace(repo, rel, got, RECORDS_NAME, rbytes, td)
        expected = {e["asset_name"]: (e["size_bytes"], e["sha256"]) for e in new_entries}
        expected[P.MANIFEST_NAME] = (len(mbytes), hashlib.sha256(mbytes).hexdigest())
        expected[RECORDS_NAME] = (len(rbytes), hashlib.sha256(rbytes).hexdigest())
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
    ap.add_argument("--config", default=os.path.join(HERE, "SOURCES.json"))
    ap.add_argument("--pkg", action="append", default=[])
    ap.add_argument("--init", action="store_true", help="only create (or verify) the empty 009 draft")
    ap.add_argument("--report")
    a = ap.parse_args()
    cfg = json.load(open(a.config, encoding="utf-8"))
    if a.init:
        rel, created = ensure_draft(a.repo, cfg)
        print(json.dumps({"tag": rel["tag_name"], "draft": rel["draft"], "id": rel["id"], "url": rel["html_url"],
                          "created": created}, ensure_ascii=False))
        return
    if not a.pkg:
        raise SystemExit("nothing to add: give --pkg (or --init)")
    append(a.repo, cfg, a.pkg, report_path=a.report)


if __name__ == "__main__":
    main()
