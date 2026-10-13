"""Run an R2 DOWNLOAD.ps1 unmodified against tests/github_sim.py (shared by the test scripts).

Only the environment is substituted, never the tool:
  * Invoke-RestMethod  -> global function that sends https://api.github.com/... to the simulator
  * Get-Date (no args) -> fixed "today" from OPC_TODAY, to play several delivery days
  * curl.exe           -> shim that sends https://github.com/... to the simulator (302 + Range)
  * explorer.exe       -> no-op
The tool's own URL whitelist still sees the real github.com URLs.
"""
import os, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = {  # name -> (path, expected SHA256)
    "original": (os.path.join(HERE, "..", "r2-original", "01-给朋友", "DOWNLOAD.ps1"),
                 "c06e41581f4c0211113ce38effd7cabfb99db24c9051b0dce2d6dd657198457a"),
    "r2.1": (os.path.join(HERE, "..", "r2.1-patch", "DOWNLOAD.ps1"),
             "8ba15e78f2f24fbe70cf5fa77097baefc8931ed953f380e0453faf70727f781e"),
}


class ToolEnv:
    def __init__(self, work, srv_url, pwsh, tool):
        self.pwsh, self.tool = pwsh, tool
        shim, home = os.path.join(work, "shim"), os.path.join(work, "home")
        os.makedirs(shim)
        os.makedirs(home)
        self.base = os.path.join(home, "Downloads", "OPC-DELIVERIES")   # tool's choice without D:\
        with open(os.path.join(shim, "curl.exe"), "w") as f:
            f.write('#!/bin/bash\nargs=()\nfor x in "$@"; do args+=("${x/https:\\/\\/github.com\\//%s/web/}"); done\n'
                    'exec /usr/bin/curl "${args[@]}"\n' % srv_url)
        with open(os.path.join(shim, "explorer.exe"), "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        for x in ("curl.exe", "explorer.exe"):
            os.chmod(os.path.join(shim, x), 0o755)
        self.preload = os.path.join(shim, "preload.ps1")
        with open(self.preload, "w") as f:
            f.write(r"""
function global:Invoke-RestMethod { param($Uri, $Headers, $TimeoutSec)
  $u = ([string]$Uri) -replace '^https://api\.github\.com/', ($env:OPC_SIM + '/api/')
  Microsoft.PowerShell.Utility\Invoke-RestMethod -Uri $u -Headers $Headers -TimeoutSec $TimeoutSec }
function global:Get-Date {
  if ($args.Count -eq 0 -and $env:OPC_TODAY) { return [datetime]::ParseExact($env:OPC_TODAY, 'yyyy-MM-dd', $null) }
  Microsoft.PowerShell.Utility\Get-Date @args }
""")
        self.env = dict(os.environ, PATH=shim + os.pathsep + os.environ["PATH"], USERPROFILE=home, OPC_SIM=srv_url)

    def run(self, today, *extra, background=False):
        cmd = [self.pwsh, "-NoProfile", "-Command",
               f". '{self.preload}'; & '{self.tool}' {' '.join(extra)}; exit $LASTEXITCODE"]
        e = dict(self.env, OPC_TODAY=today)
        if background:
            return subprocess.Popen(cmd, env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, start_new_session=True)
        p = subprocess.run(cmd, env=e, capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr
