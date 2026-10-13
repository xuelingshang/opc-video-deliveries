# 原版 R2 兼容性核对（2026-10-13，Claude B 接力）

依据：原版 R2 源码（`r2-original/01-给朋友/DOWNLOAD.ps1`，及只登记哈希的 `prepare_release.py`、`publish_release.py`），
逐字段、逐行为对照本仓库发布器 `publisher/opc_pack.py`、`publisher/opc_publish.py`。

## 一、协议字段（发布器已改为与原版完全一致）

| # | 原版 R2 | 本仓库发布器 | 结果 |
|---|---|---|---|
| 1 | 仓库 `xuelingshang/opc-video-deliveries`（工具写死，下载 URL 必须以 `https://github.com/xuelingshang/opc-video-deliveries/releases/download/` 开头） | 同一仓库的普通 Release | 一致 |
| 2 | 标签 `delivery-YYYY-MM-DD-NN`（工具接受 2～3 位 NN，也接受旧 `daily-YYYY-MM-DD`） | `delivery-日期-NN`，NN 两位，从 01 递增 | 一致 |
| 3 | 每个 Release 恰好一个 `delivery-manifest.json` | 同；所有 ZIP 上传校验后最后上传 | 一致 |
| 4 | 清单键：`schema_version`(整数 1)、`delivery_date`、`release_tag`、`repository`、`videos` | 与原版 `prepare_release.py` **键名与顺序完全相同**，已删除 C 版多出的 `generated_at_utc`、`test_only` | 一致（实测对比） |
| 5 | `videos[]`：`video_id`、`asset_name`、`size_bytes`、`sha256`（ZIP 本身） | 同 | 一致 |
| 6 | `files[]`：`name`、`size_bytes`、`sha256`，恰好 4 项、文件名不重复 | 同，已删除 C 版多出的 `path` | 一致；同一素材下与原版 `prepare_release.py` 输出的 `files[]` 逐字节相同 |
| 7 | 视频编号 `^[A-Z0-9]+(?:-[A-Z0-9]+)*$` | 打包器改用同一正则（C 版原先允许小写和点） | 一致 |
| 8 | `VIDEO-ID-DELIVERY.zip`，条目必须以 `VIDEO-ID/` 开头，解压后 SHA256 逐个核对 | 4 个条目 `VIDEO-ID/VIDEO-ID.mp4、cover.jpg、weibo.txt、subtitle.srt`，不压缩 | 一致 |
| 9 | 草稿、预发布 Release 一律跳过 | 测试与正式批次都发布为普通 Release（非预发布），否则原版工具读不到 | 一致 |
| 10 | 每个资产 < 2 GiB（原版 `prepare_release.py` 检查） | 发布器同样拒绝 ≥ 2 GiB 的 ZIP | 一致 |

## 二、行为实测（本地模拟 GitHub，PowerShell 7.4.6 / Linux，工具字节未改）

`tests/run_r2_tool_tests.py` 只替换环境（API 地址、curl.exe、explorer.exe、“今天”的日期），不改工具。

| 场景 | 原版 R2 | R2.1（改一行） |
|---|---|---|
| 首批下载，四件套同一文件夹 `…\2026-10-13\SIM-0001\`，SHA256 通过 | 通过 | 通过 |
| 重复双击自动跳过，不重下 ZIP | 通过 | 通过 |
| 同日第二批只补新视频 | **失败** | 通过 |
| 提前交付：今天不下载，交付日当天下载 | 今天不下载通过；当天下载**失败** | 通过 |
| 迟交补齐到原定日期文件夹 | **失败** | 通过 |
| 断点续传（中断后保留 `.partial`，HTTP Range 续传并校验） | **失败**（没走到下载） | 通过 |
| TEST 沙盒日期 2099-12-31：默认双击不下载；指定日期可下载、可重复跳过 | 默认不下载通过；指定日期**失败** | 通过 |
| 本地文件被改动：SHA256 不符，拒绝自动覆盖（退出码 2）；恢复后通过 | **失败** | 通过 |
| 发布器去重：已发布的视频编号不再上传 | 通过（发布器） | 通过 |

原版的全部失败都出现在仓库已有 ≥2 个 Release 之后，原因见 [`r2.1-patch/README.md`](../r2.1-patch/README.md)：
`Invoke-RestMethod` 把 Release 数组当作一个对象输出，原版把整份列表当成“一个 Release”，于是 `draft` 判断为真，所有批次被跳过，并提示“没有本次到期需要检查的批次”。

**结论：原版 R2 在仓库只有 1 个 Release 时可用；一旦有第 2 个 Release（同日第二批、第二天的批次），原版将静默失效。正式交付开始前需要朋友换用 R2.1 的 `DOWNLOAD.ps1`（Founder 决定）。**

## 三、Windows PowerShell 5.1 尚待验收（本环境无法运行 Windows）

1. 上述多 Release 缺陷在 Windows PowerShell 5.1 上是否同样出现（按 5.1 已知的 `Invoke-RestMethod` 行为，预计出现）；R2.1 修正在 5.1 上是否生效。
2. 两个 `.cmd` 以 UTF-8 BOM 开头：cmd.exe 第一行可能显示“'﻿@echo' 不是内部或外部命令”并保持回显；预计不影响下载，需确认显示。
3. `DOWNLOAD.ps1` 带 UTF-8 BOM，5.1 应按 UTF-8 读取中文；需确认控制台中文显示正常。
4. Windows 自带 `curl.exe`（Windows 10 1803 起）可用；`Expand-Archive` 解压不压缩的 ZIP；有 D 盘时输出到 `D:\OPC-DELIVERIES`。
5. `Sort-Object day,tag` 对哈希表的排序在 5.1 上可能不生效；只影响处理顺序，不影响结果。

## 四、原版的其他已知行为（不改，记录在案）

- 同一视频编号若出现在不同日期的批次里，工具会在另一个日期文件夹再下载一份（只拒绝同编号不同内容）；由发布器拒绝重复发布同一编号来保证去重。
- 已完成记录按视频编号保存在 `_已完成记录\编号.json`；同编号的新内容会被拒绝（“禁止自动覆盖”），因此修正版必须用新编号。每轮测试也应使用新的 TEST 编号。
- 测试批次无法被原版识别为测试，因此测试 Release 一律放在沙盒日期 `2099-12-31`，朋友默认双击永远不会下载它，测试完立即清理。
