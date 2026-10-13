# 发布流程与公开 Gate

## 公开 Gate（每条正式视频都必须全部满足才可发布）

1. 完整 MP4 可恢复，整片 SHA256 与原始记录一致（不重新渲染、不重新配音）。
2. 1920×1080 横屏封面、微博文案、中文字幕齐全。
3. 完整成片机器 QA 通过。
4. 素材的**公开再分发许可**已确认（公开仓库权限 ≠ 第三方素材公开许可）。
5. **Founder 审片批准**已记录。
6. 内容风险（车牌、人脸、他车、车型身份等）已处理或经 Founder 接受。

源记录标为 `RIGHTS_UNVERIFIED`、`INTERNAL_REVIEW_ONLY` 或 `FOUNDER_VIEWING_PENDING` 的成片不得发布。
未过 Gate 的内容只登记在私有待发布清单，媒体留在私有仓库；本公开仓库不保存待审清单、素材来源、RAW、GOLD、工程文件、日志或密钥。

## 交付日期

- 公开交付系统起点：**2026-10-13**。
- 此前完成的历史视频获批后，作为首批历史迁移内容统一登记到 `2026-10-13`，不按过去的制作日期拆分。
- 同一天的后续批次用下一个批次号（`-02`、`-03`…）；晚于交付日才补发的内容仍登记在原定交付日期，由朋友端自动补齐。

## 发布一个批次（`publisher/opc_publish.py`）

```
python3 publisher/opc_pack.py --id VIDEO-ID --mp4 … --cover … --weibo … --srt … --out work/pkg
python3 publisher/opc_publish.py --repo xuelingshang/opc-video-deliveries --date 2026-10-13 \
    --pkg work/pkg/VIDEO-ID [--pkg …] --confirm-public-gate --full-anon-verify
```

1. 本地复核每个 ZIP 的大小与 SHA256，ZIP 内只能是 `VIDEO-ID/VIDEO-ID.mp4、cover.jpg、weibo.txt、subtitle.srt`。
2. 已在任何已发布批次出现过的视频编号拒绝再次上传；已发布的标签拒绝改写。
3. 创建**草稿** Release `delivery-日期-NN` → 上传全部 ZIP → 最后上传 `delivery-manifest.json`。
4. 逐个核对资产大小与 SHA256（API digest，缺失时下载回来计算）。
5. 全部通过才把草稿改为已发布；中途失败只留下草稿（朋友看不到），重跑会接着同一草稿继续。
6. 发布后用不带任何凭据的公开地址下载清单与 ZIP 复核。

正式批次必须带 `--confirm-public-gate`；测试批次（`--test`）只允许 `TEST-` 编号，且只能用沙盒交付日期 `2099-12-31`，正式批次不得使用该日期。
清单与原版 R2 `prepare_release.py` 的键名、顺序、`files[]` 字段完全一致（见 [R2-COMPATIBILITY.md](R2-COMPATIBILITY.md)）。

## TEST 测试批次（GitHub Actions，仅手动触发）

工作流 `.github/workflows/publish-test-release.yml`（Actions → “TEST delivery release” → Run workflow）：

- `action=publish`：在云端生成原创测试样片（程序图案 + 正弦音，画面、封面、文案、字幕均标明“测试 / 非正式视频”），
  打包并发布为 `delivery-2099-12-31-NN`，标题以 `[TEST]` 开头，不设为 latest，最后用匿名地址完整下载核验。
- `action=cleanup`：只删除沙盒日期、标题 `[TEST]`、资产与清单全为 `TEST-` 的 Release 及其标签；任一目标不符合则一个都不删；
  删除后再次确认没有任何沙盒日期 Release 或 `TEST-` 资产留存。
- 只用仓库自带的 `GITHUB_TOKEN`，工作流内声明最小权限 `contents: write`；不读取私有仓库，不处理任何正式视频。
- 每轮测试换一个新的 TEST 编号（原版工具按编号记“已完成”，同编号新内容会被拒绝）。

朋友默认双击永远不会下载 2099-12-31 的批次（视为未来批次）；Founder 用 `02-下载指定日期.cmd` 输入 `2099-12-31` 专门测试。

## 正式批次

只在 Gate 通过后，由能读取私有成片仓库的执行环境运行 `opc_pack.py` + `opc_publish.py --confirm-public-gate`。
公开仓库的 Actions 日志是公开的，正式发布不在本仓库的 Actions 中运行，以免暴露内部资料。

## GitHub 权限状态（2026-10-13，Claude B 会话）

- 本会话可读取并推送本仓库分支（Claude C 会话当时推送返回 403；本会话的 GitHub App 授权已可写）。
- C 的提交 `edf4a76` 已原样恢复到 `claude/great-allen-zms314`。
- Release 创建与删除通过上述 Actions 工作流完成，不使用任何个人令牌。
