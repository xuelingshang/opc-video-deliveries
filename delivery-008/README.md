# delivery-008 · AUTO-BATCH-008 交付入口（所有者控制）

把 008 各工位（B、1、2）的成片追加到 **008 专属草稿** `delivery-008-YYYY-MM-DD-01`「AUTO-BATCH-008｜YYYY-MM-DD交付」。
只建草稿、只追加，没有任何发布路径；不读写 007 的 `delivery-YYYY-MM-DD-01`，不碰 007 的工作流。

## 信任边界

| 角色 | 能做什么 | 不能做什么 |
|---|---|---|
| 生产工位（008 私有仓库的 `claude/008-*` 分支） | 提交交付请求 `DELIVERY-008/requests/<日期>-<工位>.json` 和其中列出的 MP4 字节分片、封面、文案、字幕、STATUS.json | 没有任何能写 opc-video-deliveries 的令牌；改自己分支上的工作流或脚本也拿不到 |
| 本工作流（opc-video-deliveries 默认分支上的 `.github/workflows/delivery-008-draft.yml` + 本目录） | 用本仓库自己的短期 `GITHUB_TOKEN` 建草稿、上传、核对、推锁分支 `delivery-008-lock` | 不执行 008 仓库里的任何代码；不发布；不改 007 |
| 读取令牌 `OPC008_READ_TOKEN`（环境 `delivery-008` 的密钥） | 只读 008 仓库内容 | 只在第 2 步交给 git；环境限定 `main`，其他分支的工作流拿不到 |

每一步只拿它需要的凭据：

1. **state**（`GITHUB_TOKEN`）：读出 008 草稿及其清单已记录的视频。
2. **fetch**（只读令牌，经 `GIT_CONFIG_*` 交给 git，不落盘）：克隆 008 仓库的树（不含文件内容），按 `STATIONS.json` 只读取**各工位自己分支**上的请求，
   校验后只取出**尚未交付**视频的文件。逐个 blob 复制：只接受普通文件（软链接、子模块一律拒绝），路径只由校验过的部分拼成，不检出、不执行。
3. **rebuild**（无凭据）：拼接分片，逐片与整片核对 SHA256，用 `vendor/opc_pack.py` 确定性打包，ZIP 必须与请求记录的大小和 SHA256 一致。
4. **deliver**（`GITHUB_TOKEN`）：加锁 → 按请求逐个追加 → 核对远端大小与 SHA256 → 解锁。

保留的既有能力（离线测试覆盖）：008 独立草稿、绝不写 007、三工位各自提交请求、串行追加（工作流 `concurrency` + git 锁）、
同名同 SHA256 跳过、同名不同 SHA256 拒绝覆盖、MP4/ZIP/远端 SHA256 校验；素材审批状态（RIGHTS UNVERIFIED、未发布）不变。

新增的数据规则：工位只能交付 `STATIONS.json` 里自己的编号段（B 066–075，2 号 086–095；1 号未登记时可用不属于其他工位的编号）；
两个请求对同一视频给出不同 ZIP 时两者都不交付；草稿已记录同名不同 SHA256 时报 CONFLICT，不下载、不覆盖。
任何被拒项都会让本次运行标红（退出码 1），其余正常项照常交付。

本仓库公开，Actions 日志也公开：日志只写请求文件名（日期 + 工位）、提交号、视频编号、大小、SHA256 和被拒原因（可能引用请求里写的目录路径，
如 `OUTPUT/M350/008-066`），不写标题、文案、分支名或媒体内容，也不上传 artifact。草稿 Release 只有有写权限的人能看到。

## 文件

| 文件 | 作用 |
|---|---|
| `run_008.py` | 工作流驱动（state / fetch / rebuild / deliver） |
| `STATIONS.json` | 工位 → 分支规则与编号段（只由仓库所有者修改） |
| `opc_daily_008.py` | 建草稿与串行追加（由 007 的 `publisher/opc_daily.py`@0803e424 派生，只允许 008 标签与 008 编号） |
| `lock008.py` | git 快进锁（分支 `delivery-008-lock`） |
| `rebuild_from_parts.py` | 分片 → ZIP 重建与核对；同一套路径规则也用于 008 仓库的只读请求检查 |
| `deliver_008.py` | 手动路径：有本仓库写权限的人在本仓库克隆里运行，与工作流共用同一把锁 |
| `vendor/` | `opc_pack.py`、`opc_publish.py`，与 opc-video-deliveries@0803e424 逐字节相同 |
| `tests/run_tests_008.py` | 离线测试（假 `gh` + 本地 git 仓库，不访问 GitHub） |

```bash
python3 delivery-008/tests/run_tests_008.py --work /tmp/t008      # 需要 ffmpeg、git、PyYAML
```

## 部署（Founder）

1. 合并本目录与 `.github/workflows/delivery-008-draft.yml` 到 `main`。
2. 生成只读令牌：<https://github.com/settings/personal-access-tokens/new>
   Resource owner `xuelingshang` → Repository access **Only select repositories** → `opc-auto-batch-008-new-model-media` →
   Repository permissions **Contents: Read-only**（Metadata 只读自动带上），其他全部 No access；有效期按需要（例如 90 天）。
3. 建环境并放密钥：<https://github.com/xuelingshang/opc-video-deliveries/settings/environments/new>
   名称 `delivery-008` → Deployment branches and tags 选 **Selected branches and tags** → 添加 `main` →
   Environment secrets → Add secret：名称 `OPC008_READ_TOKEN`，值为上一步的令牌。
4. 保护默认分支（让受信代码只由所有者修改）：<https://github.com/xuelingshang/opc-video-deliveries/settings/rules/new?target=branch>
   Enforcement **Active** → Bypass list 加 **Repository admin** → Target branches **Include default branch** →
   勾选 **Restrict updates**、**Restrict deletions**、**Block force pushes** → Create。
5. 试运行：<https://github.com/xuelingshang/opc-video-deliveries/actions/workflows/delivery-008-draft.yml> → Run workflow →
   先勾 `dry_run`，看日志无误后再不勾运行一次。之后每小时 23 分自动运行一次。

不需要、也不应该在 008 仓库放任何交付令牌。工位 1 的分支若不是 `claude/008-1-*`，或要固定它的编号段，只改本仓库 `main` 上的 `STATIONS.json`。

注意：
- 第 4 步的规则集挡住的是没有管理员权限的写入者。以 Founder 账号身份工作的会话（例如挂载了本仓库的 Claude 会话）仍有所有者权限，
  所以**不要把本仓库挂载给生产工位的会话**；工位只需要 008 仓库。
- 只读令牌到期后在第 3 步的环境密钥里替换即可；令牌失效时第 2 步报错，不会写入任何东西。
- GitHub 会在公开仓库 60 天无活动后停用定时任务；届时在 Actions 页面重新启用，或手动 Run workflow。

说明：`docs/PUBLISHING.md` 规定正式**发布**不在本仓库 Actions 中运行。本工作流不发布，只往草稿追加，且日志只含编号与校验值；
是否接受这一例外由 Founder 决定。不接受时，可改用 008 私有仓库里的环境保护工作流（日志私有），但那需要一个能写本仓库的长期令牌。
