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

正式批次必须带 `--confirm-public-gate`；测试批次（`--test`）只允许 `TEST-` 编号。

## 当前环境的权限缺口（2026-10-13）

本次云端会话可以读取仓库，但创建 Release 被会话类型拦截：

```
POST /repos/xuelingshang/opc-video-deliveries/releases
→ HTTP 403 "Creating, editing, or deleting releases is not permitted for this session type."
```

同一会话推送本仓库分支也被拒绝（`git push` 与 GitHub 连接器均返回 403，提示 Claude GitHub App 对本仓库没有写权限）。
因此本会话没有创建任何 Release、标签、分支或资产，也没有用个人凭据绕过。可选的发布途径：

- **测试批次**：把本分支合并到 `main`，再把 `docs/workflow-templates/publish-test-release.yml` 复制到 `.github/workflows/`（模板默认不启用，由 Founder 决定），然后在 GitHub 网页 Actions → “Publish TEST delivery release” → Run workflow。
  该工作流在云端生成原创测试样片（程序图案 + 正弦音），用仓库自带的 `GITHUB_TOKEN` 走上述 1–6 步，不需要任何人的账号密码，也不经过 Founder 的电脑或宽带。
- **正式批次**（仅在 Gate 通过后）：需要一个能写 Release 的执行环境，并能读取私有成片仓库。
  公开仓库的 Actions 日志是公开的，正式发布不应在这里运行，以免暴露内部资料；应在私有仓库或允许写 Release 的会话中运行同一个发布器。
