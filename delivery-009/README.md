# delivery-009 · AUTO-BATCH-009 交付入口（所有者控制）

把 009 各工位（Cloud2、3、4、5、A、C）已经完成的内部成片，按 008 的下载方式放进 **009 专属草稿**
`delivery-009-2026-10-18-01`「AUTO-BATCH-009｜2026-10-18交付」：**一条视频一个完整的 `009-NNN-DELIVERY.zip`**，
Founder 在 Release 页面直接点击下载，不用合并分片、不用运行恢复脚本。

只建草稿、只追加，没有发布路径；不碰 007、008 的 Release、工作流和锁分支（`delivery-008/` 与 `delivery-008-draft.yml` 一字未改）。

## 和 008 的区别

008 的工位要额外提交交付请求 `DELIVERY-008/requests/*.json`；009 的工位已经把每条成片的 ZIP 按字节分片、连同清单提交在自己的分支上，
所以本入口**直接读取各工位分支上的现有分片和清单**，不需要工位再做任何事：

| 工位 | 分支 | 编号段 | 读取的清单（按 `SOURCES.json` 的 `manifests` 顺序取第一个存在的） |
|---|---|---|---|
| Cloud2 | `claude/009-2-001-011` | 001–011 | `delivery/009-NNN.zip.manifest.json` |
| Cloud3 | `claude/009-3-013-036` | 013–036 | `DELIVERY/DELIVERY_MANIFEST.json` |
| Cloud4 | `claude/009-4-043-077` | 043–077 | `DELIVERY/DELIVERY_MANIFEST.json` |
| Cloud5 | `claude/009-5-081-107` | 081–107 | `R2/DELIVERY/DELIVERY_MANIFEST.json`（最新 R2 优先，R1 保留不动） |
| CloudA | `claude/009-a-121-134` | 121–134 | `delivery/009-NNN.zip.manifest.json` |
| CloudC | `claude/009-c-152-183` | 152–183 | `DELIVERY-PARTS/PARTS.json` |

每条视频的处理（`restore_009.py`，不重新配音、不重新剪辑、不重新渲染、不下载 RAW）：

1. 按清单顺序拼接分片：每一片、整包的字节数和 SHA256 都必须与清单一致；
2. ZIP 通过 CRC 检查，且只含 `ROOT/ROOT.mp4`、`ROOT/cover.jpg`、`ROOT/weibo.txt`、`ROOT/subtitle.srt`
   （ROOT 为 `009-NNN`，或后续轮次的 `009-NNN-R2`）；清单记录的每个成员哈希都必须一致，且必须记录了 MP4 的哈希；
3. MP4 必须是 1920×1080 并带音轨（ffprobe）；
4. 把这四个文件逐字节取出，用与 008 相同的 `vendor/opc_pack.py` 存成标准布局 `009-NNN/009-NNN.mp4 …` 的
   `009-NNN-DELIVERY.zip`（不压缩、固定时间戳，结果可复现），并再次确认 MP4 字节不变。
   CloudC 的 ZIP 本来就是这种布局，所以字节完全相同；其他工位只差 ZIP 目录头，Cloud5 的 `009-NNN-R2/` 文件夹统一改为 `009-NNN/`。

各工位自己的恢复校验记录（`RESTORE_VERIFICATION.json`、`RESTORE-TEST.json`、清单内的 `verification`、
`STATUS.json` 的 `restore_verified` / `PACKAGED_RESTORE_VERIFIED`）会被找出并写进记录；记录写明“未通过”的视频不交付。

草稿上除了各条 ZIP 和 `delivery-manifest.json`（R2 schema_version 1，与 008 相同），还有 `delivery-009-records.json`：
逐条记录来源工位、分支、提交、工位 ZIP 的大小与 SHA256、MP4 SHA256，以及工位 `STATUS.json` 中**原样**抄录的事实核验、
版权（RIGHTS UNVERIFIED）和内部审片状态；`public_release_authorized` 一律为 `false`。Founder 本轮接受现有制作质量，不代表公开发布授权。

## 信任边界（与 008 相同）

| 角色 | 能做什么 | 不能做什么 |
|---|---|---|
| 生产工位（009 私有仓库的各工位分支） | 在自己分支提交分片、清单、STATUS | 没有任何能写 opc-video-deliveries 的令牌 |
| 本工作流（默认分支上的 `.github/workflows/delivery-009-draft.yml` + 本目录） | 用本仓库自己的短期 `GITHUB_TOKEN` 建 009 草稿、上传、核对、推锁分支 `delivery-009-lock` | 不执行 009 仓库里的任何代码；不发布；不碰 007、008 |
| 读取令牌 `OPC009_READ_TOKEN`（环境 `delivery-009` 的密钥） | 只读 009 仓库内容 | 只在第 2 步交给 git；环境限定 `main` |

1. **state**（`GITHUB_TOKEN`）：读出 009 草稿已记录的视频；
2. **fetch**（只读令牌，经 `GIT_CONFIG_*` 交给 git，不落盘）：无内容克隆，只按 `SOURCES.json` 读各工位**自己分支**上自己编号段内的目录，
   逐个 blob 复制清单、分片和状态文件（只接受普通文件，路径只由校验过的部分拼成，不检出、不执行）；
3. **rebuild**（无凭据）：上面的 1–4 步；每条做完就删掉它的分片；
4. **deliver**（`GITHUB_TOKEN`）：加锁 → **逐条**追加（每条上传并核对远端大小和 SHA256 后再处理下一条）→ 解锁。

保留的规则：同名同 SHA256 跳过（重复运行不会重复上传）；同名不同 SHA256 不覆盖；某条已交付后工位分支上的 ZIP 又变了，报 `CONFLICT`，不覆盖；
两条视频的 MP4 SHA256 相同时两条都不交付；草稿上出现相同 ZIP 哈希的另一条也拒绝。任何一条被拒都会让本次运行标红（退出码 1），其他视频照常交付。

本仓库公开，Actions 日志也公开：日志只写编号、清单路径、提交号、大小、SHA256 和被拒原因，不写标题、文案或媒体内容，也不上传 artifact。
草稿 Release 只有有写权限的人能看到。

## 文件

| 文件 | 作用 |
|---|---|
| `run_009.py` | 工作流驱动（state / fetch / rebuild / deliver） |
| `SOURCES.json` | 工位 → 分支、编号段、本轮交付范围 `only_ids`、清单位置（只由仓库所有者修改） |
| `restore_009.py` | 各工位清单格式的读取、恢复、校验、标准化存放 |
| `opc_daily_009.py` | 建草稿与串行追加（由 `delivery-008/opc_daily_008.py` 派生，只允许 009 标签与 009 编号） |
| `lock009.py` | git 快进锁（分支 `delivery-009-lock`；由 `delivery-008/lock008.py` 派生，只改了名字） |
| `vendor/` | `opc_pack.py`、`opc_publish.py`，与 `delivery-008/vendor/` 逐字节相同 |
| `tests/run_tests_009.py` | 离线测试（假 `gh` + 本地 git 仓库，不访问 GitHub） |
| `TEST-REPORT-2026-10-18.md` | 本轮测试与 22 条真实成片的恢复校验结果 |

```bash
python3 delivery-009/tests/run_tests_009.py --work /tmp/t009      # 需要 ffmpeg、git、PyYAML
```

## 启用（Founder）

1. 审阅并合并本分支到 `main`（只新增 `delivery-009/` 和 `.github/workflows/delivery-009-draft.yml`）。
2. 生成只读令牌：<https://github.com/settings/personal-access-tokens/new>
   Resource owner `xuelingshang` → Repository access **Only select repositories** → `opc-auto-batch-009-10-model-media` →
   Repository permissions **Contents: Read-only**（Metadata 只读自动带上），其他全部 No access。
3. 建环境并放密钥：<https://github.com/xuelingshang/opc-video-deliveries/settings/environments/new>
   名称 `delivery-009` → Deployment branches and tags 选 **Selected branches and tags** → 添加 `main` →
   Environment secrets → `OPC009_READ_TOKEN` = 上一步的令牌。
4. 试运行：<https://github.com/xuelingshang/opc-video-deliveries/actions/workflows/delivery-009-draft.yml> → Run workflow
   （`dry_run` 默认勾选）→ 日志应列出 22 条 `DRY RUN 009-NNN`，大小与 SHA256 与测试报告一致。
5. 正式上传：再 Run workflow 一次，**取消勾选** `dry_run`。完成后草稿在
   <https://github.com/xuelingshang/opc-video-deliveries/releases>（`AUTO-BATCH-009｜2026-10-18交付`，Draft）。
6. （可选）以后新成片自动进入：Settings → Secrets and variables → Actions → Variables → 新建 `DELIVERY_009_SCHEDULE` = `on`，
   工作流即每小时 41 分自动运行一次。

## 后续新视频如何进入同一草稿

工位照现在的方式在自己分支提交 `OUTPUT/009/009-NNN/` 下的分片 + 清单 + STATUS（恢复校验通过）即可，工位不需要任何新权限。
Founder 只需在 `main` 的 `SOURCES.json` 里把编号加入 `only_ids`（或把 `only_ids` 设为 `null`，即各工位编号段内的全部成片）；
下一次运行（手动或每小时）就会把它恢复、校验、追加到同一个 `delivery-009-2026-10-18-01` 草稿，已交付的不会重复上传。
新工位或新分支：在 `stations` 里加一行（分支名 + 编号段）。某条出了新一轮（例如 R3），清单列表已把 `R3/` 放在最前；
但已交付过的编号不会被覆盖，会报 `CONFLICT`，由 Founder 决定如何处理（例如在 `SOURCES.json` 换一个新的 009 Release 标签）。

注意：GitHub 会在公开仓库 60 天无活动后停用定时任务；届时在 Actions 页面重新启用，或手动 Run workflow。
