param(
  [string]$Repository = 'xuelingshang/opc-video-deliveries',
  [string]$Date = '',
  [string]$Tag = ''
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

function Fetch-Json([string]$Url) {
  Invoke-RestMethod -Uri $Url -Headers @{ 'User-Agent'='OPC-Public-Delivery-R2'; 'Accept'='application/vnd.github+json' } -TimeoutSec 70
}
function Sha([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Is-Verified([string]$Root, $Files, [bool]$FullHash=$true) {
  foreach($f in $Files){
    $name=[string]$f.name
    if($name -notmatch '^[A-Za-z0-9._-]+$' -or $name -eq '.' -or $name -eq '..'){throw "非法文件名: $name"}
    $p=Join-Path $Root $name
    if(-not (Test-Path -LiteralPath $p -PathType Leaf)){return $false}
    if((Get-Item -LiteralPath $p).Length -ne [long]$f.size_bytes){return $false}
    if($FullHash -and (Sha $p) -ne [string]$f.sha256){return $false}
  }
  return $true
}
function Download-File([string]$Url, [string]$Out, [string]$Expected, [long]$ExpectedSize) {
  if($Url -notmatch '^https://github\.com/xuelingshang/opc-video-deliveries/releases/download/'){
    throw "拒绝非指定公开仓库的下载地址: $Url"
  }
  if((Test-Path -LiteralPath $Out -PathType Leaf) -and
     (Get-Item -LiteralPath $Out).Length -eq $ExpectedSize -and
     (Sha $Out) -eq $Expected){return}
  $tmp="$Out.partial"
  for($attempt=1;$attempt -le 3;$attempt++){
    Write-Host "    下载尝试 $attempt/3 ..."
    & curl.exe -f -L -sS --retry 5 --retry-delay 3 -C - -o $tmp $Url
    if($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $tmp -PathType Leaf)){
      if((Get-Item -LiteralPath $tmp).Length -eq $ExpectedSize -and (Sha $tmp) -eq $Expected){
        Move-Item -LiteralPath $tmp -Destination $Out -Force
        return
      }
      # Completed but bad data: restart this file only.
      Remove-Item -LiteralPath $tmp -Force
    }
    # Interrupted transfers keep .partial for the next retry or next run.
  }
  throw "下载失败或SHA256不符，可重复双击继续: $Out"
}
function Release-Day([string]$tag) {
  if($tag -match '^daily-(20\d\d-\d\d-\d\d)$'){return $Matches[1]}
  if($tag -match '^delivery-(20\d\d-\d\d-\d\d)-([0-9]{2,3})$'){return $Matches[1]}
  return $null
}
function Get-Releases([string]$Repo) {
  $results=@()
  for($page=1;$page -le 100;$page++){
    # R2.1: Invoke-RestMethod emits the JSON array as ONE object; ForEach-Object unrolls it so $batch holds releases
    $batch=@(Fetch-Json "https://api.github.com/repos/$Repo/releases?per_page=100&page=$page" | ForEach-Object { $_ })
    if($batch.Count -eq 0){break}
    $results+=@($batch)
    if($batch.Count -lt 100){break}
    if($page -eq 100){throw 'Release数量超过当前扫描上限，需升级分页逻辑'}
  }
  return $results
}
function Download-Manifest([object]$release,[string]$cache) {
  $a=@($release.assets | Where-Object {$_.name -eq 'delivery-manifest.json'})
  if($a.Count -ne 1){throw "Release缺少唯一清单: $($release.tag_name)"}
  $out=Join-Path $cache ("manifest-"+[string]$release.tag_name+".json")
  $temp=$out+'.partial'
  $url=[string]$a[0].browser_download_url
  if($url -notmatch '^https://github\.com/xuelingshang/opc-video-deliveries/releases/download/') {throw '交付清单URL异常'}
  & curl.exe -f -L -sS --retry 5 --retry-delay 2 -o $temp $url
  if($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $temp -PathType Leaf)) {throw '交付清单下载失败'}
  Move-Item -LiteralPath $temp -Destination $out -Force
  $obj=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json
  if([int]$obj.schema_version -ne 1 -or [string]$obj.repository -ne 'xuelingshang/opc-video-deliveries'){
    throw '清单格式或仓库标识异常'
  }
  if([string]$obj.release_tag -ne [string]$release.tag_name){throw '清单批次与Release不一致'}
  $scheduled=Release-Day ([string]$release.tag_name)
  if([string]$obj.delivery_date -ne $scheduled){throw '清单计划交付日期与Release标签不一致'}
  try { [void][datetime]::ParseExact($scheduled,'yyyy-MM-dd',[cultureinfo]::InvariantCulture) }catch { throw "交付日期格式无效: $scheduled" }
  return $obj
}
function Write-Receipt([string]$path,[string]$archiveSha,$files,[string]$releaseTag){
  $record=@{archive_sha256=$archiveSha;release_tag=$releaseTag;files=@($files);verified_at=(Get-Date).ToString('o')}
  $temp=$path+'.tmp'
  $record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temp -Encoding UTF8
  Move-Item -LiteralPath $temp -Destination $path -Force
}

try {
  if(-not (Get-Command curl.exe -ErrorAction SilentlyContinue)){throw '找不到Windows curl.exe'}
  if($Repository -ne 'xuelingshang/opc-video-deliveries'){throw '工具仅支持指定的公开交付仓库'}
  if($Date){
    try{$Date=([datetime]::ParseExact($Date,'yyyy-MM-dd',[cultureinfo]::InvariantCulture)).ToString('yyyy-MM-dd')}
    catch{throw '指定日期须为 YYYY-MM-DD'}
  }
  $today=(Get-Date).ToString('yyyy-MM-dd')
  $base=if(Test-Path 'D:\'){'D:\OPC-DELIVERIES'}else{Join-Path $env:USERPROFILE 'Downloads\OPC-DELIVERIES'}
  $cache=Join-Path $base '_DOWNLOAD-CACHE'
  $receipts=Join-Path $base '_已完成记录'
  New-Item -ItemType Directory -Path $base,$cache,$receipts -Force | Out-Null
  Write-Host '连接公开GitHub，扫描全部交付批次（无需登录或令牌）...'
  $releases=@(Get-Releases $Repository)
  $scheduled=@()
  $sandbox=0
  foreach($r in $releases){
    if($r.draft -or $r.prerelease){continue}
    $deliveryDay=Release-Day ([string]$r.tag_name)
    if(-not $deliveryDay){continue}
    if($Tag -and [string]$r.tag_name -ne $Tag){continue}
    if($Date -and $deliveryDay -ne $Date){continue}
    # R2.2: dates are archive labels, not download permission; a published formal batch is downloaded
    # even before its delivery date. Only the TEST sandbox date needs an explicit -Date/-Tag.
    if(-not $Date -and -not $Tag -and $deliveryDay -eq '2099-12-31'){$sandbox++;continue}
    $scheduled+=@{day=$deliveryDay;tag=[string]$r.tag_name;release=$r}
  }
  $scheduled=@($scheduled | Sort-Object day,tag)
  if($scheduled.Count -eq 0){
    Write-Host "没有新的交付视频（尚无已公开的正式交付批次）。"
    Start-Process explorer.exe -ArgumentList "`"$base`""
    exit 0
  }
  $downloaded=0; $skipped=0; $failed=0; $total=0
  $seen=@{}
  foreach($item in $scheduled){
    $tag=[string]$item.tag
    $day=[string]$item.day
    $release=$item.release
    Write-Host "`n===== $day / $tag ====="
    try{$manifest=Download-Manifest $release $cache}
    catch {Write-Host ("  清单失败: "+$_.Exception.Message) -ForegroundColor Red;$failed++;continue}
    $dayPath=Join-Path $base $day
    New-Item -ItemType Directory -Path $dayPath -Force | Out-Null
    foreach($v in @($manifest.videos)){
      $total++
      $id=[string]$v.video_id
      try{
        if($id -notmatch '^[A-Z0-9]+(?:-[A-Z0-9]+)*$'){throw "视频编号异常: $id"}
        if($seen.ContainsKey($id) -and $seen[$id] -ne [string]$v.sha256){throw "不同批次重复视频ID且文件不一致: $id"}
        $seen[$id]=[string]$v.sha256
        $assetName=[string]$v.asset_name
        if($assetName -notmatch '^[A-Za-z0-9._-]+\.zip$'){throw '压缩包文件名异常'}
        $target=Join-Path $dayPath $id
        $receipt=Join-Path $receipts "$id.json"
        $files=@($v.files)
        if($files.Count -ne 4){throw '交付包应当恰有完整MP4、封面、文案、字幕4种文件'}
        $names=@($files | ForEach-Object {[string]$_.name})
        if(@($names | Sort-Object -Unique).Count -ne 4){throw '清单有重复文件名'}
        if((Test-Path -LiteralPath $receipt -PathType Leaf)){
          try {
            $rec=Get-Content -LiteralPath $receipt -Raw -Encoding UTF8 | ConvertFrom-Json
            if([string]$rec.archive_sha256 -ne [string]$v.sha256){throw "同编号交付包已变更，禁止自动覆盖: $id"}
            if((Test-Path -LiteralPath $target -PathType Container) -and (Is-Verified $target $files $false)){
              Write-Host "[$id] 已下载且大小验证通过，跳过";$skipped++;continue
            }
          } catch {
            if($_.Exception.Message -like '*禁止自动覆盖*'){throw}
          }
        }
        if((Test-Path -LiteralPath $target -PathType Container) -and (Is-Verified $target $files $true)){
          Write-Host "[$id] 原有文件SHA256通过，跳过"
          Write-Receipt $receipt ([string]$v.sha256) $files $tag
          $skipped++;continue
        }
        $assets=@($release.assets | Where-Object {$_.name -eq $assetName})
        if($assets.Count -ne 1){throw "Release缺少对应压缩包: $assetName"}
        $asset=$assets[0]
        if([long]$asset.size -ne [long]$v.size_bytes){throw '云端压缩包大小不符'}
        $zipfile=Join-Path $cache ("$tag--$assetName")
        Write-Host "[$id] 正在获取交付包..."
        Download-File ([string]$asset.browser_download_url) $zipfile ([string]$v.sha256) ([long]$v.size_bytes)
        $temp=Join-Path $dayPath "_extract_$id"
        if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Recurse -Force}
        New-Item -ItemType Directory -Path $temp -Force | Out-Null
        Add-Type -AssemblyName System.IO.Compression
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip=[System.IO.Compression.ZipFile]::OpenRead($zipfile)
        try{
          foreach($entry in $zip.Entries){
            $e=$entry.FullName.Replace('\','/')
            if($e.StartsWith('/') -or $e.Contains('../') -or $e -match '^([A-Za-z]:|\.\.|/)' -or -not $e.StartsWith("$id/")){
              throw "ZIP路径不安全: $e"
            }
          }
        }finally{$zip.Dispose()}
        Expand-Archive -LiteralPath $zipfile -DestinationPath $temp -Force
        $inner=Join-Path $temp $id
        if(-not (Is-Verified $inner $files $true)){throw '解压文件未通过SHA256校验'}
        if(Test-Path -LiteralPath $target -PathType Container){
          throw "目标位置已有不同内容，拒绝自动覆盖: $target"
        }
        Move-Item -LiteralPath $inner -Destination $target
        Remove-Item -LiteralPath $temp -Recurse -Force
        Write-Receipt $receipt ([string]$v.sha256) $files $tag
        Write-Host "[$id] MP4＋封面＋文案＋字幕：交付完成"
        $downloaded++
      } catch {
        Write-Host ("[$id] 失败: "+$_.Exception.Message) -ForegroundColor Red
        $failed++
      }
    }
  }
  Write-Host "`n===== 完成 ====="
  Write-Host "交付批次: $($scheduled.Count) | 检查视频: $total | 新下载: $downloaded | 跳过已下载: $skipped | 失败: $failed"
  if($downloaded -eq 0 -and $failed -eq 0){Write-Host "没有新的交付视频，已有视频均已下载并校验。"}
  Write-Host "位置: $base"
  Start-Process explorer.exe -ArgumentList "`"$base`""
  if($failed -gt 0){exit 2}else{exit 0}
}catch{
  Write-Host ("未完成: "+$_.Exception.Message) -ForegroundColor Red
  exit 1
}
