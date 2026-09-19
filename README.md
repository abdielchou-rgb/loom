# 龙骨 Keel · 叙事编译器

> 中文名**龙骨**，取自吊顶与船体里那层**看不见却承重**的结构 ——
> 正对应本项目的立场：决定一部作品站不站得住的，是正文之下那层结构。
> 英文名 **Keel** 是同一件事的另一个说法：龙骨，先定龙骨，再定船。
>
> **一个不谄媚的、站在作者这边的对抗性编辑。**
>
> 它不替你写，也不夸你写得好。它用结构化的证据指出你的故事哪里站不住、
> 用留痕保护你的权益，但把每一个「改不改、怎么改」的决定都交还给你。
>
> 一句话定位：**可证明是你写的 · 故事哪里坏了可被指出 · 投入制作前就知道不值得做。**
>
> 🌐 English documentation: [README_EN.md](README_EN.md)

---

## 它是什么，不是什么

Keel **不是「写稿机器」**。它是一个**叙事编译器**：把你的想法编译成一份
结构化的**叙事中间表示（Narrative IR）**，再把它渲染成小说、剧本、互动小说、
galgame、漫画分镜，或一份可分享的体检报告。

文本只是 IR 的一个视图——**IR 才是产品本体**。所以 Keel 卖的不是「一篇稿子」，
而是「关于这篇稿子的判断」：它哪里成立、哪里矛盾、哪里合规、哪里会垮。

因此扩展 Keel 的方式是「加一个 renderer」，而不是往核心里塞模块。

> 文本的生产成本趋近于零之后，稀缺的不再是故事，而是**关于故事的信息**。
> Keel 的产品是信息，不是故事。

## 快速开始

> **第一次来？先读 [`QUICKSTART.md`](QUICKSTART.md)**（5 分钟上手）。
> 下面这是给已经知道项目是什么的人备的速查。
> 版本记录见 [`CHANGELOG.md`](CHANGELOG.md)。

下面每条命令都离线可跑。Keel 不预测你的故事会不会火——只告诉你它哪里站不住、哪里合规、哪里要改。

```bash
# 建环境
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS/Linux

# 一句话想法 -> 正文（1.0 主流程，无需 API key）
.venv/Scripts/python.exe -m keel.cli write "一个替人收尸的刀客，发现自己要收的那具尸体是自己十年前的名字" \
    --scenes 6 --words 600 --out out/demo1

# 端到端验证（10 个环节：IR -> 正文 -> 体检 -> 观众模拟 -> A/B -> 渲染）
.venv/Scripts/python.exe scripts/pipeline_demo.py

# IR 层验证（10 个环节：校验器 / lore / 运行时 / 合规 / 渲染）
.venv/Scripts/python.exe scripts/demo.py
```

产物写入 `out/`：`novel.md` `script.fountain` `storyboard.json` `story.ink`
`script.rpy` `outline.md` `ir.json` `compliance.json` `audience.json`。

> **默认离线。** 整条流水线在没有 API key 的情况下端到端可跑 —— 用的是确定性的
> 参考生成器（`MockGenerator`）。这既是架构可验证性的证明，也是回归测试的基线。
> 接真模型只需换一行：`build_generator(model="gpt-4o")`。

> **不想敲命令？** 起一个本地网页界面，在浏览器里填一句话想法、点「生成」即可：
> `.venv/Scripts/python.exe -m keel.cli web` → 打开 http://127.0.0.1:8000/ 。
> 它只监听本机，数据不出本机，跑的是和命令行**完全相同**的生成逻辑（UI 只是视图）。

## 命令行

```bash
P=.venv/Scripts/python.exe

$P -m keel.cli write    "一句话想法" --out out/            # 想法 -> IR -> 正文（1.0 主命令）
                                                          #   ↑ 同时产出 report.html（双击可看）
$P -m keel.cli audience out/ir.json                       # 观众模拟（留存曲线 + 观众原话）
$P -m keel.cli audit    out/ir.json                       # 故事体检（健康分 + 分级建议）
$P -m keel.cli recheck  out/ir.json                       # 旧 IR 重跑 + 「上次以来变了什么」
$P -m keel.cli render   out/ir.json -f renpy              # 渲染指定媒介
$P -m keel.cli render   out/ir.json -f text --meta        # 正文内嵌结构元信息
$P -m keel.cli outline  out/ir.json                       # 大纲（IR 层人工确认）
$P -m keel.cli lore     out/ir.json --text "沈砚掏出腰牌"   # 查看 lore 激活集
$P -m keel.cli play     out/ir.json --runs 500            # 随机化通关测试
$P -m keel.cli compliance out/ir.json --json out/c.json   # AI 参与度合规报告
$P -m keel.cli submit-check out/ir.json       # 投稿前合规自检（能不能投）
$P -m keel.cli process-report out/ir.json --out 过程.md  # 创作过程报告（申诉举证）
$P -m keel.cli templates -v                               # 列出结构模板

$P -m keel.cli run      "一句话想法" --scenes 8 --checkpoint   # 自动驾驶（无人值守）
$P -m keel.cli proposals out/ir.json                      # 列出待裁决的结构提案
$P -m keel.cli decide   out/ir.json --all --by "human:我"  # 裁决（**默认写回原文件**）
```

### 自动驾驶（`keel run`）：不喊停就一直写

```bash
$P -m keel.cli run "想法" --scenes 8 --words 400 --checkpoint \
      --max-scenes 20 --max-cost 5 --max-minutes 30
```

「我不喊停」不是停止条件，是侥幸 —— 所以停止判据全部**从 IR 派生**：
目标场数达标 / 结局锚点兑现 / 预算闸（场数·成本·时长）。
**结构破损与漂移是「暂停」不是「停止」**：机器停下等人，绝不自动改结构。

> 曾经还有一条「全部承诺已兑现」，已删除：承诺的 `satisfied` 是**声明式**
> 字段，引擎不该猜它；而按 `must_hold_at` 派生停止条件在增量路径上恒真
> （`AutoWriter` 建第一场时就绑锚点，7 条承诺全落到 `sc1`）。
> 详见 `keel/pipeline/auto.py` 中 `_commitments_done` 旧址的说明。

自动驾驶推进的是 **IR**，不是续写文本：每轮产出场景卡 + 正文，然后把
`state_deltas` 提交回 IR。否则 IR 静止而文本变长，几场之后校验器就在
认真地检查一份虚构 —— 门禁全绿，查的是假货。

暂停后的续跑**必须显式指回人裁过的那份 IR**：

```bash
keel decide out/.auto/paused.json --all            # 人做判断
keel run "想法" --checkpoint --resume-from out/.auto/paused.json
```

不写 `--resume-from` 会从检查点续跑，而检查点存的是**机器暂停那一刻**的 IR ——
你刚做的裁决会被无声覆盖。这种情况 Keel 会先**警告**再继续。

### 决策留痕 = 申诉时真正要的那份证据

合规台账向来只记「AI 参与了哪一场」—— 那是**免责证据**，它只能说明
剩下的不是 AI 写的，说不出**人做了什么**。申诉要的是**主张证据**：

```
keel run  →  机器提案（proposed_at / proposed_by）
keel decide → 人类裁决（decided_at / decided_by）  ← 驳回的证据力强于采纳
keel process-report → 一条完整的时间线
```

`keel decide` **默认写回原 `ir.json`**：不落盘的裁决不是裁决，
人做了判断而系统没记住，申诉时这条证据不存在。
但要把话说全：这些时刻是 Keel **自报**的墙钟（`keel/clock.py`），
不签名、不存证 —— 需要对抗性质疑请用第三方时间戳。

## 核心设计

### 第一分钟：能双击打开的产物

`write` 现在会在输出目录里同时写一份 `report.html`：
**单文件、自包含、无 CDN / 无外链、断网可看**。
结构健康分、评估覆盖、人类判断痕迹、三层 IR、体检明细、待裁决提案都在一屏里。

为什么这是核心设计而不是打磨项：

> **一个到不了用户手里的判断，价值为零。**
> 35 个校验器如果没人看，等于 0 个。可达性是**乘数**，不是加法。

（`render -f html` 也可以单独对任意 `ir.json` 出报告。）

### 写作时的觉察回显（CHI 2026）

Bhat et al., *Reactive Writers*, CHI 2026（19 人访谈 + 1,291 次协同写作会话）发现：
与 AI 协同写作时，作者**察觉不到** AI 对自己方向的影响，却**感觉完全掌控**
—— 因为在原则上他们随时可以编辑最终文本。

所以 Keel 在**写作时**（不只是申诉时）回显：

```
已做判断 12 次（采纳 5 / 驳回 7） · 待你裁决 1 条 · 人工改写场景 3 个
```

数据来自 `ir.proposals`（已持久化），**不取内存态遥测** —— 觉察必须跨会话成立。
只报数、不评分：加一句「你的判断力 72 分」会把觉察又变成可刷的指标。

### 网文正文默认不出（媒介策略闸门）

起点 / 番茄 / 晋江 一致禁止 AI 直出正文（起点 >10% 即处理）。
**同一个 Keel：做网文是「违规工具」，做剧本是「合规工具」。**

故 `web_novel` 媒介默认**不生成正文**，需要时 `--force-prose` 显式放行并留痕。
这是**策略不是删除** —— 政策会变，改一行即可。见 `keel/policy.py`。

### 流水线是严格线性的，没有循环依赖

```
idea
  ├─ PremiseEngine     → L3 承诺层（主题 / 结局锚点 / 必要转折）
  ├─ CastEngine        → 卡司表（谁在这部戏里）
  ├─ StructureEngine   → L1 情节层 + 场景骨架（McKee 价值翻转是硬约束）
  ├─ CharacterEngine   → L2 角色层 + 世界层（此时才看得到场景）
  ├─ LoreSeeder        → 记忆层（常驻 / 关键词触发 / 递归激活）
  ├─ LedgerSeeder      → 悬念台账 + 知情矩阵
  ├─ Scripter × N      → 逐场正文（只注入相关 lore，绝不注入全文）
  └─ CriticLoop        → 体检 → **只自动修文风类问题**
```

三个关键设计决策：

1. **控制点靠上游。** 人在回路的确认点设在 IR 层，不在文本层 ——
   改结构比改一万字便宜两个数量级。
2. **生成与修订分离。** Critic 可换用不同模型，避免同模型自评的自我确认偏差。
3. **只自动修「可自动修」的。** 文风类（去 AI 味）自动改；结构类（承诺没有
   落点、谜题烂尾）必须人决策 —— 自动改结构会毁掉作者意图。

### 三层正交 IR（Riedl & Young, IPOCL, JAIR 2010）

| 层 | 内容 | 缺失时的失败模式 |
|---|---|---|
| L1 因果情节层 | 事件节点 + 偏序因果链 | 事件合理但角色像工具人 |
| L2 角色目标层 | 目标图 + 行动元 + 状态时间线 | — |
| L3 作者意图层 | 主题断言 / 道德论证 / 硬承诺 | **每段都合理，合起来什么都不证明** |

### 场景节点用 Genette schema，不是 beat sheet

`{focalizer, narrator, focalization, fabula_time, sjuzhet_index, frequency}`
+ McKee 价值转折 + Todorov 状态增量。

白送四个能力：换聚焦者重写、时序算子、频率旋钮、内聚焦越界检测。

### 节拍表是「场景覆盖一段」，不是一个场景一个节拍

Save the Cat 有 15 个节拍，一部长篇只有 6-10 个主要场景。
「一个场景 = 一个节拍」在数学上不可能覆盖完，会让校验器永远报警。
正确的语义是场景覆盖节拍表上的一段（相邻场景进度的中点之间），
15 个节拍按比例分摊到 N 个场景上 —— 这样「覆盖完整」才是可达判据。

### 记忆用工业收敛的 lorebook 字段体系

关键词触发 + 预算封顶 + **递归激活**。优于纯向量检索——向量召回是概率性的，
长篇里「该出现时没出现」是致命的。

### 观众模拟：结构性流失预测，不是「AI 猜爆款」

**先说清不能做什么。** LitBench (EACL 2026) 的结论很硬 —— 零样本 LLM 判断
在若干一致性指标上接近随机（UNION 指标 48.7%）。任何声称「AI 预测爆款」的产品
都在撒谎。所以本系统不把「让模型打分」当卖点。

能做的三件事：

1. **确定性留存曲线。** 由 IR 结构信号 × 人格参数算出，显式 hazard 模型，
   可复现、可回归测试、参数可辩论。不是「模型的感觉」。
2. **配对比较（推荐的主要用法）。** 绝对评分不可靠，但配对偏好稳定得多。
   `sim.ab(ir_v1, ir_v2)` 是主要 API，不是附属功能。
3. **把数值翻译成人话。** 当确定性模型与 LLM 判断**不一致**时，
   把那场标记出来给人看 —— 分歧本身就是最有价值的信息。

两个容易做错的地方，已显式处理：

- **「没有悬念」不能当流失原因用在终局。** 结尾把所有线收完是完成度，不是缺陷。
  hazard 模型里这条只在故事中段生效。
- **终局留存会被篇幅污染。** 累计留存必然随篇幅下降 —— 那是篇幅效应，不是质量。
  所以 A/B 用**单场平均存活率**（几何平均）判胜负，终局留存只作参考。

校准是显式的：未校准的模拟器只是先验，不是预测。`calibrate()` 用真实留存数据
拟合 `base_hazard`，并报出残差 —— 只有一个自由度，别指望它学到平台的全部规律。

### 2.0 运行时 = Waypoint + Storylet + Director（Emily Short《Beyond Branching》）

- **Waypoint 骨架** 锁定必达节拍，反转内容经济学：内容越多，故事自愈越灵敏
- **Storylet 池** 品质门控 + waypoint 门控 + 显著性排序
- **Director** 用戏剧弧光约束选择，防意外坏结局
- **硬不变量**：永远不要给玩家零个选项

### 35 个校验器 + 9 个报表项，每个都有方法论出处

McKee 价值转折 / Todorov 状态增量 / Barthes 谜题台账 / Greimas 行动元 /
Genette 聚焦边界 / POCL 因果链 / 李渔立主脑 / 毛宗岗犯而不犯 / 短剧钩子密度 /
Berlyne 习惯化 / Egri 前提必须被论证 / 认知叙事学 ToM …

**门禁项 35 个，报表项 9 个。** 报表项（`mirror_bookends` /
`revelation_regression` / `thread_budget` / `mice_thread_closure` /
`narrative_arc_shape` / `dialogue_rhythm` / `adverb_density` /
`length_burstiness` / `dramatic_irony_available`）
设计上只做通报，源码里不出现 WARN/ERROR，永远不会让作品不通过 ——
所以不能算进「N 个校验器」。这条分类是**可机检**的：
`scripts/verify.py` 会扫源码断言它成立。

### 「结构健康分」不吸收非结构信号（advisory 通道）

`score()` 的名字是**结构**健康分。工艺/文风信号（AI 味 / 张力 / 风格漂移 /
传输度 / 认知负荷）与**向前看的张力点**（「接下来可以写什么」）都走
`Report.advisory` 通道：出现在报告里，但不进 `score()`。

不这么做的后果实测过：craft 的 6 条 INFO 让干净基线 95 → 89；
（当时的数字；三个老报表项迁进 advisory 之后，基线现在是 96。）
而「可写的张力越多分数越低」更是无法解释 —— 加几个检测器分数就降，
读者分不清是「结构变差了」还是「多装了检查」。

### 向前看：`TensionSeeder` 与 `Proposer`

其余引擎都在生成或体检，这两个是**向前看**的：

- **`TensionSeeder`** 从锚（`wound` / `lie`）与信念层派生 `TensionPoint` ——
  每条都带 `suggestion`（schema 层面必填：只报「这里有张力」而不说
  「下一场怎么用」，等于把谜题台账又做了一遍）。它**从已声明的结构反推，
  不编造内容**：不播种秘密、不播种递归信念，那是创作内容不是结构反推。
- **`Proposer`** 把结构类问题转成 `Diff` 提案，**绝不自动应用**。
  作者用 `KeelPipeline.decide()` 一键采纳/拒绝，裁决进决策遥测
  （采纳率 + 按来源/去向/字段分布）。

边界不变：`CriticLoop` 仍然只**自动**修文风类；结构类从「留给人决策」
升级为「生成提案供一键采纳」，但仍不自动改。

### SKIPPED ≠ PASS ≠ CRASHED：体检报告必须同时报覆盖率

校验器拿不到数据时是 **SKIPPED**，不是「通过」。四态：

| 状态 | 含义 | 影响健康分 |
|---|---|---|
| PASS | 跑过了，没问题 | 否 |
| FAIL | 跑过了，有 Finding | 是 |
| SKIPPED | 数据不足，**没跑** | 否 |
| CRASHED | **校验器自己崩了** | 否（这是 Keel 的 bug，不是稿子的缺陷） |

需求是**声明式**的（`keel/validators/base.py` 的 `REQUIRES` 表），
所有校验器函数一行都不用改。理由：需求表本身可被测试断言 ——
「注册了却永远不会被真正执行」的死校验器会立刻暴露。

CRASHED 是 2026-09-14 补的第三种失败。它抓到的真缺陷：`pattern_saturation`
把 `SceneNode.storylet_ids` 写成了 `Storylet.storylet_ids` —— 在没有 storylet
的 IR 上那个生成器表达式的循环体根本不求值，**永远不报错**；
在有 storylet 的 IR 上必崩。「干净基线全绿」与「这个分支从来没跑过」
可以同时成立，而它漂了很久。崩溃**不产出 Finding**，所以不会自己浮出来，
只能靠断言抓。

体检报告因此必须一起报「评估覆盖」：

```
健康分 96/100   错误 0 · 警告 0 · 提示 4
评估覆盖 92%（跑过 33/36 · 跳过 3 · 崩溃 0）
  ⊘ 缺 medium:micro_drama：2 个 — hook_cadence, paywall_gate_present
```

只报「健康分 92」而不报覆盖率，等于隐瞒了「有多少项根本没测」。

### 自证：`scripts/verify.py`

零依赖（不需要 pytest、不需要 API key），一条命令回答八个问题：

1. registry 完整吗（每个 code 都声明了数据需求）
2. 报表项真的是报表项吗（扫源码断言无 WARN/ERROR；ADVISORY ⊆ REPORTS）
3. 提示词字段齐吗（模板里的占位符真的有人填，还是静默退化了）
4. 计数漂移了吗（README / 方案 / **脚本**里的「N 个校验器」必须等于 registry 实际数）
5. 有死校验器吗（每个门禁项至少在一种媒介基线上真的会执行）
6. 干净文本会误报吗（基线 IR 上 0 ERROR + 0 WARN；advisory 项不许空转）
7. 反例抓得住吗（40 个反例变异，断言**严重度升级**）
8. 校验器会崩吗（基线 / 示例 / 每个变异上 `Report.crashes` 必须为空）

第 6、7 条给出**净命中率**，而不是绝对命中率。绝对命中率是自欺的：
对着任何文本都报警的校验器命中率 100%，信息量为零。也不是
「变异后触发了就算」—— `thread_budget` 在健康时也输出 INFO，
只判「有输出」它永远命中，那是在给指标注水。

当前结果：**净命中率 100% · 两种媒介基线上零误报 · 计数漂移 0 · 崩溃 0。**

（上面刻意不再写「N/N」：这个数一度手写成 `28/28`，实际是 `32/32`，
而计数漂移检查当时管不到它 —— 凡手写的数字都会漂，只是时间问题。
要数字就跑 `scripts/verify.py`，它每次现算。）

这套 fixture 第一次跑就抓到了五个真缺陷（都已修）：

1. `li_yu_reduce_threads` 的窗口宽度使判据**数学上恒为假** ——
   窗口宽 3 而判据是「>3 条」，场景数 <12 的故事它永远静默通过。
   不是判据太松，是判据不可满足。
2. `emotion_curve_match` 只看 Pearson r，会放行一条**完全没有谷**的
   单调上升曲线（与 man_in_a_hole 声明弧线的 r 高达 0.49）。
   补了「转折点位置」判据。
3. STRUCTURE 提示词**从不告诉模型声明了哪条弧线**，却要求它填
   `emotion(-1..1)` —— 这个要求在信息上不可能被满足。
4. 桩件把 emotion 写死成一条与 `arc_shape` 无关的上升直线，
   于是流水线自己产出的 IR 过不了自己的校验器。
5. `mirror_bookends` / `revelation_regression` / `thread_budget` 三个函数
   源码里根本没有 WARN/ERROR，**永远不会让作品不通过**，
   却被算进了门禁数量 —— 这正是我在 Æsirian 那 167 道门禁上
   批评过的虚报。现在单列为报表项，且分类可机检。



### id 与显示名的边界是架构守的，不是提示词求的

IR 内部一律用 id（机器友好），提示词与正文一律用显示名。
`Scripter` 在构造提示词前做 id→名字解析，`StructureEngine` 对场景卡文本
再做一道兜底替换。理由：提示词是软的，代码是硬的。

## 方法论中立

内置 11 个结构模板，刻意包含彼此冲突的体系：

Save the Cat 15 节拍 · 三幕 · 起承转合 · 章回体 · 微短剧节拍 ·
**Reagan et al. 2016 实证的六种情感弧线**

> 那篇 EPJ Data Science 论文用情感弧线做聚类，只得到六种基本形状，
> **没有一种是三幕**。把实证弧线与 Snyder 的模板放在同一层级，是诚实做法。

## 目录

```
keel/ir/          IR 模型（base/models/tom/proposal）、枚举、结构模板插件、
                  情感弧线规范（arcs.py）、工艺装置词表（devices.py）
keel/llm/         Generator 抽象 / 提示词版本化 / 离线参考实现 / LiteLLM 接入 /
                  CHANGES 自申报解析（declaration.py）
keel/pipeline/    10 个引擎 + 编排层（idea -> IR -> 正文 -> 提案）
keel/audience/    观众模拟（人格库 / 信号抽取 / hazard 模型 / A-B / 校准 /
                  认知负荷 cognitive.py）
keel/validators/  35 个校验器 + 9 个报表项（结构 + 一致性 + 叙事 + 平台合规）
keel/audit/       反 slop 扫描 + 工艺检测器（craft.py）+ 风格漂移（dress.py）
                  + 传输度（transportation.py）+ CSN 数值事实抽取（csn.py）
                  + 平台合规检测器（rhythm.py）+ 投稿前自检（selfcheck.py）
keel/render/      6 个渲染器（text / fountain / storyboard / ink / renpy / html）
keel/runtime/     Waypoint + Storylet + Director + 事件冷却矩阵（cooldown.py）+ 随机通关测试
keel/provenance/  溯源台账（meter.py）+ AI 参与度合规报告 + 决策遥测（telemetry.py）
                  + 创作过程报告 / 申诉举证（process.py）
                  + 写作时觉察回显（awareness.py）
keel/policy.py    媒介策略闸门（网文正文默认不出，可显式放行并留痕）
keel/cli.py       命令行入口
tests/fixtures.py          校验器 fixture 库（干净基线 + 40 个反例变异）
tests/test_csn.py          CSN 数值事实单元测试（TDD，零依赖）
tests/test_cooldown.py     事件冷却矩阵单元测试（TDD，零依赖）
tests/test_craft.py        四个工艺检测器单元测试（TDD，零依赖）
tests/test_tom.py          信念层与张力派生单元测试（TDD，零依赖）
tests/test_proposal.py     提案裁决状态机单元测试（TDD，零依赖）
tests/test_telemetry.py    决策遥测单元测试（TDD，零依赖）
tests/test_rhythm.py       三个合规检测器单元测试（含阈值变异测试记录）
tests/test_selfcheck.py    投稿前自检单元测试（三态 / 维度派生 / 标识）
tests/test_process.py      创作过程报告单元测试（证据强度 / 缺口声明）
tests/test_redlines.py     产品红线守卫：AST 扫描禁止反检测出口
examples/         完整 IR 示例（刻意含 5 类缺陷）
scripts/verify.py          自证：registry / 报表项 / 漂移 / 误报 / 净命中 / 崩溃 / 单元测试
scripts/pipeline_demo.py   端到端：想法 -> 正文 -> 体检 -> 观众模拟
scripts/demo.py            IR 层验证：校验器 / lore / 运行时 / 合规 / 渲染
```

> 单元测试的断言数**不写在这里** —— 手写的数字没有任何机制与代码同步，
> 必然漂移（这里原先写「56 项断言」，实际是 64）。
> `scripts/verify.py` 第 8 节每次运行都会现算并打印真实数字。

完整工程方案见 [`ENGINEERING_PLAN.md`](ENGINEERING_PLAN.md)。

## 合规提示

**两层法规，来源不同，不要混为一谈：**

| 法规 | 文号 | 施行 | 对内容的要求 |
|---|---|---|---|
| 《人工智能生成合成内容标识办法》 | 国信办通字〔2025〕2 号（网信办/工信部/公安部/广电总局） | **2025-09-01** | 显式标识（文本起始/末尾/中间）＋ 隐式标识（**文件元数据**：生成属性、提供者名称或编码、内容编号） |
| 《微短剧发展管理办法》 | 国家广电总局令第 16 号 | **2026-09-01** | 第 34 条：AI 生成制作的微短剧**每集明显位置**加提示标识 |

标识义务来自**早一年**的《标识办法》；微短剧办法第 34 条只是把它落到微短剧场景。

平台侧：起点中文网 2026-08-18 起 AI 占比 >10% 即处理（移出榜单与推荐位，非下架），
番茄单月拒签 AI 生成/空洞水文新书 16 万本。

**无法证明 AI 参与度的产品，在中国市场不可交付。** 溯源计量是本系统的内建能力。

### 产品红线：不做反检测

同类工具里有专门的「反检测改写」模式（例如 `--mode anti-detect`）。**Keel 不做。**

| | |
|---|---|
| **做** | 用与平台同一套特征空间**如实报告**（`keel.cli submit-check`），并给出真的改写方向；把「人做了哪些判断」记录下来供申诉举证（`keel.cli process-report`） |
| **不做** | 按平台阈值**反向优化**的一键改写；把 AI 内容伪装成人类创作的任何功能；隐藏阈值与词表 |

三条理由：

1. **技术上必然失败** —— 检测已从词汇层转到叙事特征层。有测试者反馈：哪怕手写大纲、
   AI 扩写、再手动重写 30% 关键段落，平台仍会标记「情感锚点偏移率超标」。
   **表层改写对付不了叙事层检测。**
2. **伦理上不可辩护** —— 帮人把 AI 内容伪装成人类创作，是在对抗平台与读者的知情权，
   与本系统的合规定位直接冲突。
3. **商业上自杀** —— 一旦被贴上「AI 洗稿工具」标签，平台申诉通道与生态全部关闭。

分界线：**Keel 帮作者「真的写得更好」，不帮作者「看起来像人写的」。**
前者是产品，后者是伪造。

这条红线**可机检**：`tests/test_redlines.py` 用 AST 扫描全部源码，
禁止任何反检测的函数名／命令行标志／帮助文案。词表与阈值全部
明文公开在源码里 —— 一个靠藏着阈值才能工作的检测器，站不住脚。

---

## 理论覆盖：对表与差距

[`理论覆盖清单_2026-09-15.md`](理论覆盖清单_2026-09-15.md) 是**实测对表**：
把「所有高引用论文」与「豆瓣 ≥7 的剧本创作书」列成两张表，逐条标注 Keel 的覆盖状态。

现状（不粉饰）：

```
论文  20 篇 → 已实现 4 (20%) · 文档层 12 (60%) · 完全未覆盖 4 (20%)
书籍  39 本 → 已实现 8 (21%) · 部分 3 · 不适用 5 · 未落地 23 (59%)
```

两个数字都是**可重新推导**的，不是手写的：

```bash
python scripts/fetch_citations.py --json out   # OpenAlex 真实引用数
python scripts/verify.py                        # 计数不变式（校验器/模板/反例/文档）
```

**「覆盖」的定义**：方法论变成了可执行判据（校验器 / 模板 / IR 约束），
且**有反例 fixture 证明该判据非空转**。只在文档里提过一句不算覆盖 —— 那是单独一档。
