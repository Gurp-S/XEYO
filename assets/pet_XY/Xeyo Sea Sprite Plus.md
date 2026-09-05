# XEYO Sea Sprite Plus

这是在原 `xeyo-sea-sprite` 基础上扩展的桌宠包。**角色设计已冻结**：角色外形、服装、配色、比例、原九种状态以及新增动作均不再自行改造。本次修订只更新气泡资源与气泡映射。

## 资产

| 文件 | 用途 |
|---|---|
| `spritesheet-plus.webp` | 扩展图集，1536×2704，13 行 × 8 列；包含原九状态与四种新增状态 |
| `pet-plus.json` | 扩展桌宠配置，包含状态行、12 个气泡资源和严格来源声明 |
| `assets/bubbles/*.png` | 从用户提供的 `emotion-bubbles.png` 固定区域提取的 12 个透明气泡资源 |
| `qa/reference-bubbles-contact-sheet.png` | 12 个原图气泡的集中预览 |
| `final/validation-bubbles.json` | 气泡数量、透明像素、配置映射和扩展图集验证结果 |
| `qa/visual-findings.md` | 气泡裁切与视觉 QA 记录 |

## 气泡资源

气泡库完整保留用户原图的两排内容，没有新增图标或重新绘制：

| 资源 | 原图位置 | 语义用途 |
|---|---|---|
| `idle-ellipsis.png` | 第一排第一个 | 待机省略号 |
| `failed-exclamation.png` | 第一排第二个 | 失败或异常感叹号 |
| `waiting-question.png` | 第一排第三个 | 等待或疑问问号 |
| `thinking-bulb.png` | 第一排第四个 | 思考灯泡 |
| `happy-heart.png` | 第一排第五个 | 开心心形 |
| `waving-note.png` | 第一排第六个 | 挥手音乐符号 |
| `sitting-fish.png` | 第二排第一个 | 坐着状态鱼形思绪 |
| `thought-coconut.png` | 第二排第二个 | 椰子思绪 |
| `thought-island.png` | 第二排第三个 | 小岛思绪 |
| `sleeping-zzz.png` | 第二排第四个 | 睡眠 ZZZ |
| `review-book.png` | 第二排第五个 | 阅读或复核书本 |
| `thought-shell.png` | 第二排第六个 | 贝壳与海螺思绪 |

这些资源均为原图裁切与透明化处理结果，保留原有气泡轮廓、拖尾或思绪圆点、线稿、图标、留白和蓝灰色调。没有使用自行创作的替代气泡。

## 状态语义

`happy` 使用原角色图中的开心表情与姿态，并叠加原图心形气泡。`sleeping` 严格使用 `character.png` 右下角的**闭眼侧卧、双手抱白色鱼形枕头**姿态，并叠加原图 ZZZ 气泡。`thinking` 使用原图中的思考状态并叠加灯泡气泡。`sitting` 严格使用 `character.png` 下方偏右的**屈膝坐姿**，并叠加原图鱼形思绪气泡。其他状态按 `pet-plus.json` 的 `stateRows` 映射使用对应原图气泡。

## 接入建议

读取 `pet-plus.json`，使用 `spritesheet-plus.webp`，并依据 `stateRows` 的 `row` 与 `frames` 字段选择动作。若运行时支持独立气泡图层，可按 `bubbleOverlay` 在角色锚点处叠加；若不支持独立图层，则使用扩展图集中已经保留的状态视觉。其余 8 个气泡资源作为可选状态或环境反馈资源保留，不强制绑定到角色动作。

原有标准九状态包未被修改；如果运行时只支持标准 Codex 九行图集，请继续使用原标准包。扩展版的角色设计冻结标记为 `compatibility.characterDesignFrozen: true`，气泡来源记录为 `compatibility.bubbleSource: emotion-bubbles.png`。

所有新增气泡已完成 RGBA、非空、透明像素 RGB 残留、资源数量和配置映射检查。
