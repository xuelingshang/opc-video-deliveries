# OPC 视频公开交付

朋友不需要 GitHub 账号或 Token。所有交付都放在本仓库的 **Releases**，每批一个 `delivery-YYYY-MM-DD-NN`，
每条视频一个 `VIDEO-ID-DELIVERY.zip`，解压后是：

```
VIDEO-ID/
  VIDEO-ID.mp4
  cover.jpg
  weibo.txt
  subtitle.srt
```

## 朋友怎么下载

使用 Founder 给的 **R2 下载工具**，双击 `01-双击下载最新视频.cmd`，所有已到期的批次整理到
`D:\OPC-DELIVERIES\YYYY-MM-DD\VIDEO-ID\`，已校验过的视频不会重复下载。

> 注意：原版 R2 在仓库有 2 个及以上 Release 时会跳过全部批次（详见 [docs/R2-COMPATIBILITY.md](docs/R2-COMPATIBILITY.md)）。
> 正式交付开始前，请把朋友文件夹中的 `DOWNLOAD.ps1` 换成 [`r2.1-patch/DOWNLOAD.ps1`](r2.1-patch/README.md)（只改一行），并先在 Windows 上验收。

## 当前状态

- 尚无正式交付批次。`delivery-2099-12-31-NN` 是 `[TEST]` 测试批次（沙盒日期，朋友默认双击不会下载），测试后清理。
- 历史成片要在素材公开许可和 Founder 审片批准都确认后才会发布，规则见 [docs/PUBLISHING.md](docs/PUBLISHING.md)。

## 仓库内容

| 目录 | 内容 |
|---|---|
| `r2-original/` | 原版 R2 朋友端工具，逐字节保存，附来源与 SHA256 |
| `r2.1-patch/` | 原版 `DOWNLOAD.ps1` 的一行修正版（待 Founder 决定分发） |
| `publisher/` | 打包、发布（与原版 R2 清单格式一致）、TEST 清理脚本；原创测试样片生成脚本 |
| `.github/workflows/` | 仅手动触发的 TEST 批次发布 / 清理工作流 |
| `tests/` | 本地模拟 GitHub 的测试（PowerShell 7 / Linux，不代表 Windows 实测） |
| `tool/` | Claude C 的兼容版下载器，仅保留记录，不分发 |
| `docs/` | 发布流程、公开 Gate、R2 兼容核对、测试报告 |

大文件只放在 Release 资产里，不进入 Git 历史。
