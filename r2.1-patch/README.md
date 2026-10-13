# R2.1 修正：只改一行的 DOWNLOAD.ps1（待 Founder 决定是否分发）

`DOWNLOAD.ps1` = 原版 R2 `DOWNLOAD.ps1` + 下面这一处修改，其余字节不变（UTF-8 BOM、LF 均保留）。
SHA256 `8ba15e78f2f24fbe70cf5fa77097baefc8931ed953f380e0453faf70727f781e`。

```diff
-    $batch=@(Fetch-Json "https://api.github.com/repos/$Repo/releases?per_page=100&page=$page")
+    # R2.1: Invoke-RestMethod emits the JSON array as ONE object; ForEach-Object unrolls it so $batch holds releases
+    $batch=@(Fetch-Json "https://api.github.com/repos/$Repo/releases?per_page=100&page=$page" | ForEach-Object { $_ })
```

## 为什么要改

`Invoke-RestMethod` 把 GitHub 返回的 Release 数组当作**一个对象**输出（Windows PowerShell 5.1 一贯如此，PowerShell 7 实测同样如此）。
原版 `@(Fetch-Json …)` 因此得到“只含 1 个元素、该元素是整个列表”的数组，后面 `foreach($r in $releases)` 里 `$r` 是整个列表：

- 仓库只有 **1 个** Release 时碰巧正常；
- 有 **2 个及以上** Release 时，`$r.draft` 变成 `@($false,$false,…)`，在条件判断里为真，**全部批次被当成草稿跳过**，
  工具显示“没有本次到期需要检查的批次”并以 0 退出——朋友会以为没有新视频。

即：原版 R2 无法处理同日第二批、迟交补齐、多日累积等任何多 Release 情况。

## 证据（本地模拟，PowerShell 7.4.6 / Linux，未改动工具本身）

`python3 tests/run_r2_tool_tests.py --tool original` → 8/15；所有失败项都发生在仓库已有 ≥2 个 Release 之后。
`python3 tests/run_r2_tool_tests.py --tool r2.1` → 15/15（同日多批、提前交付、迟交补齐、断点续传、重复跳过、篡改拒绝覆盖、TEST 沙盒日期隔离）。

Windows PowerShell 5.1 上的行为尚需 Founder 在 Windows 电脑上确认（见 docs/R2-COMPATIBILITY.md 的验收 Gate）。

## 分发方式（Founder 决定后）

只需把朋友文件夹里的 `DOWNLOAD.ps1` 换成本文件；两个 `.cmd`、说明文字、下载目录、已完成记录全部不变，已下载的视频不会重下。
