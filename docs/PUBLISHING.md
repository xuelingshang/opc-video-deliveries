# 发布流程与公开 Gate

## 公开 Gate（自动，2026-10-13 起；不再要求 Founder 逐条观看）

`publisher/opc_gate.py` 按记录逐条判定，三项都为 JSON `true` 才公开，其余进入私有待交付（PRIVATE_PENDING，并写明缺哪一项）：

1. `machine_qa_pass`：自动技术 QA 通过（完整 MP4 可恢复、SHA256 一致、封面/文案/字幕齐全、机器 QA PASS）。
2. `rights_confirmed`：素材公开再分发权利已确认（公开仓库权限 ≠ 第三方素材公开许可）。
3. `public_distribution_approved`：该内容允许公开分发。

`founder_visual_pass` 不再参与判定。Gate 从不把任何字段改为 true；权利未核实的内容不得伪造批准，也不得用 `--confirm-public-gate` 手动绕过——该参数只由 `opc_gate.py` 在判定通过后传给 `opc_publish.py`。

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

## 每日 Release（2026-10-14 起）

- 每个交付日期只有一个 Release：`delivery-YYYY-MM-DD-01`。任何工位、任何账号当天（或提前为某日）完成的视频都**追加**进去，不再新建 `-02`、`-03`。
- 统一入口 `publisher/opc_daily.py`：
  - `--pkg 目录…`：追加 `opc_pack.py` 打好的包；`--from-release TAG --delete-source`：把旧的同日批次并入当天 Release，全部远端校验通过后再删除旧草稿。
  - 同名同 SHA256 跳过；同名或同编号但 SHA256 不同报 CONFLICT，不覆盖；原有 ZIP 与清单记录全部保留，清单为“原记录 + 新条目”。
  - 先上传并逐个校验 ZIP，最后替换清单；若清单在此期间被别的写入者改过，本次停止，重跑即可合并。失败后重跑会跳过已校验文件、续传其余文件。
  - `--keep-draft` 只上传到草稿，当天 Release 已公开时拒绝（未授权内容不会被暴露）；公开只经 `opc_gate.py --publish`（它现在调用 `opc_daily.py --confirm-public-gate`）。
  - GitHub 限制：每个 Release 最多 1000 个附件，单个附件 < 2 GiB（脚本检查）。
- `opc_publish.py` 保持原有用法；但若当天 `-01` 已存在，它不再新开 `-02`，而是报错提示改用 `opc_daily.py`（沙盒日期 2099-12-31 除外）。
- 离线测试：`python3 tests/run_daily_tests.py --work DIR`（合并、跳过、冲突、续传、旧流程拒开 -02、已公开拒收草稿内容）。
