#!/usr/bin/env python3
"""Minimal stand-in for `gh api` covering the Releases calls made by publisher/opc_publish.py.
State lives in $FAKE_GH_DIR; published releases are mirrored into $FAKE_GH_SIM (github_sim.py
directory) so the anonymous download check and the friend tool can read them.
Release/tag DELETE removes them from both. Fault injection: $FAKE_GH_FAIL_UPLOAD=<asset name>:<count>, $FAKE_GH_NO_DIGEST=1."""
import hashlib, json, os, re, shutil, sys, urllib.parse

D = os.environ["FAKE_GH_DIR"]; SIM = os.environ.get("FAKE_GH_SIM")
SP = os.path.join(D, "state.json")
st = json.load(open(SP)) if os.path.exists(SP) else dict(next_id=1, releases=[])


def save():
    json.dump(st, open(SP, "w"), indent=1)


def out(o):
    sys.stdout.write(json.dumps(o)); save(); sys.exit(0)


def fail(msg, code=1):
    sys.stderr.write(msg + "\n"); save(); sys.exit(code)


def view(r):
    r = dict(r)
    if os.environ.get("FAKE_GH_NO_DIGEST"):
        r["assets"] = [{k: v for k, v in a.items() if k != "digest"} for a in r["assets"]]
    return r


args = sys.argv[1:]
assert args[0] == "api"; args = args[1:]
method, headers, inp, fields, pos = "GET", [], None, {}, []
i = 0
while i < len(args):
    a = args[i]
    if a == "--method": method = args[i + 1]; i += 2
    elif a == "-H": headers.append(args[i + 1]); i += 2
    elif a == "--input": inp = args[i + 1]; i += 2
    elif a in ("-f", "-F"):
        k, v = args[i + 1].split("=", 1)
        if a == "-F" and v in ("true", "false"): v = v == "true"
        fields[k] = v; i += 2
    else: pos.append(a); i += 1
if fields and method == "GET": method = "POST"
u = urllib.parse.urlsplit(pos[0]); path = u.path.lstrip("/"); q = urllib.parse.parse_qs(u.query)
rels = st["releases"]
byid = lambda rid: next((r for r in rels if r["id"] == int(rid)), None)

if re.fullmatch(r"repos/[^/]+/[^/]+/releases", path):
    if method == "GET":
        per, page = int(q.get("per_page", ["30"])[0]), int(q.get("page", ["1"])[0])
        out([view(r) for r in rels[(page - 1) * per: page * per]])
    if any(r["tag_name"] == fields["tag_name"] and not r["draft"] for r in rels):
        fail("tag already exists", 1)
    r = dict(id=st["next_id"], tag_name=fields["tag_name"], name=fields.get("name"), draft=bool(fields.get("draft")),
             prerelease=bool(fields.get("prerelease")), assets=[], html_url=f"https://github.com/x/releases/tag/{fields['tag_name']}")
    st["next_id"] += 1; rels.insert(0, r); out(r)
m = re.fullmatch(r"repos/[^/]+/[^/]+/releases/assets/(\d+)", path)
if m:
    aid = int(m.group(1))
    for r in rels:
        for a in r["assets"]:
            if a["id"] == aid:
                if method == "DELETE":
                    if not r["draft"]: fail("refusing to delete asset of published release in fake")
                    r["assets"].remove(a); os.remove(a["_file"]); out({})
                sys.stdout.buffer.write(open(a["_file"], "rb").read()); sys.exit(0)
    fail("asset not found", 1)
m = re.fullmatch(r"repos/[^/]+/[^/]+/releases/(\d+)/assets", path)
if m and u.netloc == "uploads.github.com":
    r = byid(m.group(1)); name = q["name"][0]
    spec = os.environ.get("FAKE_GH_FAIL_UPLOAD", "")
    if spec.split(":")[0] == name:
        cnt_file = os.path.join(D, "fail-count"); n = int(open(cnt_file).read()) if os.path.exists(cnt_file) else 0
        if n < int(spec.split(":")[1]):
            open(cnt_file, "w").write(str(n + 1)); fail("simulated upload failure")
    os.makedirs(os.path.join(D, "files", str(r["id"])), exist_ok=True)
    dst = os.path.join(D, "files", str(r["id"]), name); shutil.copyfile(inp, dst)
    data = open(dst, "rb").read()
    a = dict(id=st["next_id"], name=name, size=len(data), state="uploaded", digest="sha256:" + hashlib.sha256(data).hexdigest(), _file=dst)
    st["next_id"] += 1; r["assets"].append(a); out(a)
m = re.fullmatch(r"repos/[^/]+/[^/]+/releases/(\d+)", path)
if m:
    r = byid(m.group(1))
    if method == "PATCH":
        was_draft = r["draft"]
        for k in ("draft", "prerelease"):
            if k in fields: r[k] = fields[k]
        if was_draft and not r["draft"] and SIM:
            os.makedirs(os.path.join(SIM, "assets", r["tag_name"]), exist_ok=True)
            for a in r["assets"]:
                shutil.copyfile(a["_file"], os.path.join(SIM, "assets", r["tag_name"], a["name"]))
            rp = os.path.join(SIM, "releases.json"); sr = json.load(open(rp)) if os.path.exists(rp) else []
            web = [dict(name=a["name"], size=a["size"], state="uploaded", browser_download_url=
                        f"https://github.com/xuelingshang/opc-video-deliveries/releases/download/{r['tag_name']}/{a['name']}")
                   for a in r["assets"]]   # the R2 tool reads these fields from the release list
            sr.insert(0, dict(tag_name=r["tag_name"], draft=False, prerelease=r["prerelease"], assets=web)); json.dump(sr, open(rp, "w"))
    if method == "DELETE":
        rels.remove(r)
        if SIM:
            rp = os.path.join(SIM, "releases.json")
            json.dump([x for x in json.load(open(rp)) if x["tag_name"] != r["tag_name"]], open(rp, "w"))
            shutil.rmtree(os.path.join(SIM, "assets", r["tag_name"]), ignore_errors=True)
        out({})
    out(view(r))
m = re.fullmatch(r"repos/[^/]+/[^/]+/git/refs/tags/(.+)", path)
if m and method == "DELETE":
    out({})
fail(f"fake gh: unsupported {method} {pos[0]}", 2)
