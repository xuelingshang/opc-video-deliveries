#!/usr/bin/env python3
"""AUTO-BATCH-008 delivery driver of the OWNER-CONTROLLED workflow in xuelingshang/opc-video-deliveries
(.github/workflows/delivery-008-draft.yml, default branch only). Production branches only commit requests and
byte parts to the 008 repository; they never hold a token that can write to opc-video-deliveries, and nothing
from the 008 repository is executed here.

Each step runs with only the credential it needs (the workflow passes it per step):

  state    GH_TOKEN = this repository's GITHUB_TOKEN. Reads the 008 releases and what their manifests record.
           -> WORK/state.json
  fetch    read-only token for the 008 repository, handed to git through GIT_CONFIG_* (never written to disk).
           Lists the stations' branches (STATIONS.json), reads each station's own request files, validates them,
           and copies out the files of the videos that are not delivered yet, blob by blob from git (regular-file
           blobs only, paths built from validated parts; nothing is checked out, nothing is run).
           -> WORK/plan.json, WORK/data/<n>/...
  rebuild  no credentials. Joins the parts, checks every SHA256, packs with the vendored opc_pack.py and requires
           the ZIP to equal the request.  -> WORK/plan-built.json, WORK/build/<n>/pkg/<id>/
  deliver  GH_TOKEN = GITHUB_TOKEN (gh + the lock push). lock -> per request: create/verify the 008 draft and
           append (same name + SHA256 skipped, different SHA256 refused, nothing overwritten) -> unlock.

    python3 run_008.py state   --repo xuelingshang/opc-video-deliveries --work WORK
    python3 run_008.py fetch   --config STATIONS.json --work WORK [--source GIT_URL]
    python3 run_008.py rebuild --work WORK
    python3 run_008.py deliver --repo xuelingshang/opc-video-deliveries --work WORK --lock-dir CHECKOUT [--dry-run]

opc-video-deliveries is public, so is this log: it names request files (date + station), commits, video ids, sizes,
SHA256s and refusal reasons (which may quote a path the request gave, e.g. OUTPUT/M350/008-066) - never titles,
copy text, branch names or anything read from the media.
Exit status 1 when anything was refused or failed (the run shows red); everything else is still delivered.
"""
import argparse, datetime, json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lock008  # noqa: E402
import opc_daily_008 as D  # noqa: E402
import rebuild_from_parts as RB  # noqa: E402

REQ_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-([A-Za-z0-9]{1,16})\.json$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
FILE_MODES = ("100644", "100755")
MAX_JSON = 1 << 20
MAX_COVER = 64 << 20
MAX_PART = 2 * 1024 ** 3
MAX_VIDEOS = 200
SIDECARS = (("STATUS.json", MAX_JSON), ("cover.jpg", MAX_COVER), ("weibo.txt", MAX_JSON), ("subtitle.srt", MAX_JSON))
ROW_KEYS = ("video_id", "dir", "mp4_bytes", "mp4_sha256", "zip_asset", "zip_bytes", "zip_sha256")


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


# ---------------------------------------------------------------- configuration and request validation

def load_cfg(path):
    cfg = load_json(path)
    st = cfg.get("stations")
    if not isinstance(st, dict) or not st:
        raise SystemExit(f"{path}: no stations")
    for k, v in st.items():
        if not re.fullmatch(r"[A-Za-z0-9]{1,16}", k):
            raise SystemExit(f"{path}: bad station key {k!r}")
        re.compile(v["branch_re"])
        ids = v.get("ids")
        if ids is not None and not (isinstance(ids, list) and all(
                isinstance(r, list) and len(r) == 2 and all(type(x) is int for x in r) and 0 <= r[0] <= r[1] <= 999
                for r in ids)):
            raise SystemExit(f"{path}: bad ids for station {k}")
    RB.check_rel(cfg["request_dir"])
    return cfg


def station_allows(cfg, station, n):
    ids = cfg["stations"][station].get("ids")
    if ids is not None:
        return any(lo <= n <= hi for lo, hi in ids)
    return not any(lo <= n <= hi for k, o in cfg["stations"].items() if k != station for lo, hi in (o.get("ids") or []))


def validate_request(name, raw, cfg):
    m = REQ_NAME_RE.fullmatch(name)
    if not m:
        raise Reject("file name must be YYYY-MM-DD-<station>.json")
    date, station = m.groups()
    try:
        ok = datetime.date.fromisoformat(date).isoformat() == date
    except ValueError:
        ok = False
    if not ok:
        raise Reject(f"bad date {date}")
    if station not in cfg["stations"]:
        raise Reject(f"station {station} is not in STATIONS.json")
    try:
        req = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise Reject("not UTF-8 JSON")
    if not isinstance(req, dict) or req.get("date") != date or str(req.get("station")) != station:
        raise Reject("date / station inside the file differ from its name")
    if D.tag_for(date) not in str(req.get("release", D.tag_for(date))):
        raise Reject(f"release must name {D.tag_for(date)} (the release is chosen by the date, never by this field)")
    vids = req.get("videos")
    if not isinstance(vids, list) or len(vids) > MAX_VIDEOS:
        raise Reject(f"videos must be a list of at most {MAX_VIDEOS}")
    rows, seen = [], set()
    for v in vids:
        if not isinstance(v, dict):
            raise Reject("video rows must be objects")
        try:
            vid, _ = RB.video_dir(v)
        except SystemExit as e:
            raise Reject(str(e))
        if vid in seen:
            raise Reject(f"{vid} listed twice")
        seen.add(vid)
        if not station_allows(cfg, station, int(vid[4:])):
            raise Reject(f"{vid} is not station {station}'s number (STATIONS.json)")
        if v.get("zip_asset") != f"{vid}-DELIVERY.zip":
            raise Reject(f"{vid}: zip_asset must be {vid}-DELIVERY.zip")
        for k in ("mp4_bytes", "zip_bytes"):
            if not (type(v.get(k)) is int and 0 < v[k] < MAX_PART):
                raise Reject(f"{vid}: bad {k}")
        for k in ("mp4_sha256", "zip_sha256"):
            if not (isinstance(v.get(k), str) and HEX64.fullmatch(v[k])):
                raise Reject(f"{vid}: bad {k}")
        rows.append({k: v[k] for k in ROW_KEYS})
    return date, station, rows


# ---------------------------------------------------------------- git blob access (no checkout, no symlinks)

def tree_entries(bare, commit, path):
    out = []
    for e in git(["ls-tree", "-z", commit, "--", path], cwd=bare).split(b"\0"):
        if e:
            meta, p = e.split(b"\t", 1)
            mode, typ, obj = meta.decode().split()
            out.append((mode, typ, obj, p.decode("utf-8", "replace")))
    return out


def read_blob(bare, commit, path, limit, dest=None):
    """Bytes (dest=None) or a file copy of the regular-file blob at `path`; trees are never followed through
    symlinks, so `path` resolves only through real directories of the commit."""
    ents = [e for e in tree_entries(bare, commit, path) if e[3] == path]
    if len(ents) != 1:
        raise Reject(f"missing {path}")
    mode, typ, obj, _ = ents[0]
    if typ != "blob" or mode not in FILE_MODES:
        raise Reject(f"not a regular file in git (mode {mode}): {path}")
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


# ---------------------------------------------------------------- steps

def cmd_state(a):
    out = {}
    for r in D.P.list_releases(a.repo):
        if not D.TAG_RE.match(r["tag_name"]):
            continue
        with tempfile.TemporaryDirectory() as td:
            man, _ = D.read_manifest(a.repo, r, td)
        vids = {e["video_id"]: [e["asset_name"], e["size_bytes"], e["sha256"]] for e in (man or {}).get("videos", [])}
        out[r["tag_name"]] = {"draft": r["draft"], "videos": vids}
        log(f"state: {r['tag_name']} draft={r['draft']} recorded={len(vids)}")
    if not out:
        log("state: no 008 release yet")
    save_json(out, os.path.join(a.work, "state.json"))


def cmd_fetch(a):
    cfg = load_cfg(a.config)
    state = load_json(os.path.join(a.work, "state.json"))
    url = a.source or f"https://github.com/{cfg['source_repo']}.git"
    bare = os.path.join(a.work, "src.git")
    for d in (bare, os.path.join(a.work, "data")):
        shutil.rmtree(d, ignore_errors=True)
    git(["clone", "-q", "--bare", "--filter=blob:none", "--depth=1", "--no-single-branch", "--no-tags", url, bare])
    heads = sorted(tuple(reversed(line.split(" ", 1))) for line in git(
        ["for-each-ref", "--format=%(objectname) %(refname:strip=2)", "refs/heads/"], cwd=bare).decode().splitlines())
    reqs, rejected, ignored = [], [], 0
    for br, sha in heads:
        own = [s for s, o in cfg["stations"].items() if re.fullmatch(o["branch_re"], br)]
        if not own:
            continue
        try:
            listing = tree_entries(bare, sha, cfg["request_dir"] + "/")
        except Exception as e:                      # one bad branch never stops the others
            rejected.append({"request": f"{cfg['request_dir']}@{sha[:7]}", "reason": str(e)})
            continue
        for _mode, _typ, _obj, path in listing:
            name = path.rsplit("/", 1)[-1]
            if not name.endswith(".json"):
                continue
            m = REQ_NAME_RE.fullmatch(name)
            if m and m.group(2) not in own:
                ignored += 1          # another station's request copied onto this branch: not this branch's to send
                continue
            where = f"{path}@{sha[:7]}"
            try:
                date, station, rows = validate_request(name, read_blob(bare, sha, path, MAX_JSON), cfg)
            except (SystemExit, Exception) as e:      # one bad request never stops the others
                rejected.append({"request": where, "reason": str(e)})
                log(f"REFUSED {where}: {e}")
                continue
            reqs.append({"request": where, "commit": sha, "date": date, "station": station, "rows": rows,
                         "todo": [], "delivered": [], "duplicates": [], "refused": []})

    # one decision per (date, video): identical rows are sent once, disagreeing rows are all refused
    groups = {}
    for ri, r in enumerate(reqs):
        for row in r["rows"]:
            groups.setdefault((r["date"], row["video_id"]), []).append((ri, row))
    zkey = lambda row: [row["zip_asset"], row["zip_bytes"], row["zip_sha256"]]  # noqa: E731
    for (date, vid), lst in sorted(groups.items()):
        tag = D.tag_for(date)
        rel = state.get(tag)
        reason = None
        if len({json.dumps(zkey(row)) for _, row in lst}) > 1:
            reason = "requests disagree on this video's ZIP (different SHA256); nothing delivered"
        elif rel and not rel["draft"]:
            reason = f"{tag} is published; the 008 entry only appends to drafts"
        elif vid in (rel or {}).get("videos", {}) and rel["videos"][vid] != zkey(lst[0][1]):
            rec = rel["videos"][vid]
            reason = (f"CONFLICT: {tag} already records {rec[0]} sha256 {rec[2]}, request has "
                      f"{lst[0][1]['zip_sha256']}; nothing overwritten")
        if reason:
            for ri, _ in lst:
                reqs[ri]["refused"].append({"video_id": vid, "reason": reason})
        elif vid in (rel or {}).get("videos", {}):
            for ri, _ in lst:
                reqs[ri]["delivered"].append(vid)
        else:
            reqs[lst[0][0]]["todo"].append(lst[0][1])
            for ri, _ in lst[1:]:
                reqs[ri]["duplicates"].append(vid)

    # copy out the data of the videos still to deliver
    for ri, r in enumerate(reqs):
        root = r["root"] = os.path.join(a.work, "data", str(ri))
        keep = []
        for row in r["todo"]:
            vid, d = row["video_id"], row["dir"]
            dst = lambda rel: os.path.join(root, *f"{d}/{rel}".split("/"))  # noqa: E731
            try:
                RB.check_rel(d)
                read_blob(bare, r["commit"], f"{d}/MASTER-PARTS/MASTER-PARTS.json", MAX_JSON, dst("MASTER-PARTS/MASTER-PARTS.json"))
                parts = load_json(dst("MASTER-PARTS/MASTER-PARTS.json")).get("parts")
                if not (isinstance(parts, list) and 0 < len(parts) <= RB.MAX_PARTS):
                    raise Reject("MASTER-PARTS.json: bad parts list")
                names = [p.get("name") if isinstance(p, dict) else None for p in parts]
                for n in names:
                    if not (isinstance(n, str) and re.fullmatch(re.escape(vid) + r"\.mp4\.part\d{2,4}", n)):
                        raise Reject(f"bad part name {n!r}")
                for rel, limit in SIDECARS + tuple((f"MASTER-PARTS/{n}", MAX_PART) for n in names):
                    read_blob(bare, r["commit"], f"{d}/{rel}", limit, dst(rel))
                keep.append(row)
            except (SystemExit, Exception) as e:      # one bad video never stops the others
                r["refused"].append({"video_id": vid, "reason": f"{type(e).__name__}: {e}" if not isinstance(e, (Reject, SystemExit)) else str(e)})
        r["todo"] = keep
        log(f"{r['request']}: station {r['station']} {r['date']}: {len(r['rows'])} listed, {len(keep)} to deliver, "
            f"{len(r['delivered'])} already delivered, {len(r['duplicates'])} duplicate, {len(r['refused'])} refused")
        for x in r["refused"]:
            log(f"REFUSED {r['request']} {x['video_id']}: {x['reason']}")
    if ignored:
        log(f"ignored {ignored} request file(s) of other stations copied onto a station branch")
    save_json({"requests": reqs, "rejected": rejected, "ignored_copies": ignored}, os.path.join(a.work, "plan.json"))


def cmd_rebuild(a):
    plan = load_json(os.path.join(a.work, "plan.json"))
    for ri, r in enumerate(plan["requests"]):
        out = os.path.join(a.work, "build", str(ri))
        r["pkgs"] = []
        for row in r["todo"]:
            try:
                RB.rebuild({"videos": [row]}, r["root"], out, log=log)
                r["pkgs"].append(os.path.join(out, "pkg", row["video_id"]))
            except (SystemExit, Exception) as e:
                r["refused"].append({"video_id": row["video_id"], "reason": f"rebuild: {e}"})
                log(f"REFUSED {r['request']} {row['video_id']}: rebuild: {e}")
    save_json(plan, os.path.join(a.work, "plan-built.json"))


def cmd_deliver(a):
    plan = load_json(os.path.join(a.work, "plan-built.json"))
    state = load_json(os.path.join(a.work, "state.json"))
    problems = list(plan.get("rejected", []))
    for r in plan["requests"]:
        problems += [{"request": r["request"], **x} for x in r["refused"]]
    work = []
    for ri, r in enumerate(plan["requests"]):
        if r["pkgs"]:
            work.append(("append", ri, r))
        elif not r["rows"] and D.tag_for(r["date"]) not in state:
            work.append(("init", ri, r))
    log(f"deliver: {len(work)} request(s) with work; {len(problems)} refused item(s) from the earlier steps")
    results = []
    if a.dry_run:
        for kind, _, r in work:
            log(f"DRY RUN {kind} {r['request']} -> {D.tag_for(r['date'])}: {[os.path.basename(p) for p in r['pkgs']]}")
    elif work:
        run = os.environ.get("GITHUB_RUN_ID", "local")
        with lock008.Lock(a.lock_dir, f"actions-{run}", wait_s=a.wait_s, note="delivery-008", branch=a.lock_branch):
            for kind, ri, r in work:
                try:
                    if kind == "init":
                        rel, created = D.ensure_draft(a.repo, r["date"])
                        res = {"request": r["request"], "action": "init", "release_tag": rel["tag_name"],
                               "draft": rel["draft"], "created": created}
                    else:
                        rep = D.append(a.repo, r["date"], r["pkgs"], report_path=os.path.join(a.work, "records", f"{ri}.json"))
                        res = {"request": r["request"], "action": "append", "release_tag": rep["release_tag"],
                               "draft": rep["draft"], "uploaded": rep["uploaded"], "skipped": rep["skipped"],
                               "videos_on_release": rep["videos"], "manifest_sha256": rep["manifest_sha256"],
                               "zips": {n: [v["size"], v["digest"]] for n, v in rep["assets"].items()
                                        if n.endswith("-DELIVERY.zip")}}
                    results.append(res)
                    log("DELIVERED " + json.dumps(res, ensure_ascii=False))
                except (SystemExit, Exception) as e:
                    problems.append({"request": r["request"], "reason": f"{kind}: {e}"})
                    log(f"FAILED {r['request']}: {e}")
    save_json({"results": results, "problems": problems}, os.path.join(a.work, "deliver-report.json"))
    for p in problems:
        log("PROBLEM " + json.dumps(p, ensure_ascii=False))
    log(f"summary: {len(results)} request(s) delivered or verified, {len(problems)} problem(s)")
    sys.exit(1 if problems else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("state"); p.add_argument("--repo", required=True); p.add_argument("--work", required=True)
    p = sub.add_parser("fetch"); p.add_argument("--config", required=True); p.add_argument("--work", required=True)
    p.add_argument("--source", help="git URL of the 008 repository (default https://github.com/<source_repo>.git)")
    p = sub.add_parser("rebuild"); p.add_argument("--work", required=True)
    p = sub.add_parser("deliver"); p.add_argument("--repo", required=True); p.add_argument("--work", required=True)
    p.add_argument("--lock-dir", required=True, help="checkout of the repository that holds the lock branch")
    p.add_argument("--lock-branch", default=lock008.BRANCH)
    p.add_argument("--wait-s", type=int, default=3600)
    p.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    {"state": cmd_state, "fetch": cmd_fetch, "rebuild": cmd_rebuild, "deliver": cmd_deliver}[a.cmd](a)


if __name__ == "__main__":
    main()
