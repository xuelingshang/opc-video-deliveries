#!/usr/bin/env python3
"""AUTO-BATCH-009 delivery driver of the OWNER-CONTROLLED workflow in xuelingshang/opc-video-deliveries
(.github/workflows/delivery-009-draft.yml, default branch only). Same trust model as delivery-008/run_008.py:
the production repository is only read, as data; nothing from it is executed; the stations hold no token that can
write here. Unlike 008 there are no request files: the stations already committed each video's ZIP as byte parts
plus a manifest, so the videos are found directly in each station's own branch (SOURCES.json).

  state    GH_TOKEN = this repository's GITHUB_TOKEN. Reads the 009 draft and what its manifest records.
           -> WORK/state.json
  fetch    read-only token for the 009 repository, handed to git through GIT_CONFIG_* (never written to disk).
           For each station branch in SOURCES.json and each 009-NNN directory in the station's number ranges (and in
           only_ids): picks the first existing manifest of SOURCES.json "manifests", and copies out the manifest, the
           parts it lists and the station's STATUS / restore records - only for videos not delivered yet, blob by blob
           (regular files only, paths from validated parts; nothing is checked out, nothing is run).
           -> WORK/plan.json, WORK/data/<id>/...
  rebuild  no credentials. restore_009.restore(): join, verify every SHA256, check the ZIP layout, the 1080p MP4,
           and re-store the four files as 009-NNN-DELIVERY.zip. Each video's parts are deleted once it is packed.
           -> WORK/plan-built.json, WORK/build/pkg/<id>/
  deliver  GH_TOKEN = GITHUB_TOKEN (gh + the lock push). lock -> append the videos ONE BY ONE (each one is on the
           draft and verified before the next starts; same name + SHA256 skipped, different SHA256 refused) -> unlock.

    python3 run_009.py state   --repo xuelingshang/opc-video-deliveries --work WORK
    python3 run_009.py fetch   --config SOURCES.json --work WORK [--source GIT_URL] [--ids 009-043,009-049]
    python3 run_009.py rebuild --work WORK
    python3 run_009.py deliver --repo xuelingshang/opc-video-deliveries --config SOURCES.json --work WORK
                               --lock-dir CHECKOUT [--dry-run]

opc-video-deliveries is public, so is this log: it names video ids, manifest paths, sizes, SHA256s and refusal
reasons only - never titles, copy text or anything read from the media.
Exit status 1 when any video was refused or failed (the run shows red); every other video is still delivered.
"""
import argparse, json, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lock009  # noqa: E402
import opc_daily_009 as D  # noqa: E402
import restore_009 as R  # noqa: E402

FILE_MODES = ("100644", "100755")
MAX_JSON = 1 << 20
MAX_PART = 2 * 1024 ** 3
STATUS_FILES = ("STATUS.json",)
RESTORE_RECORDS = ("RESTORE_VERIFICATION.json", "RESTORE-TEST.json")
# what delivery-009-records.json copies from the station's STATUS.json (round STATUS-R<k>.json overrides), as recorded
STATUS_KEYS = ("status", "state", "delivery_status", "fact_gate", "gates", "media_gate", "rights_status", "rights",
               "public_release_authorized", "visual_review", "founder_review", "use", "usage", "distribution")


class Reject(Exception):
    pass


def log(msg):
    print(msg, flush=True)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def git(args, cwd=None, out=None):
    p = subprocess.run(["git", *args], cwd=cwd, stdout=out or subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise RuntimeError(f"git {args[0]} failed: {p.stderr.decode(errors='replace').strip()[-400:]}")
    return p.stdout


def load_cfg(path):
    cfg = load_json(path)
    D.release_cfg(cfg)
    st = cfg.get("stations")
    if not isinstance(st, dict) or not st:
        raise SystemExit(f"{path}: no stations")
    for k, v in st.items():
        if not re.fullmatch(r"[A-Za-z0-9]{1,16}", k) or not re.fullmatch(r"claude/009-[A-Za-z0-9._-]+", v.get("branch", "")):
            raise SystemExit(f"{path}: bad station {k}")
        if not (isinstance(v.get("ids"), list) and all(isinstance(r, list) and len(r) == 2 and all(type(x) is int for x in r)
                                                         and 0 <= r[0] <= r[1] <= 999 for r in v["ids"])):
            raise SystemExit(f"{path}: bad ids for station {k}")
    only = cfg.get("only_ids")
    if only is not None and not (isinstance(only, list) and all(isinstance(x, str) and R.ID_RE.fullmatch(x) for x in only)):
        raise SystemExit(f"{path}: bad only_ids")
    R.check_rel(cfg["video_root"])
    for m in cfg["manifests"]:
        R.check_rel(m.replace("{id}", "009-000"))
    return cfg


def owner_of(cfg, n):
    own = [k for k, v in cfg["stations"].items() if any(lo <= n <= hi for lo, hi in v["ids"])]
    return own[0] if len(own) == 1 else None


# ---------------------------------------------------------------- git blob access (no checkout, no symlinks)

def tree_entries(bare, commit, path):
    out = []
    for e in git(["ls-tree", "-z", commit, "--", path], cwd=bare).split(b"\0"):
        if e:
            meta, p = e.split(b"\t", 1)
            mode, typ, obj = meta.decode().split()
            out.append((mode, typ, obj, p.decode("utf-8", "replace")))
    return out


def blob_at(bare, commit, path):
    ents = [e for e in tree_entries(bare, commit, path) if e[3] == path]
    if len(ents) != 1:
        return None
    mode, typ, obj, _ = ents[0]
    if typ != "blob" or mode not in FILE_MODES:
        raise Reject(f"not a regular file in git (mode {mode}): {path}")
    return obj


def read_blob(bare, commit, path, limit, dest=None):
    obj = blob_at(bare, commit, path)
    if obj is None:
        raise Reject(f"missing {path}")
    size = int(git(["cat-file", "-s", obj], cwd=bare))
    if size > limit:
        raise Reject(f"{path}: {size} bytes > {limit}")
    if dest is None:
        return git(["cat-file", "blob", obj], cwd=bare)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        git(["cat-file", "blob", obj], cwd=bare, out=f)
    if os.path.getsize(dest) != size:
        raise Reject(f"{path}: short read")
    return None


# ---------------------------------------------------------------- station records (copied as recorded, never judged here)

def restore_record(m, mdir_files):
    """The station's own record that its restore was tested: (where, passed) or None."""
    v = m.get("verification") if isinstance(m, dict) else None
    if isinstance(v, dict):
        ok = v.get("pass", v.get("matches_original"))
        return "manifest.verification", ok is True
    for name, js in mdir_files.items():
        if isinstance(js, dict):
            ok = js.get("PASS", js.get("restored_zip_sha256_equals_original",
                                       js.get("restored_zip_sha256") == js.get("original_zip_sha256") or None))
            return name, ok is True
    return None


def status_subset(js):
    return {k: js[k] for k in STATUS_KEYS if isinstance(js, dict) and k in js}


# ---------------------------------------------------------------- steps

def cmd_state(a):
    cfg = load_cfg(a.config)
    tag = D.release_cfg(cfg)[0]
    out = {}
    rel = D.find_release(a.repo, tag)
    if rel:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            man, _ = D.read_asset_json(a.repo, rel, D.P.MANIFEST_NAME, td)
            recs, _ = D.read_asset_json(a.repo, rel, D.RECORDS_NAME, td)
        recs = (recs or {}).get("videos", {})
        vids = {e["video_id"]: [e["asset_name"], e["size_bytes"], e["sha256"],
                                (recs.get(e["video_id"]) or {}).get("source_zip_sha256")]
                for e in (man or {}).get("videos", [])}
        out = {"tag": tag, "exists": True, "draft": rel["draft"], "videos": vids}
        log(f"state: {tag} draft={rel['draft']} recorded={len(vids)}")
    else:
        out = {"tag": tag, "exists": False, "draft": True, "videos": {}}
        log(f"state: {tag} not created yet")
    save_json(out, os.path.join(a.work, "state.json"))


def cmd_fetch(a):
    cfg = load_cfg(a.config)
    state = load_json(os.path.join(a.work, "state.json"))
    only = set(cfg["only_ids"]) if cfg.get("only_ids") is not None else None
    if a.ids:
        want = {x.strip() for x in a.ids.split(",") if x.strip()}
        bad = sorted(x for x in want if not R.ID_RE.fullmatch(x) or (only is not None and x not in only))
        if bad:
            raise SystemExit(f"--ids outside SOURCES.json only_ids: {bad}")
        only = want
    url = a.source or f"https://github.com/{cfg['source_repo']}.git"
    bare = os.path.join(a.work, "src.git")
    for d in (bare, os.path.join(a.work, "data")):
        shutil.rmtree(d, ignore_errors=True)
    git(["clone", "-q", "--bare", "--filter=blob:none", "--depth=1", "--no-single-branch", "--no-tags", url, bare])
    heads = dict(tuple(line.split(" ", 1)[::-1]) for line in git(
        ["for-each-ref", "--format=%(objectname) %(refname:strip=2)", "refs/heads/"], cwd=bare).decode().splitlines())
    videos, refused = [], []
    found = set()
    root = cfg["video_root"]
    for station, sc in sorted(cfg["stations"].items()):
        sha = heads.get(sc["branch"])
        if not sha:
            log(f"station {station}: branch not found")
            for vid in sorted(x for x in (only or ()) if owner_of(cfg, int(x[4:])) == station):
                refused.append({"video_id": vid, "reason": f"station {station} branch not found"})
                found.add(vid)
            continue
        dirs = [e[3].rsplit("/", 1)[-1] for e in tree_entries(bare, sha, root + "/") if e[1] == "tree"]
        for vid in sorted(d for d in dirs if R.ID_RE.fullmatch(d)):
            if owner_of(cfg, int(vid[4:])) != station or (only is not None and vid not in only):
                continue
            found.add(vid)
            vdir = f"{root}/{vid}"
            row = {"video_id": vid, "station": station, "commit": sha}
            try:
                mrel = next((f"{vdir}/{m.replace('{id}', vid)}" for m in cfg["manifests"]
                             if blob_at(bare, sha, f"{vdir}/{m.replace('{id}', vid)}")), None)
                if not mrel:
                    raise Reject("no delivery manifest (no restorable ZIP parts recorded)")
                mdir = mrel.rsplit("/", 1)[0]
                data = os.path.join(a.work, "data", vid)
                dst = lambda rel: os.path.join(data, *rel.split("/"))  # noqa: E731
                read_blob(bare, sha, mrel, MAX_JSON, dst(mrel))
                m = load_json(dst(mrel))
                n = R.normalize(m, vid)
                if vid in state["videos"]:
                    old = state["videos"][vid]
                    if old[3] and old[3] != n["zip_sha256"]:
                        raise Reject(f"CONFLICT: {state['tag']} already holds {old[0]} {old[2]} restored from station ZIP "
                                     f"{old[3]}; the branch now records {n['zip_sha256']} ({mrel}); nothing overwritten")
                    row["already"] = old
                    videos.append(row)
                    shutil.rmtree(data, ignore_errors=True)
                    continue
                for p in n["parts"]:
                    read_blob(bare, sha, f"{mdir}/{p['name']}", MAX_PART, dst(f"{mdir}/{p['name']}"))
                recs = {}
                for name in RESTORE_RECORDS:
                    if blob_at(bare, sha, f"{mdir}/{name}"):
                        recs[name] = json.loads(read_blob(bare, sha, f"{mdir}/{name}", MAX_JSON))
                status, verified = {}, None
                rd = mdir.rsplit("/", 1)[0] if mdir.count("/") > vdir.count("/") + 1 else None   # .../R2/DELIVERY -> .../R2
                for rel in [f"{vdir}/{s}" for s in STATUS_FILES] + ([f"{rd}/STATUS-{rd.rsplit('/', 1)[-1]}.json"] if rd else []):
                    if blob_at(bare, sha, rel):
                        try:
                            js = json.loads(read_blob(bare, sha, rel, MAX_JSON))
                        except ValueError:
                            continue
                        status.update(status_subset(js))
                        if not isinstance(js, dict):
                            continue
                        out = js.get("outputs")                         # Cloud3: delivery_status + outputs.delivery_zip_sha256
                        if isinstance(out, dict) and out.get("delivery_zip_sha256") == n["zip_sha256"] and \
                                "RESTORE_VERIFIED" in str(js.get("delivery_status", "")):
                            verified = (f"{rel.rsplit('/', 1)[-1]} delivery_status", True)
                        dl = js.get("delivery")
                        if not (isinstance(dl, dict) and "restore_verified" in dl):
                            continue
                        zsha = dl.get("zip_sha256") or (dl["zip"].get("sha256") if isinstance(dl.get("zip"), dict) else None)
                        if zsha == n["zip_sha256"]:                 # the record is about this very ZIP
                            verified = (f"{rel.rsplit('/', 1)[-1]} delivery.restore_verified", dl["restore_verified"] is True)
                rr = restore_record(m, recs) or verified
                row.update(manifest=mrel, root=data, parts=len(n["parts"]), source_zip_sha256=n["zip_sha256"],
                           station_restore_record=rr and {"where": rr[0], "pass": rr[1]}, station_status=status)
                if rr and not rr[1]:
                    raise Reject(f"the station's own restore record ({rr[0]}) does not say PASS")
                videos.append(row)
            except (SystemExit, Exception) as e:       # one bad video never stops the others
                shutil.rmtree(os.path.join(a.work, "data", vid), ignore_errors=True)
                refused.append({"video_id": vid, "reason": f"{type(e).__name__}: {e}" if not isinstance(e, (Reject, SystemExit)) else str(e)})
    for vid in sorted((only or set()) - found):
        refused.append({"video_id": vid, "reason": "no directory for it on its station's branch"})
    shutil.rmtree(bare, ignore_errors=True)            # the copied blobs are all that later steps need
    for v in videos:
        if "already" in v:
            log(f"{v['video_id']}: already on the draft ({v['already'][2][:12]}), skipped")
        else:
            rr = v["station_restore_record"]
            log(f"{v['video_id']}: station {v['station']} {v['commit'][:7]} {v['manifest']} {v['parts']} parts "
                f"zip {v['source_zip_sha256'][:12]} station restore record: {rr['where'] if rr else 'none'}")
    for x in refused:
        log(f"REFUSED {x['video_id']}: {x['reason']}")
    save_json({"videos": videos, "refused": refused}, os.path.join(a.work, "plan.json"))


def cmd_rebuild(a):
    plan = load_json(os.path.join(a.work, "plan.json"))
    out = os.path.join(a.work, "build")
    keep = []
    for v in plan["videos"]:
        if "already" in v:
            keep.append(v)
            continue
        try:
            rec = R.restore(v["video_id"], v["root"], v["manifest"], out, log=log)
            if rec["source_zip_sha256"] != v["source_zip_sha256"]:
                raise SystemExit("manifest changed between fetch and rebuild")
            v.update(pkg=os.path.join(out, "pkg", v["video_id"]), restored=rec)
            keep.append(v)
        except (SystemExit, Exception) as e:
            plan["refused"].append({"video_id": v["video_id"], "reason": f"rebuild: {e}"})
            log(f"REFUSED {v['video_id']}: rebuild: {e}")
        finally:
            shutil.rmtree(v["root"], ignore_errors=True)
    mp4s = {}
    for v in keep:
        if "restored" in v:
            mp4s.setdefault(v["restored"]["mp4_sha256"], []).append(v["video_id"])
    dup = {vid for ids in mp4s.values() if len(ids) > 1 for vid in ids}
    for vid in sorted(dup):
        plan["refused"].append({"video_id": vid, "reason": "the same MP4 SHA256 is recorded for another video; nothing delivered"})
        log(f"REFUSED {vid}: same MP4 SHA256 as another video")
    plan["videos"] = [v for v in keep if v["video_id"] not in dup]
    save_json(plan, os.path.join(a.work, "plan-built.json"))


def record_of(v, cfg):
    r = v["restored"]
    return {"station": v["station"], "branch": cfg["stations"][v["station"]]["branch"], "commit": v["commit"],
            "manifest": v["manifest"], "source_zip": r["source_zip"], "source_zip_bytes": r["source_zip_bytes"],
            "source_zip_sha256": r["source_zip_sha256"], "source_zip_root": r["source_zip_root"], "parts": r["parts"],
            "mp4_bytes": r["mp4_bytes"], "mp4_sha256": r["mp4_sha256"], "asset_name": r["asset_name"],
            "zip_bytes": r["zip_bytes"], "zip_sha256": r["zip_sha256"],
            "station_restore_record": v["station_restore_record"], "station_status": v["station_status"],
            "delivery_restore_check": "PASS (all part / ZIP / member SHA256, ZIP CRC, layout, 1920x1080 MP4)",
            "public_release_authorized": False}


def cmd_deliver(a):
    cfg = load_cfg(a.config)
    plan = load_json(os.path.join(a.work, "plan-built.json"))
    problems = list(plan["refused"])
    todo = [v for v in plan["videos"] if "pkg" in v]
    log(f"deliver: {len(todo)} video(s) to append, {len(plan['videos']) - len(todo)} already on the draft, "
        f"{len(problems)} refused")
    results = []
    if a.dry_run:
        for v in todo:
            r = v["restored"]
            log(f"DRY RUN {v['video_id']} -> {D.release_cfg(cfg)[0]}: {r['asset_name']} {r['zip_bytes']} {r['zip_sha256']}")
    elif todo:
        run = os.environ.get("GITHUB_RUN_ID", "local")
        with lock009.Lock(a.lock_dir, f"actions-{run}", wait_s=a.wait_s, note="delivery-009", branch=a.lock_branch):
            for v in todo:                       # one by one: each video is on the draft before the next starts
                try:
                    rep = D.append(a.repo, cfg, [v["pkg"]], records={v["video_id"]: record_of(v, cfg)},
                                   report_path=os.path.join(a.work, "records", f"{v['video_id']}.json"))
                    z = rep["assets"][v["restored"]["asset_name"]]
                    res = {"video_id": v["video_id"], "release_tag": rep["release_tag"], "draft": rep["draft"],
                           "uploaded": v["video_id"] in rep["uploaded"], "size": z["size"], "digest": z["digest"],
                           "videos_on_release": rep["videos"]}
                    results.append(res)
                    log("DELIVERED " + json.dumps(res, ensure_ascii=False))
                    shutil.rmtree(v["pkg"], ignore_errors=True)
                except (SystemExit, Exception) as e:
                    problems.append({"video_id": v["video_id"], "reason": f"append: {e}"})
                    log(f"FAILED {v['video_id']}: {e}")
    save_json({"results": results, "problems": problems}, os.path.join(a.work, "deliver-report.json"))
    for p in problems:
        log("PROBLEM " + json.dumps(p, ensure_ascii=False))
    log(f"summary: {len(results)} video(s) delivered or verified, {len(problems)} problem(s)")
    sys.exit(1 if problems else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("state"); p.add_argument("--repo", required=True); p.add_argument("--work", required=True)
    p.add_argument("--config", default=os.path.join(HERE, "SOURCES.json"))
    p = sub.add_parser("fetch"); p.add_argument("--config", default=os.path.join(HERE, "SOURCES.json"))
    p.add_argument("--work", required=True)
    p.add_argument("--source", help="git URL of the 009 repository (default https://github.com/<source_repo>.git)")
    p.add_argument("--ids", default="", help="comma list: only these (must be inside only_ids)")
    p = sub.add_parser("rebuild"); p.add_argument("--work", required=True)
    p = sub.add_parser("deliver"); p.add_argument("--repo", required=True); p.add_argument("--work", required=True)
    p.add_argument("--config", default=os.path.join(HERE, "SOURCES.json"))
    p.add_argument("--lock-dir", required=True, help="checkout of the repository that holds the lock branch")
    p.add_argument("--lock-branch", default=lock009.BRANCH)
    p.add_argument("--wait-s", type=int, default=3600)
    p.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    {"state": cmd_state, "fetch": cmd_fetch, "rebuild": cmd_rebuild, "deliver": cmd_deliver}[a.cmd](a)


if __name__ == "__main__":
    main()
