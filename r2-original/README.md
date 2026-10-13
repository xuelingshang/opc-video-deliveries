# 原版 R2 朋友端下载工具（原样保存，不修改）

来源：Founder 提供的 `OPC-公开交付一键下载-R2-提前交付和迟交自动补齐.zip`（ChatGPT 制作的 R2），
附件 SHA256 `a2ffd6e41fe9bbe19f44c91a16b434f7f4225381f8cf6030daa8c66893abe75f`。
`01-给朋友/` 是该 ZIP 中同名文件夹的逐字节副本（`.gitattributes` 禁止换行转换），即朋友手上的工具。

ZIP 中的全部文件与 SHA256（管理员脚本 `03-仅管理员使用/` 按其自身说明不放入公开仓库，只登记哈希）：

| 文件 | SHA256 |
|---|---|
| 00-先看这里.txt | bbac72d9ac423b8fa91e0c2bbae3fd69c3d9c98816ba9dc2bb6dbdd3187bcbaa |
| 01-给朋友/01-双击下载最新视频.cmd | b85b4ee5d9d527d64bded794fbaddcff9b9c65456ede10163e971656e62052d5 |
| 01-给朋友/02-下载指定日期.cmd | 6b53f3edcf06fc1dea09414e92b1ad45ddba09a7d8972303bdcda9b59039e7ce |
| 01-给朋友/DOWNLOAD.ps1 | c06e41581f4c0211113ce38effd7cabfb99db24c9051b0dce2d6dd657198457a |
| 01-给朋友/给朋友看-操作说明.txt | dcb709f46f702fadcfc5bbcb3a2a63d842fc84a2901e383213ec17c551b9800e |
| 02-交付仓库初始文件/.gitignore | 90079bbee8bff58ff12bca80056e1a32b84be7894ec5f4ec9230c28dd1c3b7ac |
| 02-交付仓库初始文件/README.md | 7e3218853c3833dfdf59c7191d39a4725874c6bb9bb37f4e833088db80c70632 |
| 03-仅管理员使用/Claude-C-首次部署任务.txt | 58d205e47de82cf2d917c4894ba4ca344c2dc86f5333482719d855d9be293250 |
| 03-仅管理员使用/approvals.EXAMPLE.json | 09671e4e0a8b6641cebaee221675a8549f3dbbdcb92349c7e51472a779f1f70e |
| 03-仅管理员使用/prepare_release.py | 58e1aa0ef6f5a0d46e0567ebcb1fdb47e7d7763ed8693af11ad986237d0f6aa1 |
| 03-仅管理员使用/publish_release.py | 0445d78407c4f23b7604ddde0e35593e2600736bce8c9c3b0a2349e2a90d9013 |

安全检查（2026-10-13）：11 个纯文本文件，无可执行二进制、无路径穿越条目、无令牌或账号信息；
`DOWNLOAD.ps1` 只访问 `api.github.com` 与 `github.com/xuelingshang/opc-video-deliveries/releases/download/`。

已知缺陷与修正版见 [`../r2.1-patch/`](../r2.1-patch/README.md) 和 [`../docs/R2-COMPATIBILITY.md`](../docs/R2-COMPATIBILITY.md)。
