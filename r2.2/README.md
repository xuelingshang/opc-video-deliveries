# R2.2 员工版下载器

员工只需把本文件夹（`01-双击下载全部视频.cmd`、`DOWNLOAD.ps1`、`员工使用说明.txt`）放在电脑上，双击 `01-双击下载全部视频.cmd`。
不需要 GitHub 账号、令牌、仓库地址、命令或视频编号。

## 相对 R2.1 的改动（`DOWNLOAD.ps1` 只改 4 处）

| 改动 | 原因 |
|---|---|
| 默认运行不再跳过交付日期晚于今天的批次 | 日期只是归档标签；已公开的正式批次可提前下载，仍归入其交付日期文件夹 |
| 默认运行跳过 `2099-12-31` 测试沙盒；只有 `-Date 2099-12-31` 或 `-Tag` 才下载 | TEST 不进入员工默认下载 |
| 无可下载批次、或全部已下载时提示“没有新的交付视频” | 员工能看懂 |
| 启动文件为纯 ASCII、无 BOM、CRLF | 原版 `.cmd` 带 UTF-8 BOM，cmd.exe 第一行会报错 |

保留 R2.1 的多 Release 数组展开修复；交付包结构、`D:\OPC-DELIVERIES\日期\视频编号\` 目录和 `_已完成记录` 与原版 R2 完全兼容（原版下载过的视频不会重下）。
`管理员-测试沙盒下载.cmd` 仅供 Founder 验收 TEST 样片，不发给员工。

SHA256：`DOWNLOAD.ps1` `0e3ff442763a78bc479b5caae668b7eab3f7669bf087556b3a897729b1fd6298`

## 测试

`python3 tests/run_r2_2_tests.py --pwsh <pwsh> --work <dir> --assets <pkgdir>`：16 项（多 Release、同日/跨日、提前下载、新增补齐、重复跳过、断点续传、
服务器 SHA256 不符拒收、同编号不同内容拒收且不覆盖、本地损坏拒绝覆盖、TEST 隔离、原版 R2 记录兼容、无新视频提示）。
在 Linux 的 PowerShell 7 上运行；**Windows PowerShell 5.1 尚待实测**（步骤见 docs/R2.2-ACCEPTANCE.md）。
