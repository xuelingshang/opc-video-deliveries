# R2 协议逐字段核对

现有朋友端 R2 下载工具是 Founder 从外部获得的独立 ZIP，不在任何 OPC 仓库里，本仓库无法读取它的源码。
下表把 Founder 2026-10-13 给出的 R2 规格与本仓库发布器（`publisher/opc_publish.py`、`publisher/opc_pack.py`）
实际生成的内容逐项对照。**“已对齐”只表示与文字规格一致；在用旧 R2 工具对真实 Release 实测之前，不能声称旧工具已经可用。**

| # | R2 规格 | 本仓库生成的内容 | 状态 |
|---|---|---|---|
| 1 | 仓库 `xuelingshang/opc-video-deliveries` | 同一仓库的 Release | 已对齐 |
| 2 | Release 标签 `delivery-YYYY-MM-DD-NN` | `delivery-<计划交付日期>-<两位批次号>`；同一天第二批取下一个空号（01、02…）；已发布的标签永不改写 | 已对齐（假设 NN 从 01 起、两位数） |
| 3 | 每批包含 `delivery-manifest.json` | 每个 Release 一个同名资产，在所有 ZIP 上传并校验后**最后**上传；草稿全部校验通过才发布 | 已对齐 |
| 4 | `schema_version=1` | JSON 整数 `1` | 已对齐（假设旧工具接受整数而非字符串 `"1"`） |
| 5 | 清单含 `repository`、`delivery_date`、`release_tag`、`videos` | 同名字段，值分别为仓库全名、`YYYY-MM-DD`、Release 标签、数组 | 已对齐 |
| 5a | （规格未提） | 额外字段 `generated_at_utc`；测试批次另有 `test_only: true` | 待实测：需旧工具忽略未知字段 |
| 6 | `videos[]` 含 `video_id`、`asset_name`、`size_bytes`、`sha256`、`files` | 同名字段；`asset_name`=`VIDEO-ID-DELIVERY.zip`；`size_bytes`、`sha256` 为该 ZIP 的字节数与小写十六进制 SHA256 | 已对齐（假设 size/sha 指 ZIP 本身） |
| 7 | `files`（规格未给内部结构） | 4 个对象，顺序固定：`{"name","path","size_bytes","sha256"}`，`path` 为 ZIP 内路径 `VIDEO-ID/…` | **未知，必须用旧工具实测**；若旧工具要求字符串数组或其他键名，只需改发布器一处，ZIP 不变 |
| 8 | 每条视频独立 `VIDEO-ID-DELIVERY.zip` | 同 | 已对齐 |
| 9 | ZIP 内 `VIDEO-ID/VIDEO-ID.mp4`、`cover.jpg`、`weibo.txt`、`subtitle.srt` | 正好这 4 个条目（无目录条目），存储不压缩，固定时间戳，可重复生成同一 SHA256 | 已对齐 |
| 10 | 自动补齐所有已到期但未验证完成的批次 | 由旧工具实现；发布器保证已发布批次不变、补发批次用新批次号 | 取决于旧工具 |
| 11 | （规格未提）旧工具如何发现批次：API 列表、逐号探测或其他 | 发布为普通 Release（非草稿、非预发布）；API 列表与 `releases/download/<tag>/delivery-manifest.json` 两种方式都能找到 | 待实测 |

## 本仓库的下载器（`tool/`）

`tool/opc-download.ps1` 是按上表读取同一批 Release 的**兼容版**，不是旧 R2 工具本身：

- 发现批次：先用 GitHub 匿名 API 列出 Release；API 不可用时按日期逐批探测 `releases/download/delivery-日期-NN/delivery-manifest.json`。
- 校验 `schema_version==1`、`repository`、`release_tag`、`delivery_date` 与标签一致；`asset_name` 必须是 `VIDEO-ID-DELIVERY.zip`；ZIP 内只允许那 4 个文件。
- `files` 同时接受对象（`path`/`name` + `size_bytes` + `sha256`）和纯文件名两种写法。
- 编号以 `TEST-` 开头的测试样片默认不下载；`OPC-Download-TEST.cmd`（`-IncludeTest`）会把它们单独放到 `_TEST\日期\编号`。

旧 R2 工具与兼容版可以并存，读的是同一批 Release。**在旧工具对真实测试 Release 实测通过前，请不要让朋友更换工具，也不要据此认定旧工具可用。**
如果实测发现旧工具与第 7 项（或其他项）不兼容，二选一：调整发布器的 `files` 写法以适配旧工具（推荐，ZIP 不变），
或由 Founder 让朋友一次性换成本仓库的兼容版下载器。

## 测试批次与正式批次的区分

测试 Release 的标签也必须是 `delivery-YYYY-MM-DD-NN`，否则测不到旧工具。为避免混入正式交付：

- 测试样片编号固定以 `TEST-` 开头，画面、封面、文案、字幕都写明“测试 / 非正式视频”；Release 标题以 `[TEST]` 开头。
- 测试批次只含 TEST 编号，正式批次不允许出现 TEST 编号（发布器强制检查）。
- 旧 R2 工具若不区分测试批次，会把 `TEST-0001` 下载到 `D:\OPC-DELIVERIES\<日期>\TEST-0001`。建议 Founder 先在自己电脑上实测，确认后再通知朋友。
