| run | wall | tests | steps | calls | read | files | read/file | compactions | comp/step | last ckpt |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fast-native-1 | 53s | 4/4 | 14 | 22 | 9 | 6 | 1.5 | 0 | 0 | — |
| fast-d-2 | 185s | 4/4 | 16 | 23 | 13 | 5 | 2.6 | 8 | 0.5 | 0.5K |
| fast-f-2 | 218s | 4/4 | 15 | 25 | 13 | 6 | 2.2 | 8 | 0.53 | 0.4K |
| fast-g-1 | 47s | 4/4 | 14 | 18 | 7 | 6 | 1.2 | 0 | 0 | — |

### fast-native-1

工具构成：read=9，pwsh=6，write=6，glob=1
读得最多的文件：tokenize.js×2，count.js×2，cli.js×2，README.md×1，basic.test.mjs×1，package.json×1

（无压缩）

### fast-d-2

工具构成：read=13，pwsh=5，glob=2，edit=2，write=1
读得最多的文件：tokenize.js×3，count.js×3，cli.js×3，README.md×2，basic.test.mjs×2

| # | 被压区域 tokens | checkpoint | 保留比 | 段构成 |
| --- | --- | --- | --- | --- |
| 1 | 822 | 0.9K | 0.27 | User requests and instructions=414B，Selected excerpts=212B，Recorded judgments=259B |
| 2 | 3070 | 1.0K | 0.082 | Prior checkpoint=785B，Tool calls=126B，Files touched=88B |
| 3 | 2923 | 2.3K | 0.204 | Prior checkpoint=370B，Selected excerpts=1491B，Verification state=517B |
| 4 | 484 | 1.0K | 0.529 | Prior checkpoint=1025B |
| 5 | 2697 | 0.6K | 0.053 | Prior checkpoint=195B，Selected excerpts=198B，Recorded judgments=181B |
| 6 | 2867 | 3.5K | 0.314 | Prior checkpoint=576B，Selected excerpts=2588B，Recorded judgments=433B |
| 7 | 613 | 1.2K | 0.515 | Prior checkpoint=1262B |
| 8 | 2744 | 0.5K | 0.051 | Prior checkpoint=225B，Selected excerpts=160B，Recorded judgments=173B |

### fast-f-2

工具构成：read=13，pwsh=6，glob=3，edit=3
读得最多的文件：README.md×3，count.js×3，cli.js×3，tokenize.js×2，basic.test.mjs×1，package.json×1

| # | 被压区域 tokens | checkpoint | 保留比 | 段构成 |
| --- | --- | --- | --- | --- |
| 1 | 822 | 1.0K | 0.299 | User requests and instructions=414B，Selected excerpts=429B，Recorded judgments=137B |
| 2 | 3081 | 1.1K | 0.089 | Prior checkpoint=878B，Tool calls=126B，Files touched=88B |
| 3 | 2906 | 5.4K | 0.474 | Prior checkpoint=370B，Selected excerpts=855B，Recorded judgments=208B，Verification state=517B，Recent tool results=3554B |
| 4 | 1385 | 1.2K | 0.228 | Prior checkpoint=1262B |
| 5 | 3407 | 0.8K | 0.062 | Prior checkpoint=180B，Selected excerpts=198B，Recorded judgments=141B，Recent tool results=325B |
| 6 | 2864 | 5.2K | 0.469 | Prior checkpoint=667B，Selected excerpts=2097B，Recorded judgments=706B，Recent tool results=1899B |
| 7 | 1058 | 1.2K | 0.298 | Prior checkpoint=1262B |
| 8 | 2750 | 0.4K | 0.041 | Prior checkpoint=254B，Selected excerpts=197B |

### fast-g-1

工具构成：read=7，pwsh=6，edit=3，glob=1，write=1
读得最多的文件：count.js×2，README.md×1，basic.test.mjs×1，tokenize.js×1，cli.js×1，package.json×1

（无压缩）

