# 公开交付 R2 接力测试报告（2026-10-13，Claude B）

## 1. 代码恢复状态

| 项目 | 结果 |
|---|---|
| C 的 Git bundle | `git bundle verify` 通过；唯一引用 `claude/bold-cori-m6fzje` → `edf4a76`，父提交为本仓库 `8afb0ac` |
| C 的源码 ZIP | 与 bundle 中 `edf4a76` 的文件树逐字节一致 |
| 原版 R2 ZIP | 11 个纯文本文件，无二进制、无路径穿越、无令牌；SHA256 见 `r2-original/README.md` |
| 恢复方式 | `edf4a76` 原样快进到 `claude/great-allen-zms314`，作者、时间、内容均未改动 |

## 2. 实际分支与提交

| 提交 | 内容 |
|---|---|
| `edf4a76` | Claude C 原提交（恢复） |
| `7aa54bf` | 发布器对齐原版 R2、部署 TEST 工作流、原版工具存档、R2.1 修正、测试 |
| `2e12c50` | 合并 [PR #1](https://github.com/xuelingshang/opc-video-deliveries/pull/1) 到 `main` |

## 3. GitHub 权限状态

| 能力 | 结果 |
|---|---|
| 读取公开仓库 `xuelingshang/opc-video-deliveries` | 可以 |
| 推送工作分支（含 `.github/workflows/`） | 可以（C 当时 403；本会话 GitHub App 授权已可写） |
| 建 PR / 合并到 `main` | 可以 |
| 触发 `workflow_dispatch` | 可以 |
| 本会话直接创建/删除 Release | 未尝试；改用 Actions + `GITHUB_TOKEN`（`contents: write`），未使用任何个人令牌 |
| 007 私有来源仓库 `xuelingshang/opc-auto-batch-007-five-model-media` | 账号可见（可推送），**未接入本会话**；本轮不发布任何 007 内容，故未读取 |
| 仓库 Settings | 本轮无需 Founder 修改（工作流权限默认已允许 `contents: write`） |

## 4. 原版 R2 兼容性

详见 [R2-COMPATIBILITY.md](R2-COMPATIBILITY.md)。要点：

- 清单字段、顺序、`files[]` 与原版 `prepare_release.py` 完全一致（同一素材实测对比）。
- **原版 `DOWNLOAD.ps1` 缺陷**：仓库出现第 2 个 Release 起，所有批次被当作草稿跳过，并提示“没有本次到期需要检查的批次”（退出码 0）。
  一行修正见 [`r2.1-patch/`](../r2.1-patch/README.md)。

本地模拟（PowerShell 7.4.6 / Linux，工具字节未改）：

| 测试 | 原版 R2 | R2.1 |
|---|---|---|
| `tests/run_r2_tool_tests.py`（首批、重复跳过、同日多批、提前交付、迟交补齐、断点续传、TEST 沙盒隔离、篡改拒绝覆盖、去重） | 8/15（失败全部在 ≥2 个 Release 时） | 15/15 |
| `tests/run_publisher_tests.py`（批准 Gate、沙盒日期、不覆盖、草稿续传、清理只删 TEST） | — | 13/13 |
| `tests/run_sim_tests.py`（C 的兼容版下载器，不分发） | — | 13/13 |

## 5. 真实 TEST Release（GitHub Actions）

| 项目 | 结果 |
|---|---|
| 发布运行 | [Actions run 38412451484](https://github.com/xuelingshang/opc-video-deliveries/actions/runs/38412451484)：成功（草稿 → 上传 → 校验 digest → 发布 → 匿名完整下载核验） |
| Release | `https://github.com/xuelingshang/opc-video-deliveries/releases/tag/delivery-2099-12-31-01`（已按流程删除，现为 404） |
| 标题 | `[TEST] OPC 交付链路测试 2099-12-31 第01批（非正式视频）`，非预发布、未设为 latest |
| 资产 | `TEST-0001-DELIVERY.zip` 5,131,148 B，sha256 `a24226af…2049c`；`delivery-manifest.json` 1,086 B |
| 匿名访问 | 未登录请求 Release 页面 HTTP 200；匿名下载清单与 ZIP 成功 |
| 清单 | `schema_version` 1，`repository`/`delivery_date`/`release_tag`/`videos` 与原版协议一致，`files[]` 仅 `name`/`size_bytes`/`sha256` |
| 内容 | 原创测试样片：程序生成测试图案 + 440 Hz 正弦音，12 秒 1920×1080 H.264/AAC；画面、封面、文案、字幕均标注“测试 / TEST ONLY / 非正式视频”，无第三方素材 |

### 原版 R2 工具对真实 Release 的下载（未改工具；Linux 上 PowerShell 7，`curl.exe` 指向系统 curl）

| 运行 | 结果 |
|---|---|
| 默认一键（今天 2026-10-13） | 不下载 TEST：“没有本次到期需要检查的批次。今天: 2026-10-13；提前交付批次: 1”，退出 0 |
| `-Date 2099-12-31` | 下载并核验：“MP4＋封面＋文案＋字幕：交付完成”，退出 0 |
| 再次 `-Date 2099-12-31` | “已下载且大小验证通过，跳过”，退出 0 |
| 目录 | `OPC-DELIVERIES\2099-12-31\TEST-0001\` 下恰好 `TEST-0001.mp4`、`cover.jpg`、`weibo.txt`、`subtitle.srt`，4 个 SHA256 与清单一致 |

### 清理

[Actions run 38412655860](https://github.com/xuelingshang/opc-video-deliveries/actions/runs/38412655860)：成功。之后匿名 API 返回 Release 列表 `[]`、标签列表 `[]`，原 Release 页面 404。正式交付列表无测试污染。

## 6. 正式历史成片

未发布任何正式视频：005 VAR-011～030 排除；007-051～055、061～065 仍待授权与 Founder 审片；25 条历史私有打包产物未上传。未制作 007 剩余内容、未改 008、未调用付费 TTS。

## 7. Windows 尚待验收（Founder Gate）

本环境无法运行 Windows PowerShell 5.1，以下未验证：

1. 原版 R2 在 5.1 上的多 Release 缺陷是否同样出现；R2.1 修正在 5.1 上是否生效。
2. `.cmd` 文件开头的 UTF-8 BOM 是否在第一行显示“'﻿@echo' 不是内部或外部命令”（预计只影响显示）。
3. 控制台中文显示、`curl.exe`、`Expand-Archive`、D 盘输出路径。

## 8. Founder 下一步

1. **Windows 验收（约 10 分钟）**：GitHub 仓库 → Actions → “TEST delivery release” → Run workflow，`action=publish`，`video_id=TEST-0002`（每轮换新编号）。
   在 Windows 电脑上用朋友的 R2 文件夹：先双击 `01-双击下载最新视频.cmd`（应不下载 TEST），再双击 `02-下载指定日期.cmd` 输入 `2099-12-31`（应下载到 `D:\OPC-DELIVERIES\2099-12-31\TEST-0002\` 四个文件），再输入一次（应跳过）。拍下黑窗口结果。
2. **多批次验收**：再运行一次 publish，`video_id=TEST-0003`（此时有 2 个 Release）。原版工具输入 `2099-12-31`，预计显示“没有本次到期需要检查的批次”（证实缺陷）；
   把 `DOWNLOAD.ps1` 换成 `r2.1-patch/DOWNLOAD.ps1` 后重试，应下载 TEST-0003 并跳过 TEST-0002。
3. 验收后运行 `action=cleanup`，确认 Releases 页为空；删除 Windows 上的 `D:\OPC-DELIVERIES\2099-12-31` 和 `_已完成记录\TEST-*.json`。
4. 决定是否把 R2.1 的 `DOWNLOAD.ps1` 发给朋友（**正式交付第 2 批之前必须完成**，否则朋友端会静默收不到）。
5. 正式视频逐条完成授权确认与审片批准后，再安排在私有执行环境中发布（不在本公开仓库的 Actions 中运行）。
