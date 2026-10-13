#!/usr/bin/env python3
"""Add one R2 batch (delivery-YYYY-MM-DD-NN) to a github_sim.py directory, using the same
manifest builder as publisher/opc_publish.py.  Usage: sim_add_batch.py SIMDIR TAG PKGDIR..."""
import json, os, re, shutil, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "publisher"))
import opc_publish

sim, tag, pkgs = sys.argv[1], sys.argv[2], sys.argv[3:]
date = re.match(r"^delivery-(\d{4}-\d{2}-\d{2})-\d{2}$", tag).group(1)
test = all(os.path.basename(p.rstrip("/")).startswith("TEST-") for p in pkgs)
videos = opc_publish.load_packages(pkgs, test)
m = opc_publish.build_manifest("xuelingshang/opc-video-deliveries", date, tag, videos, test)
os.makedirs(os.path.join(sim, "assets", tag), exist_ok=True)
for e, zp in videos:
    shutil.copyfile(zp, os.path.join(sim, "assets", tag, e["asset_name"]))
json.dump(m, open(os.path.join(sim, "assets", tag, "delivery-manifest.json"), "w"), ensure_ascii=False, indent=1)
rp = os.path.join(sim, "releases.json")
rel = json.load(open(rp)) if os.path.exists(rp) else []
rel.insert(0, dict(tag_name=tag, draft=False, prerelease=False))
json.dump(rel, open(rp, "w"), indent=1)
print("added", tag, [e["video_id"] for e, _ in videos])
