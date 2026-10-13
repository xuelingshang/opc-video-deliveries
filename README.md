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

继续使用 Founder 给的 **R2 下载工具**，双击即可，它会把所有已到期的批次整理到
`D:\OPC-DELIVERIES\YYYY-MM-DD\VIDEO-ID\`，已校验过的视频不会重复下载。

本仓库 `tool/` 里另有一个按同一格式读取 Release 的兼容版下载器（`OPC-Download.cmd`），
与旧工具的逐字段核对和尚待实测的项目见 [docs/R2-COMPATIBILITY.md](docs/R2-COMPATIBILITY.md)。
在 Founder 用真实测试 Release 实测之前，请以旧 R2 工具为准。

## 当前状态

- 尚无已发布的交付批次。
- 历史成片要在素材公开许可和 Founder 审片批准都确认后才会发布，规则见 [docs/PUBLISHING.md](docs/PUBLISHING.md)。

## 仓库内容

| 目录 | 内容 |
|---|---|
| `tool/` | 兼容版 Windows 下载器（PowerShell 5.1/7，双击 `.cmd`） |
| `publisher/` | 打包（可重复生成同一 SHA256）与 Release 发布器；原创测试样片生成脚本 |
| `docs/workflow-templates/` | Founder 手动启用的测试批次发布工作流模板 |
| `tests/` | 本地模拟 GitHub 的场景测试（不代表真实 Release 或 Windows 实测） |
| `docs/` | 发布流程、公开 Gate、R2 兼容核对 |

大文件只放在 Release 资产里，不进入 Git 历史。
