#!/usr/bin/env python3
"""Publish one OPC R2 delivery batch as a GitHub Release.

R2 format (fixed by the existing friend-side R2 tool):
  * release tag      delivery-YYYY-MM-DD-NN  (NN = batch number on that date, 01, 02, ...)
  * release assets   VIDEO-ID-DELIVERY.zip (one per video) + delivery-manifest.json
  * manifest         schema_version=1, repository, delivery_date, release_tag, videos[]
  * videos[] entry   video_id, asset_name, size_bytes, sha256, files

Safety rules:
  * The release is created as a DRAFT; all ZIPs are uploaded first, the manifest last;
    every asset's size and SHA256 digest is checked before the draft is published.
  * A published tag is never modified or overwritten. Re-running with the same packages
    resumes an unfinished draft of ours instead of starting over.
  * Formal batches need --confirm-public-gate (rights + Founder viewing approved);
    test batches may only contain TEST-* video ids.

Uses the `gh` CLI (GH_TOKEN / GITHUB_TOKEN must allow contents:write on the repo).

    python3 opc_publish.py --repo OWNER/REPO --date 2026-10-13 --pkg out/TEST-0001 --test
    python3 opc_publish.py ... --dry-run          # plan only, no API writes
"""
import argparse, datetime, hashlib, json, os, re, subprocess, sys, tempfile, time, urllib.request

TAG_RE = re.compile(r"^delivery-(\d{4}-\d{2}-\d{2})-(\d{2})$")
MANIFEST_NAME = "delivery-manifest.json"


def log(*a):
    print(*a, flush=True)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def gh(args, input_path=None, headers=(), method=None, allow_fail=False):
    cmd = ["gh", "api"]
    if method:
        cmd += ["--method", method]
    for h in headers:
        cmd += ["-H", h]
    if input_path:
        cmd += ["--input", input_path]
    cmd += args
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        if allow_fail:
            return None
        raise SystemExit(f"gh api failed ({' '.join(args[:1])}): {p.stderr.strip() or p.stdout.strip()}")
    return json.loads(p.stdout) if p.stdout.strip() else {}


def list_releases(repo):
    out, page = [], 1
    while True:
        batch = gh([f"repos/{repo}/releases?per_page=100&page={page}"])
        out += batch
        if len(batch) < 100:
            return out
        page += 1


def load_packages(pkg_dirs, test):
    videos = []
    for d in pkg_dirs:
        e = json.load(open(os.path.join(d, "video-entry.json"), encoding="utf-8"))
        vid = e["video_id"]
        if e["asset_name"] != f"{vid}-DELIVERY.zip":
            raise SystemExit(f"{vid}: asset_name must be {vid}-DELIVERY.zip")
        zp = os.path.join(d, e["asset_name"])
        if os.path.getsize(zp) != e["size_bytes"] or sha256_file(zp) != e["sha256"]:
            raise SystemExit(f"{vid}: ZIP on disk does not match video-entry.json")
        want = [f"{vid}/{vid}.mp4", f"{vid}/cover.jpg", f"{vid}/weibo.txt", f"{vid}/subtitle.srt"]
        if [f["path"] for f in e["files"]] != want:
            raise SystemExit(f"{vid}: files must be exactly {want}")
        if test != vid.startswith("TEST-"):
            raise SystemExit(f"{vid}: test batches hold only TEST-* ids, formal batches none")
        videos.append((e, zp))
    ids = [e["video_id"] for e, _ in videos]
    if len(set(ids)) != len(ids):
        raise SystemExit("duplicate video ids in one batch")
    return videos


def already_published_ids(releases):
    """video ids already present in any published delivery release (by asset name)."""
    seen = {}
    for r in releases:
        if r.get("draft") or not TAG_RE.match(r["tag_name"]):
            continue
        for a in r.get("assets", []):
            if a["name"].endswith("-DELIVERY.zip"):
                seen[a["name"][: -len("-DELIVERY.zip")]] = r["tag_name"]
    return seen


def pick_tag(releases, date, nn, asset_names):
    same_day = {}
    for r in releases:
        m = TAG_RE.match(r["tag_name"])
        if m and m.group(1) == date:
            same_day[int(m.group(2))] = r
    if nn:
        r = same_day.get(int(nn))
        if r and not r["draft"]:
            raise SystemExit(f"delivery-{date}-{int(nn):02d} is already published; it is never overwritten")
        return f"delivery-{date}-{int(nn):02d}", r
    for n, r in sorted(same_day.items()):
        if r["draft"] and {a["name"] for a in r.get("assets", [])} <= asset_names | {MANIFEST_NAME}:
            return r["tag_name"], r            # resume our own unfinished draft
    n = max(same_day, default=0) + 1
    if n > 99:
        raise SystemExit("no free batch number left for this date")
    return f"delivery-{date}-{n:02d}", None


def build_manifest(repo, date, tag, videos, test):
    m = dict(schema_version=1, repository=repo, delivery_date=date, release_tag=tag,
             videos=[e for e, _ in videos])
    m["generated_at_utc"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if test:
        m["test_only"] = True
    return m


def asset_ok(repo, a, size, sha):
    """True if the release asset is complete and byte-identical (API digest, else download+hash)."""
    if a.get("state") != "uploaded" or a.get("size") != size:
        return False
    digest = a.get("digest")
    if digest:
        return digest == f"sha256:{sha}"
    with tempfile.NamedTemporaryFile() as tmp:
        subprocess.run(["gh", "api", "-H", "Accept: application/octet-stream",
                        f"repos/{repo}/releases/assets/{a['id']}"], stdout=tmp, check=True)
        return os.path.getsize(tmp.name) == size and sha256_file(tmp.name) == sha


def upload(repo, rel, name, path, size, sha, content_type):
    for a in rel.get("assets", []):
        if a["name"] == name:
            if asset_ok(repo, a, size, sha):
                log(f"  {name}: already uploaded and verified, skip")
                return
            log(f"  {name}: incomplete or different copy on our draft, replacing")
            gh([f"repos/{repo}/releases/assets/{a['id']}"], method="DELETE")
    log(f"  uploading {name} ({size} bytes)")
    upload_url = f"https://uploads.github.com/repos/{repo}/releases/{rel['id']}/assets?name={name}"
    for attempt in range(1, 4):
        r = gh([upload_url], input_path=path, headers=[f"Content-Type: {content_type}"], method="POST", allow_fail=True)
        if r is not None:
            return
        log(f"  upload attempt {attempt} failed, retrying")
        time.sleep(5 * attempt)
        fresh = gh([f"repos/{repo}/releases/{rel['id']}"])
        for a in fresh.get("assets", []):
            if a["name"] == name:
                gh([f"repos/{repo}/releases/assets/{a['id']}"], method="DELETE")
    raise SystemExit(f"upload of {name} failed 3 times; draft kept, re-run to resume")


def verify_assets(repo, rel_id, expected):
    rel = gh([f"repos/{repo}/releases/{rel_id}"])
    got = {a["name"]: a for a in rel.get("assets", [])}
    extra = set(got) - set(expected)
    if extra:
        raise SystemExit(f"unexpected assets on draft: {sorted(extra)}")
    for name, (size, sha) in expected.items():
        a = got.get(name)
        if not a:
            raise SystemExit(f"asset missing after upload: {name}")
        if not asset_ok(repo, a, size, sha):
            raise SystemExit(f"asset verification failed: {name}")
        log(f"  verified {name}")
    return rel


def anonymous_check(repo, tag, manifest_bytes, videos, full, web_base="https://github.com"):
    """Download through the public URLs without any credentials."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler() if web_base.startswith("https://")
                                         else urllib.request.ProxyHandler({}))
    opener.addheaders = [("User-Agent", "opc-publish-anon-check")]
    base = f"{web_base}/{repo}/releases/download/{tag}"
    with opener.open(f"{base}/{MANIFEST_NAME}", timeout=60) as r:
        if r.read() != manifest_bytes:
            raise SystemExit("anonymous manifest download differs from the uploaded manifest")
    log("  anonymous download of delivery-manifest.json: identical")
    for e, _ in videos:
        req = urllib.request.Request(f"{base}/{e['asset_name']}")
        if not full:
            req.add_header("Range", "bytes=0-1048575")
        h, n = hashlib.sha256(), 0
        with opener.open(req, timeout=120) as r:
            for b in iter(lambda: r.read(1 << 20), b""):
                h.update(b); n += len(b)
        if full and (n != e["size_bytes"] or h.hexdigest() != e["sha256"]):
            raise SystemExit(f"anonymous download of {e['asset_name']} failed verification")
        log(f"  anonymous download of {e['asset_name']}: {'full SHA256 match' if full else 'first MiB OK'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--date", required=True, help="planned delivery date YYYY-MM-DD")
    ap.add_argument("--nn", help="batch number; default: resume our draft or take the next free one")
    ap.add_argument("--pkg", action="append", required=True, help="package dir with video-entry.json + ZIP")
    ap.add_argument("--test", action="store_true", help="test batch (TEST-* ids only)")
    ap.add_argument("--confirm-public-gate", action="store_true",
                    help="required for formal batches: public redistribution licence and Founder viewing approved")
    ap.add_argument("--target", default="main", help="commit/branch the tag is created on")
    ap.add_argument("--full-anon-verify", action="store_true", help="download every ZIP anonymously and hash it")
    ap.add_argument("--manifest-out", help="also write the manifest here")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--web-base", default="https://github.com", help=argparse.SUPPRESS)  # tests only
    a = ap.parse_args()

    datetime.date.fromisoformat(a.date)
    if not a.test and not a.confirm_public_gate:
        raise SystemExit("formal batch refused: pass --confirm-public-gate only after rights and Founder viewing are approved")
    videos = load_packages(a.pkg, a.test)
    releases = list_releases(a.repo)
    dup = {e["video_id"]: t for e, _ in videos for v, t in already_published_ids(releases).items() if v == e["video_id"]}
    if dup:
        raise SystemExit(f"already published, not uploading twice: {dup}")
    names = {e["asset_name"] for e, _ in videos}
    tag, rel = pick_tag(releases, a.date, a.nn, names)
    manifest = build_manifest(a.repo, a.date, tag, videos, a.test)
    mbytes = (json.dumps(manifest, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    if a.manifest_out:
        open(a.manifest_out, "wb").write(mbytes)
    log(f"batch {tag}: {len(videos)} video(s){' [TEST]' if a.test else ''}; {'resuming draft ' + str(rel['id']) if rel else 'new draft'}")
    if a.dry_run:
        log(mbytes.decode())
        return

    title = (f"[TEST] OPC 交付链路测试 {a.date} 第{tag[-2:]}批（非正式视频）" if a.test
             else f"OPC 交付 {a.date} 第{tag[-2:]}批")
    body = ("测试批次：画面为程序生成的测试图案，非正式视频，请勿发布。\n\n" if a.test else "") + \
        "\n".join(f"- {e['video_id']} · {e['asset_name']} · {e['size_bytes']} bytes · SHA256 `{e['sha256']}`" for e, _ in videos) + \
        f"\n\n清单：{MANIFEST_NAME}（schema_version 1）。朋友端用 R2 下载工具自动获取，无需登录。"
    if not rel:
        rel = gh([f"repos/{a.repo}/releases", "-f", f"tag_name={tag}", "-f", f"target_commitish={a.target}",
                  "-f", f"name={title}", "-f", f"body={body}", "-F", "draft=true", "-F", "prerelease=false"],
                 method="POST")
        log(f"  draft release created: id {rel['id']}")
    for e, zp in videos:
        upload(a.repo, rel, e["asset_name"], zp, e["size_bytes"], e["sha256"], "application/zip")
    with tempfile.TemporaryDirectory() as td:
        mp = os.path.join(td, MANIFEST_NAME)
        open(mp, "wb").write(mbytes)
        rel = gh([f"repos/{a.repo}/releases/{rel['id']}"])
        upload(a.repo, rel, MANIFEST_NAME, mp, len(mbytes), hashlib.sha256(mbytes).hexdigest(), "application/json")
    expected = {e["asset_name"]: (e["size_bytes"], e["sha256"]) for e, _ in videos}
    expected[MANIFEST_NAME] = (len(mbytes), hashlib.sha256(mbytes).hexdigest())
    verify_assets(a.repo, rel["id"], expected)
    rel = gh([f"repos/{a.repo}/releases/{rel['id']}", "-F", "draft=false", "-f",
              f"make_latest={'false' if a.test else 'true'}"], method="PATCH")
    log(f"  published: {rel['html_url']}")
    anonymous_check(a.repo, tag, mbytes, videos, a.full_anon_verify, a.web_base)
    log(json.dumps(dict(release_tag=tag, url=rel["html_url"], videos=[e["video_id"] for e, _ in videos]), ensure_ascii=False))


if __name__ == "__main__":
    main()
