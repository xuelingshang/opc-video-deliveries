# delivery-009 测试报告 · 2026-10-18

## 1. 离线测试（本地模拟，未访问 GitHub Release API）

`python3 delivery-009/tests/run_tests_009.py --work …` → **47/47 passed**

- 第 1 部分：六个工位的清单格式（Cloud2、3、4、5 R1、5 R2、A、C）各自恢复、校验并标准化存放，MP4 字节不变、结果可复现；
  分片被改、整包哈希不符、路径穿越、成员哈希不符、未记录 MP4 哈希、ZIP 内多文件、顶层目录不对、非 1080p、分片是软链接——全部拒绝。
- 第 2 部分：本地“009 仓库”+六个工位分支，端到端 state → fetch → rebuild → deliver（假 `gh`、本地锁仓库）：
  dry run 不写任何东西；一次运行只建一个 009 草稿、每条一个完整 ZIP；无清单、找不到目录、两条 MP4 相同的编号单独拒绝，其他照常交付；
  R2 优先于 R1；记录文件原样抄录工位状态且 `public_release_authorized=false`；第二次运行不重复上传；已交付视频被工位改动时报 CONFLICT 不覆盖；
  `--ids` 限定范围；其他工位编号段、未配置分支一律忽略；日志不含标题；锁分支 `delivery-009-lock` 正常加锁解锁；008 草稿不受影响。
- 第 3 部分：工作流静态检查：只读令牌只在第 2 步、`GITHUB_TOKEN` 只在第 1、4 步、第 3 步无凭据；环境 `delivery-009` 仅 `main`；
  定时运行需所有者开关 `DELIVERY_009_SCHEDULE=on`、手动运行默认 dry run；无发布、无 artifact；`delivery-008/` 与其工作流相对 `origin/main` 无改动；
  `vendor/` 与 008 逐字节相同。
- 回归：`python3 delivery-008/tests/run_tests_008.py` → 44/44 passed（008 代码未改动）。

## 2. 22 条真实成片的恢复校验（只读，未上传）

用本会话对 `xuelingshang/opc-auto-batch-009-10-model-media` 的只读访问，以与工作流相同的 `run_009.py fetch` + `rebuild` 读取各工位分支当前提交，
22/22 全部通过：分片与整包 SHA256、ZIP CRC、四文件布局、成员哈希、1920×1080 MP4 + 音轨、标准化后 MP4 字节不变。
随后用假 `gh` 把这 22 个真实 ZIP 逐条追加到模拟草稿：22 条全部上传并核对，0 个问题。

| 编号 | 工位 | 提交 | 清单 | 分片 | 工位 ZIP SHA256 | 工位恢复校验记录 | 交付 ZIP 字节 | 交付 `009-NNN-DELIVERY.zip` SHA256 |
|---|---|---|---|---|---|---|---|---|
| 009-001 | 2 | `49173ec` | `delivery/009-001.zip.manifest.json` | 3 | e8298eec6143… | STATUS.json delivery.restore_verified | 133,872,329 | `853264da715c0852e5132ab382c498cae5d42ca9bf6ca3e5c1e54982207df49c` |
| 009-002 | 2 | `49173ec` | `delivery/009-002.zip.manifest.json` | 4 | 95c3004c662e… | STATUS.json delivery.restore_verified | 180,960,013 | `996d0a812fd9222c5d0d7816047ca630aa0f54ab72b09bcc627ab465f6e3ede4` |
| 009-003 | 2 | `49173ec` | `delivery/009-003.zip.manifest.json` | 3 | bc12e9f33bdd… | STATUS.json delivery.restore_verified | 105,025,338 | `abdc09f7131e0e05f35ef1cb20db00598dd9fb6a130e2bf48fbad8816fa11c7a` |
| 009-004 | 2 | `49173ec` | `delivery/009-004.zip.manifest.json` | 3 | 462a52a4d7d7… | STATUS.json delivery.restore_verified | 139,683,811 | `cbbf2359eec62d1a226b65cb31b957aafe68ce918716734f36eb7461242cf028` |
| 009-005 | 2 | `49173ec` | `delivery/009-005.zip.manifest.json` | 3 | e805e5dd9569… | STATUS.json delivery.restore_verified | 121,714,226 | `7c7038bd54aed5818cc535474c15ac3bbeb450b263892afc5e6064e12d663437` |
| 009-021 | 3 | `c083ba3` | `DELIVERY/DELIVERY_MANIFEST.json` | 5 | 109c8ad53bfd… | STATUS.json delivery_status | 195,688,322 | `194459b3c4311f80554a4ccc690d8f07f74ef64b60decf1aa2f3834f841a6085` |
| 009-043 | 4 | `872bdac` | `DELIVERY/DELIVERY_MANIFEST.json` | 5 | a7a6f5e1ad50… | RESTORE_VERIFICATION.json | 220,913,576 | `00604194f0443f358793143d7e1a388400da1fd2742553e3ce40f12d6d29ab68` |
| 009-049 | 4 | `872bdac` | `DELIVERY/DELIVERY_MANIFEST.json` | 3 | 423af02f1241… | RESTORE_VERIFICATION.json | 147,805,709 | `93ce952320e00ddc29d735d4e0bcd689fd20b9a819debc89a8a64c035e159ac4` |
| 009-057 | 4 | `872bdac` | `DELIVERY/DELIVERY_MANIFEST.json` | 4 | 0818e16ac0b8… | RESTORE_VERIFICATION.json | 177,436,675 | `2bdd8789300873e1cbd80c29438b4cf28a50c28591a85134ac9d77140468a2f5` |
| 009-058 | 4 | `872bdac` | `DELIVERY/DELIVERY_MANIFEST.json` | 3 | 38b1a9405ada… | RESTORE_VERIFICATION.json | 149,500,702 | `a420c0f420abe538d22793ccd8b41d4944755096ffa4c38e1aa9cbeee55ce6cf` |
| 009-061 | 4 | `872bdac` | `DELIVERY/DELIVERY_MANIFEST.json` | 3 | 75f63eacab0d… | RESTORE_VERIFICATION.json | 136,396,726 | `4d930ef1b92a28e07f44ffc9a17784c12c224e621e796047d702e26c1e9b927a` |
| 009-081 | 5 | `c1d86ae` | `R2/DELIVERY/DELIVERY_MANIFEST.json` | 3 | 456e289161cd… | manifest.verification | 108,600,200 | `a38f8de49b344d4e09c16ea9dcef069c94437376468204cd70630921af295752` |
| 009-082 | 5 | `c1d86ae` | `R2/DELIVERY/DELIVERY_MANIFEST.json` | 3 | e863bb1d93f6… | manifest.verification | 115,012,305 | `f344d37edd18d58949fe3b745dc7ce88691b2cb082c0d5fb6e446e384fa881cb` |
| 009-084 | 5 | `c1d86ae` | `R2/DELIVERY/DELIVERY_MANIFEST.json` | 3 | fc47da4dbf00… | manifest.verification | 138,368,903 | `e05b95382a9d438c49b265eb6b36bf276350f1196bd3bc7ed65b31668aec1578` |
| 009-085 | 5 | `c1d86ae` | `R2/DELIVERY/DELIVERY_MANIFEST.json` | 3 | 404a59105bf8… | manifest.verification | 121,904,044 | `7d29affb772389df0add6de14ac15dcd5059d0816b15f87bcfeff90167f18783` |
| 009-121 | A | `bc7fb13` | `delivery/009-121.zip.manifest.json` | 4 | f306c49a522e… | manifest.verification | 177,815,101 | `1dd8c706b3033693c86c02802729c902c49b5747f137962f1fa5e9a4068953aa` |
| 009-122 | A | `bc7fb13` | `delivery/009-122.zip.manifest.json` | 4 | d6a59506eff1… | manifest.verification | 174,142,597 | `178b8bc07b2b0d14fc9e0a114551f2e0ee2f18e7b0a231626911c4b601a6fdae` |
| 009-124 | A | `bc7fb13` | `delivery/009-124.zip.manifest.json` | 4 | b182be8b12df… | manifest.verification | 167,788,881 | `4a5ae53587bab3e373769c9b269fb87446dc2c75252d2c5b422c0101195f676d` |
| 009-161 | C | `982388c` | `DELIVERY-PARTS/PARTS.json` | 8 | 7921a564b9e1… | RESTORE-TEST.json | 356,722,469 | `7921a564b9e1047f41de9dbbe118f818b317cfce162da3988221199471dc3b06` |
| 009-162 | C | `982388c` | `DELIVERY-PARTS/PARTS.json` | 6 | d022961419eb… | RESTORE-TEST.json | 271,311,687 | `d022961419eba0849a6f096b55ddf89f42caf41f241665fa4308274a581e03d8` |
| 009-181 | C | `982388c` | `DELIVERY-PARTS/PARTS.json` | 7 | e8a578cc37a0… | RESTORE-TEST.json | 293,840,304 | `e8a578cc37a0cabc162c6104a2628e3d953f5658b187d706f7a312c0884ea8c0` |
| 009-182 | C | `982388c` | `DELIVERY-PARTS/PARTS.json` | 9 | 4e223acad2af… | RESTORE-TEST.json | 380,164,839 | `4e223acad2af51c575a3914e3c57a563339d811d3292793b4bf5ccbff7429734` |

合计 22 个文件，4,014,668,757 字节（约 3.74 GiB）。

正式运行时工作流会重新读取各分支当时的最新提交；若工位在此之后又改了某条，交付 ZIP 的 SHA256 会随之变化（日志与 `delivery-009-records.json` 会记录实际值）。
009-021 在本次检查期间已被 Cloud3 更新（提交 `c083ba3`，5 片），上表是更新后的结果。
