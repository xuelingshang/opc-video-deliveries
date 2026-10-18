"""Cross-station mutex for the 009 delivery release, built on git push fast-forward semantics.

One branch (default `delivery-009-lock`) in the repository the tool runs from is a chain of empty commits whose tip
message is the lock state. Deployed, that is the opc-video-deliveries checkout of the owner-controlled workflow
(its own GITHUB_TOKEN pushes the lock); a local run from a deliveries clone uses the same branch, so both serialise:

    OPC-009-LOCK FREE   station=<id> token=<uuid> at=<utc>      (anyone may take it)
    OPC-009-LOCK LOCKED station=<id> token=<uuid> at=<utc> ...  (held)

acquire: read the tip; if FREE (or LOCKED for longer than --stale-min minutes), push a LOCKED child of exactly
         that tip without --force. A second station that read the same tip pushes a different child, which git
         rejects as non-fast-forward, so only one writer wins (compare-and-swap). Losers wait and retry.
release: push a FREE child of our own LOCKED commit (again fast-forward only), so a lock that someone else broke
         is never "released" by us.
No ref is ever deleted or force-pushed, so the lock works for every writer that can push to that repository.
The full lock history stays readable with `git log` on the branch.
"""
import argparse, datetime, os, subprocess, sys, tempfile, time, uuid

BRANCH = "delivery-009-lock"
TAG = "OPC-009-LOCK"


def git(args, cwd, check=True):
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and p.returncode:
        raise RuntimeError(f"git {' '.join(args[:3])}: {p.stderr.strip()[-600:]}")
    return p


class Lock:
    def __init__(self, repo_dir, station, remote="origin", stale_min=180, wait_s=3600, note="", branch=BRANCH):
        self.dir, self.station, self.remote, self.branch = repo_dir, station, remote, branch
        self.stale_min, self.wait_s, self.note = stale_min, wait_s, note
        self.mine = None
        self.tree = self._empty_tree()

    def _empty_tree(self):
        p = subprocess.run(["git", "mktree"], cwd=self.dir, input="", capture_output=True, text=True, check=True)
        return p.stdout.strip()

    def _commit(self, parent, state):
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        msg = f"{TAG} {state} station={self.station} token={uuid.uuid4()} at={now}" + (f" note={self.note}" if self.note else "")
        args = ["commit-tree", self.tree, "-m", msg, "--no-gpg-sign"] + (["-p", parent] if parent else [])
        env = dict(os.environ, GIT_AUTHOR_NAME="opc-009-lock", GIT_AUTHOR_EMAIL="noreply@anthropic.com",
                   GIT_COMMITTER_NAME="opc-009-lock", GIT_COMMITTER_EMAIL="noreply@anthropic.com")
        p = subprocess.run(["git", *args], cwd=self.dir, capture_output=True, text=True, env=env, check=True)
        return p.stdout.strip(), msg

    def tip(self):
        p = git(["ls-remote", self.remote, f"refs/heads/{self.branch}"], self.dir)
        line = p.stdout.strip()
        if not line:
            return None, None
        sha = line.split()[0]
        git(["fetch", "-q", self.remote, f"+refs/heads/{self.branch}:refs/remotes/{self.remote}/opc-009-lock"], self.dir)
        msg = git(["log", "-1", "--format=%B", sha], self.dir).stdout.strip()
        return sha, msg

    def _push(self, sha):
        p = git(["push", self.remote, f"{sha}:refs/heads/{self.branch}"], self.dir, check=False)
        return p.returncode == 0, (p.stderr or p.stdout).strip()[-300:]

    @staticmethod
    def _age_min(msg):
        try:
            at = next(x for x in msg.split() if x.startswith("at="))[3:]
            t = datetime.datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
            return (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds() / 60
        except StopIteration:
            return 1e9

    def acquire(self):
        t_end = time.time() + self.wait_s
        delay = 5
        while True:
            sha, msg = self.tip()
            free = sha is None or msg.startswith(f"{TAG} FREE")
            stale = sha is not None and msg.startswith(f"{TAG} LOCKED") and self._age_min(msg) > self.stale_min
            if free or stale:
                c, m = self._commit(sha, "LOCKED")
                ok, err = self._push(c)
                if ok:
                    self.mine = c
                    print(f"[lock] acquired {self.branch} @ {c[:12]}{' (broke stale lock: ' + msg + ')' if stale else ''}", flush=True)
                    return c
                print(f"[lock] lost the race ({err.splitlines()[-1] if err else 'rejected'}); retrying", flush=True)
            else:
                print(f"[lock] held: {msg}; waiting", flush=True)
            if time.time() > t_end:
                raise SystemExit(f"[lock] could not acquire {self.branch} within {self.wait_s}s")
            time.sleep(delay)
            delay = min(60, delay * 2)

    def release(self):
        if not self.mine:
            return
        c, _ = self._commit(self.mine, "FREE")
        ok, err = self._push(c)
        if ok:
            print(f"[lock] released ({c[:12]})", flush=True)
        else:
            print(f"[lock] release refused (someone broke our lock?): {err}", flush=True)
        self.mine = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["status", "acquire-test"])
    ap.add_argument("--repo-dir", default=os.getcwd())
    ap.add_argument("--station", default="?")
    ap.add_argument("--branch", default=BRANCH)
    a = ap.parse_args()
    lk = Lock(a.repo_dir, a.station, branch=a.branch)
    if a.cmd == "status":
        sha, msg = lk.tip()
        print(sha, msg)
    else:
        with lk:
            print("[lock] holding for 2 s")
            time.sleep(2)


if __name__ == "__main__":
    main()
