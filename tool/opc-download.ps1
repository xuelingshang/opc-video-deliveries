<#
  OPC 朋友端一键下载工具（R2 协议兼容版）

  双击同目录的 OPC-Download.cmd 即可运行；不需要 GitHub 账号、密码或 Token。

  读取与现有 R2 工具相同的公开 Release：
    * 仓库 xuelingshang/opc-video-deliveries
    * Release 标签 delivery-YYYY-MM-DD-NN，每批一个 delivery-manifest.json（schema_version=1）
    * 每条视频一个 VIDEO-ID-DELIVERY.zip，内部为 VIDEO-ID/VIDEO-ID.mp4、cover.jpg、weibo.txt、subtitle.srt

  做的事情：
    1. 找出所有计划交付日期已到（北京时间）的批次；以前没下载完或后来补发的批次自动补齐。
    2. 每条视频下载 ZIP（支持断点续传），校验 ZIP 与其中文件的 SHA256。
    3. 整理到  D:\OPC-DELIVERIES\YYYY-MM-DD\VIDEO-ID\
    4. 已校验成功的视频再次运行时直接跳过。
    5. 编号以 TEST- 开头的测试样片默认不下载；加 -IncludeTest 时单独放在 _TEST 文件夹。

  兼容 Windows PowerShell 5.1（Windows 10/11 自带）和 PowerShell 7。
#>
[CmdletBinding()]
param(
    [string]$Root = '',
    [switch]$IncludeTest,
    [string]$Today = '',
    [string]$StartDate = '2026-10-13',
    [switch]$KeepZip,
    [switch]$VerifyAll,
    [string]$Repo = 'xuelingshang/opc-video-deliveries',
    [string]$ApiBase = 'https://api.github.com',
    [string]$WebBase = 'https://github.com'
)

$ErrorActionPreference = 'Stop'
$ToolName = 'OPC 交付下载（R2 协议兼容版）'
$ToolBuild = '2026-10-13'
$ManifestName = 'delivery-manifest.json'
$TagPattern = '^delivery-(\d{4}-\d{2}-\d{2})-(\d{2})$'
$StallSeconds = 120
$MaxAttempts = 5

# ---------------------------------------------------------------- setup
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }
Add-Type -AssemblyName System.Net.Http
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$IsWin = ($env:OS -eq 'Windows_NT')
if (-not $Root) {
    if ($IsWin) {
        if (Test-Path -LiteralPath 'D:\') { $Root = 'D:\OPC-DELIVERIES' }
        else {
            $Root = Join-Path $env:USERPROFILE 'OPC-DELIVERIES'
            Write-Host "提示：这台电脑没有 D 盘，改为保存到 $Root" -ForegroundColor Yellow
        }
    } else {
        throw '非 Windows 环境请用 -Root 指定下载目录'
    }
}
if (-not (Test-Path -LiteralPath $Root)) { New-Item -ItemType Directory -Force -Path $Root | Out-Null }
$Root = (Resolve-Path -LiteralPath $Root).Path
$TestRoot = Join-Path $Root '_TEST'
$OpcDir = Join-Path $Root '.opc'
foreach ($d in @($OpcDir, (Join-Path $OpcDir 'logs'), (Join-Path $OpcDir 'downloads'), (Join-Path $OpcDir 'staging'), (Join-Path $OpcDir 'quarantine'))) {
    if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
}
$LogFile = Join-Path (Join-Path $OpcDir 'logs') ('run-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')

function Log([string]$msg, [string]$color = '') {
    $line = (Get-Date -Format 'HH:mm:ss') + '  ' + $msg
    if ($color) { Write-Host $line -ForegroundColor $color } else { Write-Host $line }
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
}

$LockPath = Join-Path $OpcDir 'lock'
try {
    $Lock = [System.IO.File]::Open($LockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
} catch {
    Write-Host '另一个下载窗口正在运行，请等它结束后再试。' -ForegroundColor Yellow
    exit 3
}

if ($Today) {
    if ($Today -notmatch '^\d{4}-\d{2}-\d{2}$') { throw "-Today 格式应为 YYYY-MM-DD：$Today" }
} else {
    $Today = [DateTime]::UtcNow.AddHours(8).ToString('yyyy-MM-dd')   # 北京时间（无夏令时）
}

$Handler = New-Object System.Net.Http.HttpClientHandler
$Handler.AllowAutoRedirect = $false          # 手动跟随跳转，保证续传的 Range 头不会丢
$Handler.UseProxy = $true                    # 使用系统代理设置
$Client = New-Object System.Net.Http.HttpClient($Handler)
$Client.Timeout = [TimeSpan]::FromMinutes(10)
$Client.DefaultRequestHeaders.UserAgent.ParseAdd('OPC-Friend-Downloader-R2compat/' + $ToolBuild)

function Test-UrlAllowed([System.Uri]$u) {
    if ($u.Scheme -eq 'https') { return $true }
    return ($u.Scheme -eq 'http' -and ($u.Host -eq '127.0.0.1' -or $u.Host -eq 'localhost'))   # 仅本机自测
}

function Send-Get([string]$url, [long]$offset, [string]$accept = '') {
    $current = New-Object System.Uri($url)
    for ($hop = 0; $hop -lt 10; $hop++) {
        if (-not (Test-UrlAllowed $current)) { throw ('不安全的下载地址：' + $current.AbsoluteUri) }
        $req = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Get, $current)
        if ($accept) { [void]$req.Headers.TryAddWithoutValidation('Accept', $accept) }
        if ($offset -gt 0) { $req.Headers.Range = New-Object System.Net.Http.Headers.RangeHeaderValue($offset, $null) }
        $resp = $Client.SendAsync($req, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        $code = [int]$resp.StatusCode
        if ($code -in 301, 302, 303, 307, 308) {
            $loc = $resp.Headers.Location
            $resp.Dispose()
            if ($null -eq $loc) { throw '跳转缺少 Location' }
            if (-not $loc.IsAbsoluteUri) { $loc = New-Object System.Uri($current, $loc) }
            $current = $loc
            continue
        }
        return $resp
    }
    throw '跳转次数过多'
}

# returns $null on 404, text otherwise; throws on other errors
function Get-Text([string]$url, [string]$accept = '') {
    $resp = Send-Get $url 0 $accept
    try {
        if ([int]$resp.StatusCode -eq 404) { return $null }
        if (-not $resp.IsSuccessStatusCode) { throw ('HTTP ' + [int]$resp.StatusCode) }
        $bytes = $resp.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
        return [System.Text.Encoding]::UTF8.GetString($bytes).TrimStart([char]0xFEFF)
    } finally { $resp.Dispose() }
}

function Get-Sha256([string]$path) { return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }

function Format-Size([long]$b) {
    if ($b -ge 1GB) { return ('{0:N2} GB' -f ($b / 1GB)) }
    if ($b -ge 1MB) { return ('{0:N1} MB' -f ($b / 1MB)) }
    return ('{0} B' -f $b)
}

# ---------------------------------------------------------------- download with resume
function Receive-File([string]$url, [string]$dest, [long]$expectedBytes, [string]$expectedSha) {
    $partial = $dest + '.partial'
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            $offset = 0L
            if (Test-Path -LiteralPath $partial) { $offset = (Get-Item -LiteralPath $partial).Length }
            if ($offset -gt $expectedBytes) { Remove-Item -LiteralPath $partial -Force; $offset = 0L }
            if ($offset -lt $expectedBytes) {
                $resp = Send-Get $url $offset
                try {
                    $code = [int]$resp.StatusCode
                    if (-not $resp.IsSuccessStatusCode) { throw ('HTTP ' + $code) }
                    $append = ($offset -gt 0 -and $code -eq 206)
                    if ($offset -gt 0 -and -not $append) { Log '  服务器未返回续传数据，从头下载'; $offset = 0L }
                    if ($append) { Log ('  断点续传：已有 ' + (Format-Size $offset) + '，从这里继续') }
                    $mode = [System.IO.FileMode]::Create
                    if ($append) { $mode = [System.IO.FileMode]::Append }
                    $fs = New-Object System.IO.FileStream($partial, $mode, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
                    try {
                        $stream = $resp.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
                        $buf = New-Object byte[] (1MB)
                        $done = $offset
                        $step = [Math]::Max(1MB, [long]($expectedBytes / 10))
                        $nextReport = $done + $step
                        while ($true) {
                            $task = $stream.ReadAsync($buf, 0, $buf.Length)
                            if (-not $task.Wait($StallSeconds * 1000)) { throw ('网络停滞超过 ' + $StallSeconds + ' 秒') }
                            $n = $task.Result
                            if ($n -le 0) { break }
                            $fs.Write($buf, 0, $n)
                            $done += $n
                            if ($done -gt $expectedBytes) { throw '下载数据比清单记录的大' }
                            if ($done -ge $nextReport) {
                                Log ('  已下载 ' + (Format-Size $done) + ' / ' + (Format-Size $expectedBytes) + ('（{0:P0}）' -f ($done / $expectedBytes)))
                                $nextReport = $done + $step
                            }
                        }
                    } finally { $fs.Dispose() }
                } finally { $resp.Dispose() }
            }
            $len = (Get-Item -LiteralPath $partial).Length
            if ($len -ne $expectedBytes) { throw ('下载不完整 ' + $len + '/' + $expectedBytes) }
            if ((Get-Sha256 $partial) -ne $expectedSha) {
                Remove-Item -LiteralPath $partial -Force
                throw 'ZIP 的 SHA256 与清单不一致（已删除，重新下载）'
            }
            if (Test-Path -LiteralPath $dest) { Remove-Item -LiteralPath $dest -Force }
            Move-Item -LiteralPath $partial -Destination $dest
            return
        } catch {
            Log ('  第 ' + $attempt + ' 次下载未完成：' + $_.Exception.Message) 'Yellow'
            if ($attempt -eq $MaxAttempts) { throw }
            Start-Sleep -Seconds ([Math]::Min(60, 5 * $attempt))
        }
    }
}

# ---------------------------------------------------------------- R2 manifest
# name/value pairs of a hashtable (written this run) or a PSCustomObject (read from state.json)
function Get-Pairs($o) {
    if ($null -eq $o) { return @() }
    if ($o -is [System.Collections.IDictionary]) { return @($o.GetEnumerator() | ForEach-Object { @{ Name = [string]$_.Key; Value = $_.Value } }) }
    return @($o.PSObject.Properties | ForEach-Object { @{ Name = $_.Name; Value = $_.Value } })
}

function Get-Prop($o, [string[]]$names) {
    foreach ($n in $names) { if ($null -ne $o.PSObject.Properties[$n]) { return $o.$n } }
    return $null
}

# Normalise one videos[] entry; returns a hashtable or a string describing the problem.
function ConvertTo-Video($v, [string]$tag) {
    $id = [string]$v.video_id
    if ($id -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') { return "编号不合法：$id" }
    if ([string]$v.asset_name -ne "$id-DELIVERY.zip") { return "$id 的 asset_name 应为 $id-DELIVERY.zip" }
    if ([string]$v.sha256 -notmatch '^[0-9a-fA-F]{64}$') { return "$id 的 sha256 不合法" }
    if ([long]$v.size_bytes -le 0) { return "$id 的 size_bytes 不合法" }
    $want = @("$id.mp4", 'cover.jpg', 'weibo.txt', 'subtitle.srt')
    $files = @()
    foreach ($f in @($v.files)) {
        if ($f -is [string]) { $p = $f; $sz = $null; $sh = $null }
        else {
            $p = [string](Get-Prop $f @('path', 'name', 'file'))
            $sz = Get-Prop $f @('size_bytes', 'bytes', 'size')
            $sh = Get-Prop $f @('sha256')
        }
        $name = $p
        if ($p -like "$id/*") { $name = $p.Substring($id.Length + 1) }
        if ($want -notcontains $name) { return "$id 的 files 含有规范外的文件：$p" }
        if ($null -ne $sh -and [string]$sh -notmatch '^[0-9a-fA-F]{64}$') { return "$id 的文件 sha256 不合法" }
        $files += @{ name = $name; size = $sz; sha = $(if ($null -ne $sh) { ([string]$sh).ToLowerInvariant() } else { $null }) }
    }
    $names = @($files | ForEach-Object { $_.name } | Sort-Object -Unique)
    if ($names.Count -ne 4) { return "$id 的 files 应正好包含 4 个文件" }
    return @{
        id = $id; asset = [string]$v.asset_name; bytes = [long]$v.size_bytes; sha = ([string]$v.sha256).ToLowerInvariant()
        files = $files; tag = $tag; test = $id.StartsWith('TEST-')
        url = "$WebBase/$Repo/releases/download/$tag/" + [string]$v.asset_name
    }
}

function Get-DeliveryTags {
    $tags = @()
    try {
        for ($page = 1; $page -le 20; $page++) {
            $txt = Get-Text "$ApiBase/repos/$Repo/releases?per_page=100&page=$page" 'application/vnd.github+json'
            if ($null -eq $txt) { throw '仓库不存在或不可见' }
            $list = @($txt | ConvertFrom-Json)
            foreach ($r in $list) {
                if ($r.draft) { continue }
                if ([string]$r.tag_name -match $TagPattern) { $tags += [string]$r.tag_name }
            }
            if ($list.Count -lt 100) { break }
        }
        Log ("通过 GitHub 列表找到 $($tags.Count) 个交付批次。")
        return ,$tags
    } catch {
        Log ("GitHub 列表暂不可用（$($_.Exception.Message)），改为按日期逐批查找 …") 'DarkYellow'
    }
    $tags = @()
    $d = [DateTime]::ParseExact($StartDate, 'yyyy-MM-dd', $null)
    $end = [DateTime]::ParseExact($Today, 'yyyy-MM-dd', $null)
    while ($d -le $end) {
        $ds = $d.ToString('yyyy-MM-dd'); $miss = 0
        for ($nn = 1; $nn -le 99 -and $miss -lt 2; $nn++) {
            $tag = 'delivery-{0}-{1:D2}' -f $ds, $nn
            if ($null -ne (Get-Text "$WebBase/$Repo/releases/download/$tag/$ManifestName")) { $tags += $tag; $miss = 0 } else { $miss++ }
        }
        $d = $d.AddDays(1)
    }
    Log ("按日期查找到 $($tags.Count) 个交付批次。")
    return ,$tags
}

# ---------------------------------------------------------------- local state
$StatePath = Join-Path $OpcDir 'state.json'
$Videos = @{}
$Batches = @{}
if (Test-Path -LiteralPath $StatePath) {
    try {
        $raw = [System.IO.File]::ReadAllText($StatePath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
        if ($raw.videos) { foreach ($p in $raw.videos.PSObject.Properties) { $Videos[$p.Name] = $p.Value } }
        if ($raw.batches) { foreach ($p in $raw.batches.PSObject.Properties) { $Batches[$p.Name] = $p.Value } }
    } catch { Log '本地记录无法读取，将重新校验已有文件。' 'Yellow'; $Videos = @{}; $Batches = @{} }
}
function Save-State {
    $tmp = $StatePath + '.tmp'
    $obj = @{ tool = $ToolBuild; videos = $Videos; batches = $Batches }
    [System.IO.File]::WriteAllText($tmp, ($obj | ConvertTo-Json -Depth 8), (New-Object System.Text.UTF8Encoding($false)))
    if (Test-Path -LiteralPath $StatePath) { Remove-Item -LiteralPath $StatePath -Force }
    Move-Item -LiteralPath $tmp -Destination $StatePath
}

function Test-Delivered([string]$dir, $v) {
    foreach ($f in $v.files) {
        $p = Join-Path $dir $f.name
        if (-not (Test-Path -LiteralPath $p)) { return $false }
        if ($null -ne $f.size -and (Get-Item -LiteralPath $p).Length -ne [long]$f.size) { return $false }
    }
    $rec = $null
    if ($Videos.ContainsKey($v.id)) { $rec = $Videos[$v.id] }
    if ((-not $VerifyAll) -and $null -ne $rec -and [string]$rec.zip_sha256 -eq $v.sha -and [string]$rec.path -eq $dir) {
        $same = $true
        foreach ($f in $v.files) {
            $ticks = (Get-Item -LiteralPath (Join-Path $dir $f.name)).LastWriteTimeUtc.Ticks
            $saved = $rec.mtimes.($f.name)
            if ($null -eq $saved -or [long]$saved -ne $ticks) { $same = $false; break }
        }
        if ($same) { return $true }
        # 文件被改动过：只有在知道每个文件的 SHA256 时才能重新确认
        foreach ($f in $v.files) {
            $known = $f.sha
            if ($null -eq $known) { $known = $rec.sha.($f.name) }
            if ($null -eq $known -or (Get-Sha256 (Join-Path $dir $f.name)) -ne [string]$known) { return $false }
        }
        Set-Delivered $dir $v
        return $true
    }
    foreach ($f in $v.files) {
        if ($null -eq $f.sha) { return $false }        # 没有逐文件校验值时，以本工具的下载记录为准
        if ((Get-Sha256 (Join-Path $dir $f.name)) -ne $f.sha) { return $false }
    }
    Set-Delivered $dir $v
    return $true
}

function Set-Delivered([string]$dir, $v) {
    $mt = @{}; $sh = @{}
    foreach ($f in $v.files) {
        $p = Join-Path $dir $f.name
        $mt[$f.name] = (Get-Item -LiteralPath $p).LastWriteTimeUtc.Ticks
        if ($null -ne $f.sha) { $sh[$f.name] = $f.sha } else { $sh[$f.name] = Get-Sha256 $p }
    }
    $Videos[$v.id] = @{ path = $dir; zip_sha256 = $v.sha; release_tag = $v.tag; mtimes = $mt; sha = $sh; verified_utc = [DateTime]::UtcNow.ToString('s') + 'Z' }
    Save-State
}

function Move-ToQuarantine([string]$dir, [string]$why) {
    $q = Join-Path (Join-Path $OpcDir 'quarantine') ((Split-Path -Leaf (Split-Path -Parent $dir)) + '_' + (Split-Path -Leaf $dir) + '_' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    Move-Item -LiteralPath $dir -Destination $q
    Log ("  原文件夹与清单不一致（$why），已整体移到 $q 保存，未删除。") 'Yellow'
}

function Install-Video($v, [string]$date) {
    $base = $Root
    if ($v.test) { $base = $TestRoot }
    $dateDir = Join-Path $base $date
    $target = Join-Path $dateDir $v.id
    if (Test-Path -LiteralPath $target) {
        if (Test-Delivered $target $v) { return 'SKIP' }
        Move-ToQuarantine $target '校验不通过'
    }
    if ($Videos.ContainsKey($v.id)) {
        $old = [string]$Videos[$v.id].path
        if ($old -and $old -ne $target -and (Test-Path -LiteralPath $old) -and [string]$Videos[$v.id].zip_sha256 -eq $v.sha -and (Test-Delivered $old $v)) {
            if (-not (Test-Path -LiteralPath $dateDir)) { New-Item -ItemType Directory -Force -Path $dateDir | Out-Null }
            Move-Item -LiteralPath $old -Destination $target
            Set-Delivered $target $v
            Log ("  已从 $old 移到 $target（无需重新下载）")
            return 'MOVED'
        }
    }
    $need = $v.bytes * 2 + 200MB
    $free = (New-Object System.IO.DriveInfo([System.IO.Path]::GetPathRoot($Root))).AvailableFreeSpace
    if ($free -lt $need) { throw ('磁盘空间不足：需要约 ' + (Format-Size $need) + '，可用 ' + (Format-Size $free)) }

    $zipPath = Join-Path (Join-Path $OpcDir 'downloads') ($v.id + '-' + $v.sha.Substring(0, 12) + '.zip')
    if ((Test-Path -LiteralPath $zipPath) -and (Get-Sha256 $zipPath) -ne $v.sha) { Remove-Item -LiteralPath $zipPath -Force }
    if (-not (Test-Path -LiteralPath $zipPath)) {
        Log ('  下载 ' + $v.asset + '（' + (Format-Size $v.bytes) + '）…')
        Receive-File $v.url $zipPath $v.bytes $v.sha
    }
    Log '  ZIP 校验通过，解压并逐个校验文件 …'
    $stage = Join-Path (Join-Path $OpcDir 'staging') ($v.id + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
    $stageVid = Join-Path $stage $v.id
    New-Item -ItemType Directory -Force -Path $stageVid | Out-Null
    try {
        $byName = @{}
        foreach ($f in $v.files) { $byName[$v.id + '/' + $f.name] = $f }
        $zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
        try {
            $entries = @($zip.Entries | Where-Object { -not $_.FullName.EndsWith('/') })
            if ($entries.Count -ne 4) { throw ('ZIP 内应为 4 个文件，实际 ' + $entries.Count) }
            foreach ($ze in $entries) {
                if (-not $byName.ContainsKey($ze.FullName)) { throw ('ZIP 内有规范外的文件：' + $ze.FullName) }
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($ze, (Join-Path $stageVid $byName[$ze.FullName].name), $true)
            }
        } finally { $zip.Dispose() }
        foreach ($f in $v.files) {
            $p = Join-Path $stageVid $f.name
            if ($null -ne $f.size -and (Get-Item -LiteralPath $p).Length -ne [long]$f.size) { throw ('文件大小不符：' + $f.name) }
            if ($null -ne $f.sha -and (Get-Sha256 $p) -ne $f.sha) { throw ('文件校验失败：' + $f.name) }
        }
        if (-not (Test-Path -LiteralPath $dateDir)) { New-Item -ItemType Directory -Force -Path $dateDir | Out-Null }
        Move-Item -LiteralPath $stageVid -Destination $target
        Set-Delivered $target $v
    } finally {
        if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    }
    if (-not $KeepZip) { Remove-Item -LiteralPath $zipPath -Force }
    return 'NEW'
}

# ---------------------------------------------------------------- main
Log ("$ToolName $ToolBuild · 北京时间今天 $Today · 保存到 $Root")
if ($IncludeTest) { Log '已开启测试样片：TEST- 开头的视频单独保存到 _TEST 文件夹。' 'Yellow' }

$allTags = Get-DeliveryTags
$due = @($allTags | Where-Object { $_ -match $TagPattern -and [string]::CompareOrdinal($Matches[1], $Today) -le 0 } | Sort-Object)
$notDue = @($allTags).Count - $due.Count
Log ("已到期批次 $($due.Count) 个；未到期批次 $notDue 个（到期后再运行即可）。")

$cNew = 0; $cSkip = 0; $cMoved = 0; $cFail = 0; $cTest = 0; $cBad = 0
foreach ($tag in $due) {
    $null = $tag -match $TagPattern
    $date = $Matches[1]
    $b = $null
    if ($Batches.ContainsKey($tag)) { $b = $Batches[$tag] }
    # 已全部校验完成的批次：本地文件未变动就不再请求网络
    if ((-not $VerifyAll) -and $null -ne $b -and $b.complete -and [bool]$b.include_test -eq [bool]$IncludeTest) {
        $allOk = $true
        foreach ($vid in @($b.video_ids)) {
            $rec = $null
            if ($Videos.ContainsKey($vid)) { $rec = $Videos[$vid] }
            if ($null -eq $rec -or -not (Test-Path -LiteralPath ([string]$rec.path))) { $allOk = $false; break }
            foreach ($p in (Get-Pairs $rec.mtimes)) {
                $fp = Join-Path ([string]$rec.path) $p.Name
                if (-not (Test-Path -LiteralPath $fp) -or (Get-Item -LiteralPath $fp).LastWriteTimeUtc.Ticks -ne [long]$p.Value) { $allOk = $false; break }
            }
            if (-not $allOk) { break }
        }
        if ($allOk) { $cSkip += @($b.video_ids).Count; Log ("[$tag] 本批已全部校验完成，跳过。") 'DarkGray'; continue }
    }
    Log ("[$tag] 读取清单 …")
    try {
        $txt = Get-Text "$WebBase/$Repo/releases/download/$tag/$ManifestName"
        if ($null -eq $txt) { throw "没有 $ManifestName" }
        $m = $txt | ConvertFrom-Json
        if ([int]$m.schema_version -ne 1) { throw ('schema_version 不是 1：' + $m.schema_version) }
        if ([string]$m.repository -ne $Repo) { throw ('repository 不符：' + $m.repository) }
        if ([string]$m.release_tag -ne $tag) { throw ('release_tag 不符：' + $m.release_tag) }
        if ([string]$m.delivery_date -ne $date) { throw ('delivery_date 与标签日期不符：' + $m.delivery_date) }
    } catch {
        $cFail++; Log ("  清单不可用：$($_.Exception.Message)") 'Red'; continue
    }
    $batchOk = $true; $ids = @()
    foreach ($raw in @($m.videos)) {
        $v = ConvertTo-Video $raw $tag
        if ($v -is [string]) { $cBad++; $batchOk = $false; Log ("  清单条目已忽略：$v") 'Red'; continue }
        if ($v.test -and -not $IncludeTest) { $cTest++; Log ("  $($v.id) 是测试样片，未下载（需要时加 -IncludeTest）。") 'DarkGray'; continue }
        Log ("  $($v.id)")
        try {
            switch (Install-Video $v $date) {
                'SKIP' { $cSkip++; Log '    已校验，跳过。' 'DarkGray' }
                'MOVED' { $cMoved++ }
                'NEW' { $cNew++; Log ('    完成：' + (Join-Path (Join-Path $(if ($v.test) { $TestRoot } else { $Root }) $date) $v.id)) 'Green' }
            }
            $ids += $v.id
        } catch {
            $cFail++; $batchOk = $false
            Log ('    未完成：' + $_.Exception.Message + '（已下载的部分会保留，下次运行自动续传）') 'Red'
        }
    }
    $Batches[$tag] = @{ complete = $batchOk; include_test = [bool]$IncludeTest; video_ids = $ids; checked_utc = [DateTime]::UtcNow.ToString('s') + 'Z' }
    Save-State
}
$summaryColor = 'Green'
if ($cFail -gt 0 -or $cBad -gt 0) { $summaryColor = 'Red' }
Log ("本次：新下载 $cNew 条，已有跳过 $cSkip 条，移动 $cMoved 条，未完成 $cFail 条，清单异常 $cBad 条，测试样片未下载 $cTest 条，未到期批次 $notDue 个。") $summaryColor
Log ("日志：$LogFile")
$Lock.Dispose()
if ($cFail -gt 0 -or $cBad -gt 0) { exit 1 }
exit 0
