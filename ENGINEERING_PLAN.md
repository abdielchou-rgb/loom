# Loom 叙事编译器 · 完整工程方案

> **Idea → Narrative IR → Renderers**
>
> 版本 v1.0 ｜ 2026-09-14 ｜ 状态：架构定稿 + 可运行原型

本文档是可直接开工的工程方案。所有数据模型、校验器、渲染器、运行时均已实现并跑通，
代码见 `loom/`，端到端验证见 `scripts/demo.py`。

---

## 0. 开工前的三个假设

上一轮遗留的三个决策问题，本方案按以下假设推进（**如与实际不符，改动量已在括号中标注**）：

| 决策 | 本方案假设 | 理由 | 若要改动的成本 |
|---|---|---|---|
| 1.0 输出媒介 | **小说/网文 + 影视剧本双渲染** | Fountain 渲染器成本极低（已实现），双渲染不增加 IR 复杂度 | 低：删一个 renderer |
| 用户角色 | **「AI 帮你写」**（辅助共创） | 已核实：起点「AI>10% 撤榜」、番茄拒签 16 万份、NGA 投票 524 人中仅 33 人愿为 AI 小说付费。全自动在商业与平台规则上均不可行 | **高**：若改为全自动，产品重心与合规架构都要重做 |
| IR 开放程度 | **完全开放可编辑** | 这是「创作工具」与「生成器」的分界；也是唯一有数据沉淀和迁移成本的护城河 | 中：可退化为只读 |

---

## 1. 系统定位

**一句话：Loom 不是文本生成器，是叙事编译器。**

输入是想法，输出是 **Narrative IR（叙事中间表示）**；文本、剧本、Ink 脚本、Ren'Py 脚本、
漫画分镜都只是 IR 的渲染视图。这带来四个直接收益：

1. 一致性从「事后检测」变成「事前约束」
2. 方法论变成可插拔的结构模板，系统天然方法论中立
3. **2.0 从「重写」变成「加 renderer」**
4. 人类在 IR 层改稿的成本是改文本的 1/100

**三个真空地带（本方案的差异化立足点）**

| 真空 | 现状 | 本方案 |
|---|---|---|
| Narrative IR → 多后端 transpiler | 市面上只有「从零生成」，没有「从结构编译」 | `loom/render/` 五个 renderer |
| 统一的 typed lorebook schema | NovelAI / SillyTavern / KoboldAI 字段高度相似但无开放标准 | `LoreEntry` 模型 |
| LLM 驱动的 storylet + salience + director | 学术上近乎空白（storylet 研究停在 2019 前后） | `loom/runtime/` |

---

## 2. 架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│  输入层   Idea / logline / 参考作品 / 已有大纲                        │
└───────────────────────────────┬─────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  编排层   LangGraph 状态机（显式状态 + checkpoint + 人在回路）         │
│  ├ Premise Engine    内核层：前提 / 主题 / 弧线 / 结局锚点            │
│  ├ Structure Engine  结构层：节拍模板 → 序列 → 场景卡                 │
│  ├ Lore Engine       记忆层：lorebook 编译与注入                      │
│  ├ Render Engine     渲染层：5 个 renderer                           │
│  ├ Audit Engine      审校层：校验器 + 反 slop + 奖励模型               │
│  ├ Audience Sim      观众模拟（产品楔子）                             │
│  └ Provenance        溯源与合规计量                                   │
└───────────────────────────────┬─────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  核心     Narrative IR（三层正交）                                    │
│  L1 因果情节层  ── 事件节点 + 偏序因果链 (POCL)                       │
│  L2 角色目标层  ── 目标图 + 行动元绑定 + 状态时间线                    │
│  L3 作者意图层  ── 主题断言 / 道德论证 / 硬承诺                       │
│  + 场景层 (Genette) + 台账层 (谜题/知情) + 世界层 + 记忆层 + 溯源层    │
└───────────────────────────────┬─────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  运行时 (2.0)   Waypoint 骨架 + Storylet 池 + Director               │
└───────────────────────────────┬─────────────────────────────────────┘
                                ▼
        小说 / 剧本 / Ink / Ren'Py / 漫画分镜 / 剧本杀
```

**为什么 IR 必须是三层正交**（Riedl & Young, IPOCL, JAIR 2010）：

| 约束层级 | 缺失时的失败模式 |
|---|---|
| 只有 L1 | 事件合理，但角色像工具人 |
| L1 + L2 | **每段都合理，合起来什么都不证明**（漂离论点）—— AI 长文最隐蔽的失败 |
| L1 + L2 + L3 | 情节必然性、角色可信性、主题论证同时成立 |

---

## 3. 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 语言 | Python 3.12+ | AI 生态；IR 用 Pydantic v2 做硬契约 |
| IR 校验 | **Pydantic v2**（`extra="forbid"`） | schema 是硬契约，不是文档。未知字段直接拒绝 |
| 编排 | **LangGraph** | 显式状态机 + checkpointing + 人在回路，最贴合叙事 IR。CrewAI 状态管理弱，AutoGen 适合批评循环 |
| 模型接入 | **LiteLLM** | 多provider 切换 + 模型版本固定（同一部长篇换模型会导致风格断裂，必须可追溯） |
| 存储 | SQLite（dev）→ PostgreSQL + pgvector（prod） | IR 存 JSON/YAML + 内容寻址版本库；向量仅作兜底检索 |
| 前端 | Next.js + React Flow（故事图）+ Tiptap（正文） | IR 可视化编辑是产品本体 |
| 可观测 | Langfuse / OpenTelemetry | prompt 与模型版本追踪是刚需 |
| 图像 | 外部模型（本系统不产图） | 分镜 JSON 只描述，`consistency_key` 绑定参考图 / LoRA |

**关键工程决策：不引入向量数据库做主力检索。** 关键词触发 + 预算封顶优于纯向量——
向量召回是概率性的，长篇里「该出现时没出现」是致命的。向量只作兜底。

---

## 4. 数据模型（已实现）

`loom/ir/models.py`。核心设计要点：

### 4.1 场景节点：Genette schema，不是 beat-sheet 场景卡

```python
class SceneNode(LoomModel):
    # --- Genette《叙事话语》---
    focalizer: str            # 谁感知
    narrator: str             # 谁讲述
    focalization: Focalization  # zero / internal / external
    fabula_time: TimePoint    # 故事时间
    sjuzhet_index: int        # 话语顺序
    frequency: Frequency      # singulative / repetitive / iterative

    # --- McKee 价值转折 ---
    value: str
    value_charge_start: Literal["+", "-"]
    value_charge_end: Literal["+", "-"]

    # --- 场景卡 ---
    goal / conflict / turning_point / outcome / entities / emotion

    # --- Todorov 状态增量 ---
    state_deltas: list[StateDelta]   # 零增量会被拒绝

    # --- 2.0 预留 ---
    is_branch_point / is_paywall_gate / storylet_ids
```

**这一换白送四个能力**：换聚焦者重写同一场景；闪回/省略/概述成为一等算子；
频率做质感旋钮；内聚焦越界自动检测。

### 4.2 记忆条目：工业字段体系的统一 schema

`LoreEntry` 把 NovelAI Lorebook / SillyTavern World Info / KoboldAI 的字段收敛为一份
typed schema：`keys / secondary_keys / logic / content / position / depth / role /
order / token_budget / reserved_tokens / scan_depth / recursion / min_activations /
inclusion_group / probability / timed / match_whole_words / is_constant`。

**CJK 场景下 `match_whole_words` 默认关闭**，否则中文匹配全废。

### 4.3 Storylet：骨架与血肉的接缝

```python
class Storylet(LoomModel):
    at_waypoint: str | None      # 挂载在哪个 waypoint；None = 全局（兜底块）
    advances_waypoint: str | None
    preconditions / effects       # QBN 的品质门控
    salience: float              # 显著性排序
    arc_weights: dict[str, float] # 供 Director 约束，防意外坏结局
    is_fallback: bool            # 硬不变量：永不给玩家零个选项
```

### 4.4 IR 指纹

`NarrativeIR.fingerprint()` 基于场景转折 + 承诺生成 16 位哈希，用于版本比对与缓存失效。

---

## 5. 模块设计

### 5.1 Premise Engine（内核层）

输入想法，输出 L3 承诺层：Egri 前提（一句因果断言）、McKee 控制理念、Reagan 弧线形状、
**结局锚点**。

**关键：倒着设计，正着写。** 先锁结局与关键转折，再反推节拍。绝大多数结构崩坏
都是因为开写时结局还没定。

### 5.2 Structure Engine（结构层）

结构模板 = `{ beats[], validators[], prompt_fragments }` 三件套（`loom/ir/templates.py`）。

**已内置 13 个模板，刻意包含彼此冲突的体系**，以证明方法论中立：

| 模板 | 来源 | 节拍 |
|---|---|---|
| `save_the_cat` | Blake Snyder | 15 |
| `three_act` | Syd Field | 5 |
| `kishotenketsu` 起承转合 | 东亚传统 | 4 |
| `zhanghui` 章回体 | 明清章回小说 | 4 |
| `micro_drama` 微短剧 | 中国短剧行业惯例 | 6 |
| `arc_*` × 6 | **Reagan et al. 2016（实证聚类）** | 2-3 |

> 把 Reagan 的六种实证情感弧线与 Snyder 的 beat sheet 放在同一层级，是诚实做法：
> 那篇 EPJ Data Science 论文用情感弧线做聚类，**只得到六种基本形状，没有一种是三幕**。
> 而 Bordwell 指出好莱坞规范是历史偶然的惯例，beat sheet 的错误在于把语料当成了语法。

### 5.3 Lore Engine（记忆层）

三层记忆分工：

| 层 | 机制 | 用途 |
|---|---|---|
| 硬约束 | IR 结构化字段，直接注入 | 角色状态、知情、伏笔 |
| 软记忆 | lorebook 关键词触发 + 递归激活 | 设定细节、世界规则 |
| 滚动摘要 | 近期原文窗口 | 文风与语感连续性 |

`Lorebook.compile(text, budget_tokens)` 的选择顺序：常驻条目 → 关键词命中
（主键 + 次键逻辑）→ 递归激活 → 按 order 排序 → 预算截断。

**递归激活是长程一致性的关键**：提到「沈砚」→ 激活该条目 → 触发其关联的
「锦衣卫」条目 → 形成链式召回。

### 5.4 Audit Engine（审校层）

**35 个校验器 + 9 个报表项**（`loom/validators/`），每个都对应真实方法论来源，不是凭空发明的启发式：

| 校验器 | 来源 |
|---|---|
| `value_charge_flip` | McKee：场景结束时价值状态必须改变 |
| `state_delta` | Todorov：零增量即无场景 |
| `commitment_satisfied` | IPOCL：承诺必须有**落点**（`must_hold_at` 指向真实场景）。<br>注：**主题是否真的兑现**不可机判 —— 词法代理在中文上恒假，已移除 |
| `enigma_resolution` | Barthes 阐释符码：悬空未解 = 烂尾 |
| `mirror_bookends` ⊘ | Snyder：首尾净变化为零（**报表项**） |
| `emotion_curve_match` | Reagan 2016：弧线相关性 + **转折点位置** |
| `li_yu_main_brain` | 李渔：立主脑（游离场次检测） |
| `li_yu_reduce_threads` | 李渔：减头绪（窗口内并发支线 ≤3） |
| `mao_repeat_variation` | 毛宗岗：犯而不犯（重复必须变异） |
| `actant_collision` | Greimas：一人占 SUBJECT+OPPONENT = 反转信号 |
| `focalizer_boundary` | Genette：内聚焦不得越界 |
| `causal_chain_integrity` | POCL：前置条件必须被满足 + 因果环检测 |
| `hook_cadence` / `paywall_gate_present` | 短剧：钩子密度 + 付费卡点 |
| `knowledge_matrix` / `alias_collision` / `timeline_monotonic` / `entity_reference` | 一致性 |
| `numeric_fact_consistency` | 读者侧事实：跨场数值矛盾（年龄/年限/人数）纯规则可判 |
| `pattern_saturation` | Berlyne 1971 习惯化 + Genette 叙事频率：跨场窗口内的手法饱和 |
| `declaration_consistency` | CHANGES 双通道协议：自申报 vs 场景卡（**虚报 WARN / 漏报 INFO**） |
| `lie_arc_closure` | Egri：前提必须被论证 —— 高潮有没有真的处理那个 `lie` |
| `belief_consistency` | 认知叙事学 ToM：信念标注与客观真值是否自洽 |
| `secret_reveal_ordering` | Barthes 阐释符码：埋了没揭 |
| `relation_temporal` | 时序知识图谱的**边有效期**：区间倒置 / 同类型重叠 |
| `revelation_regression` ⊘ / `thread_budget` ⊘ | 信息密度 / 价值线分布（**报表项**） |
| `dramatic_irony_available` ⊘† | ToM：可用反讽点（**报表项 + advisory 通道**） |

⊘ 标记的四个是**报表项**：设计上只做通报，源码里不出现 WARN/ERROR，
永远不会让作品不通过。因此它们不计入「N 个校验器」——
把永远不会失败的检查算进门禁数量，是虚报覆盖能力。

† `dramatic_irony_available` 还走 **advisory 通道**（`Report.advisory`）：
它出现在报告里，但不进 `score()`。理由是它属于「向前看」的信号
（「你接下来可以写什么」），把它算进**结构**健康分会产生一个无法解释的
头条指标 —— 故事可写的张力越多，分数越低。
非结构信号（AI 味 / 工艺 / 风格漂移 / 传输度 / 认知负荷）同走这条通道。

**设计原则：校验器只产出 Finding，不抛异常、不阻断生成。** 输出为
「故事体检报告」（0-100 健康分 + ERROR/WARN/INFO 分级 + 修改建议）。

**四态：PASS / FAIL / SKIPPED / CRASHED。** 数据不足的校验器是 SKIPPED，
不是「通过」；校验器自身抛异常是 CRASHED，记进 `Report.crashes`，
**既不扣健康分也不产出 Finding**（代码 bug 不该让作者买单），
但 `verify.py` 断言它在所有输入上为空。
需求声明在 `REQUIRES` 表里（声明式），因此可被测试断言 —— 这防的是
「注册了却永远不会被真正执行」的死校验器。体检报告必须同时报
「评估覆盖率」，否则「健康分 92」可能只是「大部分校验器没数据可查」。

> CRASHED 这一态抓到的真缺陷：`pattern_saturation` 把
> `SceneNode.storylet_ids` 写成了 `Storylet.storylet_ids` ——
> 在没有 storylet 的 IR 上那个生成器表达式根本不求值，**永远不报错**；
> 在有 storylet 的 IR 上必崩。「干净基线全绿」与「这个分支从来没跑过」
> 可以同时成立，而它漂了很久。

> 这不是营销功能，是架构必需件。Wardrip-Fruin《Expressive Processing》对 Tale-Spin
> 的批评至今锋利：**永远不要隐藏模型的推理。** 隐藏覆盖率就是隐藏推理的一部分。

**自证工具**：`scripts/verify.py`（零依赖）跑八类断言 —— registry 完整性、
报表项/advisory 分类可机检、文档计数漂移、死校验器、基线误报、反例净命中率、
校验器崩溃、advisory 空转。
当前：净命中 29/29，两种媒介基线上零误报，计数漂移 0，崩溃 0。

### 5.5 反 slop 模块（`loom/audit/anti_slop.py`）

「AI 味」不是玄学，是可量化的模式集合：否定式煽情、虚假范围、最高级堆叠、
情绪直述、总结式升华收尾、陈词滥调、英文套话。另加三个统计指标：
比喻密度、句长变异系数、句首重复率。

输出 0-100 的「去 AI 味得分」。全部输出为 WARN/INFO——这些规则会产生误报，
不应阻断生成。

### 5.6 Audience Simulator（观众模拟）—— 产品楔子

**这是本方案里最被低估、也最可能成为核心卖点的模块。**

CHI 2025 对 23 位编剧的深度访谈（arXiv 2502.16153）显示：

| 阶段 | 使用人数 | 满意人数 |
|---|---|---|
| 想法/构思 | 8 | 8（全部满意） |
| 结构情节 | 12（最多） | **2** |
| 对白 | 6 | **0** |
| 剧本正文 | 9 | **1** |

编剧想要的四种 AI 角色是 **Actor / Audience / Expert / Executor**。
其中 **Audience（从多观众视角评估）是最高价值、最被渴望、市面上最缺失的能力。**

> 编剧要的不是「帮我写」，是「告诉我这一稿在观众眼里会怎样」。
> 这避开了用户最不满意的位置（写正文），直击最缺失的能力。

实现：一组人格化评审 Agent（按人群细分：核心受众 / 泛用户 / 挑剔型 / 类型片死忠），
对 IR 或文本做多维打分（情感投入、可预测性、爽点密度、卡点位置），
输出观众留存曲线预测。

### 5.7 Render Engine（渲染层，已实现 5 个）

| Renderer | 输出 | 阶段 | 备注 |
|---|---|---|---|
| `render_text` | 小说/网文正文 + 大纲 | 1.0 | 支持按故事时间排序（检查时序倒错效果） |
| `render_fountain` | Fountain 剧本 | 1.0 | 结构信息写入 `[[ ]]` 注释，不污染可拍摄内容 |
| `render_storyboard` | 漫画分镜 JSON | 2.0 | **自定义 schema，填补行业空白** |
| `render_ink` | Ink 脚本 | 2.0 | knot = waypoint，stitch = storylet |
| `render_renpy` | Ren'Py 脚本 | 2.0 | 含好感度/flag 状态机 + 路线图 + 资产清单 |

**渲染器只负责从 IR 生成视图，绝不反向修改 IR。** 场景无 prose 时输出结构占位
（stub）而非空文本，保证 IR ↔ 文本映射始终可追溯。

### 5.8 2.0 运行时（`loom/runtime/director.py`）

**架构依据：Emily Short《Beyond Branching》(2016)。**

v1 方案把 Ashwell 的分支拓扑当参考，但那只回答了「分支内部怎么排」，
没回答「要不要分支」。三种非分支结构才是正确起点：

| 结构 | 谁决定下一块 | 关键性质 |
|---|---|---|
| QBN | 玩家在合法 storylet 中选 | 模块化、可增量添加 |
| Salience | 系统选最贴合当前情境的 | 允许「广覆盖默认值 + 逐步补充特例」 |
| Waypoint | 系统向下一触发点寻路 | **故事自愈** |

**Waypoint 反转了内容经济学**：分支叙事里每多写一段内容，就被迫在下游多写更多
（组合爆炸）；waypoint 里内容越多，穿越话题空间的路越多，故事自愈越高效灵敏。
**这是 2.0 唯一可持续的经济学。**

实现为三层：

```
骨架层   Waypoint 序列（作者锁定的必达节拍）
血肉层   Storylet 池（品质门控 + waypoint 门控 + 显著性排序）
导演层   Director（drama management）
```

**Director 不是可选项。** Short 明确警告：若显著性被用来编排**事件**（而非只是对白），
玩家可能「稀里糊涂地满足了被黑帮干掉的全部前置条件」。本实现的三条约束：

1. **Waypoint 寻路亲和度** —— 推进下一节拍 +0.6，偏离 −0.25
2. **弧光对齐** —— 按声明的弧线形状计算期望方向，对齐加权
3. **安全阀** —— 会不可逆关闭主线的选择 −0.8

**硬不变量（Failbetter 实践）：永远不要给玩家零个选项** —— 必须始终保留一张
可重复触发的底牌（`is_fallback=True`）。

### 5.9 Provenance（溯源与合规）

**这是架构必需件，不是 nice-to-have。**

**标识义务的源头早一年**：《人工智能生成合成内容标识办法》（国信办通字〔2025〕2 号，
网信办/工信部/公安部/广电总局四部门联合）**2025-09-01 已施行** ——
显式标识（文本的起始、末尾或中间适当位置）＋ 隐式标识（**文件元数据**中的生成属性、
服务提供者名称或编码、内容编号）。第九条允许提供不含显式标识的内容，
但须以用户协议明确用户标识义务，并**留存日志不少于六个月**。

《微短剧发展管理办法》（国家广电总局令第 16 号）**2026-09-01 已施行**，
把上述要求落到微短剧场景：AI 参与制作生成的微短剧，制作机构与播出平台须在
每集醒目位置加注「AI 生成」提示标识；确立分类分级管理（按投资额以 30 万/80 万
为两条红线分三类）；一类微短剧须配套发行许可证编号与「苔花」标识。

起点中文网 2026-08-18：**AI 内容占比超过 10% 即处理**（月票榜前 1000 名撤出约 100 本，
其中 27 本均订过万；处置方式是「去流量化」——移出榜单与推荐位，非下架）。
番茄小说 2026-07 单月：拒签 AI 生成/空洞水文类新书 16 万本，下架 5.4 万部，
封禁量产账号 5621 个。

结论：**无法证明 AI 参与度的产品，在中国市场不可交付。**
`ProvenanceLedger` 提供 AI 参与度计量 + 一键合规报告（已实现，见 demo 第 9 节）。

#### 5.9.1 产品红线：不做反检测

调研中必须点名的一件事：同类引擎 InkOS 提供 `revise --mode anti-detect`
（专门的反检测改写）。**Loom 不做这个功能**，且这是**产品红线**，不是偏好。

| | |
|---|---|
| **做** | 如实报告（`submit-check`）+ 创作过程留痕（`process-report`）+ 真的改写方向 |
| **不做** | 按平台阈值反向优化的一键改写；把 AI 内容伪装成人类创作；隐藏阈值与词表 |

理由三条（技术 / 伦理 / 商业）：

1. **技术上必然失败。** 检测已从词汇层转到叙事特征层。起点的维度里有
   「情感锚点偏移率」—— 测试者反馈「哪怕手写大纲、AI 扩写、再手动重写 30% 关键段落，
   系统仍能标记超标」。**表层改写（同义词替换、打乱句长）对付不了叙事层检测。**
2. **伦理上不可辩护。** 帮人把 AI 生成内容伪装成人类创作，是在对抗平台与读者的
   知情权，与本项目的合规定位直接冲突。
3. **商业上自杀。** 一旦被贴上「AI 洗稿工具」标签，起点/番茄的申诉通道、
   平台合作与《反洗稿自律公约》的生态全部关闭。

**分界线**：Loom 帮作者「真的更像人写的」，不帮作者「看起来更像人写的」。
前者是产品，后者是伪造。

**落地方式（避免红线沦为口号）**：

- 正面对替代品已实现：
  `loom/audit/selfcheck.py`（投稿前自检，含「Loom 检不了」的显式清单）与
  `loom/provenance/process.py`（创作过程报告，把免责证据升级为主张证据）。
- `tests/test_redlines.py` 用 **AST** 扫描全部源码，禁止任何反检测的
  函数名 / 命令行标志 / 帮助文案。**判据落在 AST 上而不是文本搜索上**：
  文本搜索会误伤 `engines.py` 里同名的 JSON 归一化工件 `humanize`，
  以及 `anti_slop` 的「去 AI 味」质量指标 ——
  **一个会误报的守卫会被人删掉，而删掉它比没有它更糟。**
- 词表与阈值明文公开在源码里，不做隐藏或编码。

---

## 6. 目录结构

```
loom/
├── ir/
│   ├── enums.py         # 全部枚举（Focalization/EnigmaState/ActantRole/ArcShape...）
│   ├── models.py        # 三层 IR + 场景 + 台账 + 世界 + 记忆 + storylet
│   └── templates.py     # 11 个结构模板插件
├── validators/
│   ├── base.py          # Finding / Report / 注册机制 / REPORTS / ADVISORY
│   ├── structure.py     # 结构校验器
│   ├── consistency.py   # 一致性校验器
│   ├── narrative.py     # 叙事层校验器（信念 / 谎言 / 反讽 / 关系）
│   └── compliance.py    # 3 个平台合规报表项（走 advisory，不进健康分）
├── audit/
│   ├── anti_slop.py     # 反 slop 扫描
│   ├── craft.py         # 四个工艺检测器
│   ├── rhythm.py        # 三个**平台合规**检测器（爆发度/副词密度/对话节奏）
│   └── selfcheck.py     # 投稿前合规自检（法律义务 + 平台画像 + 不可检清单）
├── render/
│   ├── text.py          # 小说正文 + 大纲
│   ├── fountain.py      # Fountain 剧本
│   ├── storyboard.py    # 漫画分镜 JSON
│   ├── ink.py           # Ink
│   └── renpy.py         # Ren'Py
├── runtime/
│   └── director.py      # Waypoint + Storylet + Director + 随机通关测试
├── provenance/
│   ├── meter.py         # 溯源台账 + AI 参与度合规报告
│   ├── telemetry.py     # 决策遥测（作者如何裁决提案）
│   └── process.py       # 创作过程报告（申诉举证：主张证据）
└── cli.py               # 命令行入口
examples/demo_story.py   # 完整 IR 示例（刻意含 5 类缺陷）
scripts/demo.py          # 端到端验证
out/                     # demo 产物
```

**CLI**

```bash
python -m loom.cli audit      out/ir.json          # 故事体检
python -m loom.cli render     out/ir.json -f renpy # 渲染指定媒介
python -m loom.cli outline    out/ir.json          # 大纲（IR 层人工确认）
python -m loom.cli lore       out/ir.json --text "沈砚掏出腰牌"
python -m loom.cli play       out/ir.json --runs 500
python -m loom.cli compliance out/ir.json --json out/compliance.json
python -m loom.cli submit-check out/ir.json --json out/submit.json
python -m loom.cli process-report out/ir.json --out out/process.md
python -m loom.cli templates
```

---

## 7. 里程碑

### M0 · IR Core（2 周）
- [x] 三层正交 IR schema（Pydantic，`extra=forbid`）
- [x] 场景节点 Genette schema
- [x] lorebook 统一字段 schema
- [x] storylet 模型
- [x] 结构模板插件机制（13 个内置模板）
- [x] 校验器框架 + 35 个校验器 + 9 个报表项（含 SKIPPED / CRASHED 语义与覆盖率）
- [x] 客观真值层 + 信念层（ToM）+ 张力点（`loom/ir/tom.py`）
- [x] 提案协议（`loom/ir/proposal.py`）+ 决策遥测（`loom/provenance/telemetry.py`）
- [x] IR 指纹与版本比对
- **出口标准**：IR 能序列化/反序列化往返一致，未知字段被拒绝

### M1 · 想法 → 正文 打通（4 周）
- [x] 6 个渲染器（含单文件 HTML 报告 html.py、按作品报告 export.py、备案清单 filing.py）
- [x] CLI
- [x] LLM 抽象层（Generator 协议 + 离线参考实现 + LiteLLM 接入 + Token 记账）
- [x] 提示词版本化（8 个版本化提示词 + PromptRegistry；`next_scene` 为自动驾驶模式新增）
- [x] Premise Engine（L3 承诺层生成）
- [x] Cast Engine（卡司表 —— 解开结构层与角色层的循环依赖）
- [x] Structure Engine（节拍 → 场景卡，McKee 价值翻转硬约束）
- [x] Character Engine（L2 角色层 + 世界层，在场景之后运行，产出锚：`wound` / `lie`）
- [x] Tension Seeder（**向前看**的引擎：从锚与信念层派生张力点）
- [x] Scripter（场景卡 → 正文，含 lore 注入 + id→名字解析 + CHANGES 自申报分流）
- [x] Critic Loop（生成与修订分离，只自动修文风类）
- [x] Proposer（结构类问题 → Diff 提案，**不自动应用**）
- [x] 编排层 `LoomPipeline`（严格线性，无循环依赖；`decide()` 是提案生效的唯一入口）
- [x] 端到端验证 `scripts/pipeline_demo.py`
- [ ] LangGraph 迁移（当前是手写编排；IR 状态已可序列化，迁移成本低）
- [ ] 人在回路三个确认点：内核 → 节拍表 → 逐章（**均在 IR 层**）
- **出口标准**：一句话想法 → 可读的 5 章正文，IR 可编辑可回滚
- **当前状态**：✅ 已达成（离线参考生成器，6 场 / 92 分 / 0 错误）
  待补：真模型接入验证、LangGraph、人在回路 UI

### M2 · 一致性与反 slop（4 周）
- [x] lorebook 编译器（关键词 + 递归 + 预算）
- [x] 反 slop 模块
- [x] 一致性校验器组
- [x] 伏笔台账自动维护（`LedgerSeeder`：谜题台账 + 知情矩阵自动派生）
- [ ] 设定审计批处理（每 N 章全量扫描）
- [ ] 别名消歧（AI 长篇最高频吃书来源）
- **出口标准**：5 万字稿件的一致性 ERROR 数为 0

### M3 · 观众模拟 + 体检报告（3 周）
- [x] Audience Simulator（人格化评审组 —— 行为参数而非人口统计）
- [x] 观众留存曲线预测（显式 hazard 模型，确定性可回归）
- [x] 确定性信号抽取（每场：翻转 / 钩子 / 开放谜题 / 密度 / 去 AI 味）
- [x] A/B 配对比较（按单场存活率判胜负，剔除篇幅效应）
- [x] 校准接口（单自由度拟合 base_hazard + 残差报告）
- [x] 模型分歧标记（结构模型 vs LLM 判断不一致的场次交人工复核）
- [ ] 情感曲线可视化
- [ ] 故事体检报告 Web 化（React Flow 故事图 + 报告面板）
- **出口标准**：编剧用户认为「体检报告」比「帮我写」更有价值
- **当前状态**：✅ 引擎完成，⏳ 可视化未做
- **必须写清的边界**：LitBench (EACL 2026) 证明零样本 LLM 判断在部分指标上
  接近随机（UNION 48.7%）。本模块不宣称「预测爆款」，只宣称
  「结构性流失预测 + 配对比较」。未校准的模拟器是**先验**，不是预测。

### M4 · 合规与评估（3 周）
- [x] 溯源台账 + 合规报告
- [x] AI 参与度计量接入生成流程（`LoomPipeline.write` 逐场写 Provenance）
- [x] 提示词与模型版本化（`prompt_version` + `model_id` 落到每个场景节点）
- [x] **三个平台合规检测器**（爆发度 / 副词密度 / 对话节奏，走 advisory 不进健康分）
- [x] **投稿前合规自检**（`loom.cli submit-check`：法律义务 + 平台画像 + 不可检清单）
- [x] **创作过程报告**（`loom.cli process-report`：把免责证据升级为**主张证据**）
- [x] **产品红线守卫**（`tests/test_redlines.py`：AST 扫描禁止反检测出口）
- [ ] 内部 rubric 评估 harness
- [ ] 奖励模型（LitBench 风格的 Bradley-Terry / 生成式 RM）
- **出口标准**：能一键导出可提交平台的合规报告
- **当前状态**：✅ 合规报告一键导出已达成（`loom.cli compliance`）；
  ✅ 另有两个更强出口：投稿前自检（`submit-check`）与创作过程报告（`process-report`）；
  ✅ 「不做反检测」已成可机检红线；
  ⏳ rubric harness 与奖励模型未做

> **M4 结束 = 1.0 GA**

### M5 · 结构可导出（4 周，1.5 阶段）
- [x] Ink / Fountain / 分镜渲染器
- [ ] 场景卡加 `preconditions / effects`
- [ ] 引入 quality 概念（QBN 地基）
- [ ] 标注可分支点与付费边界节点
- [ ] 导出目标平台格式（易次元导入格式、橙光引擎格式）
- **出口标准**：一份 IR 能导出可运行的 Ink 脚本

### M6 · 2.0 运行时（6 周）
- [x] Waypoint + Storylet + Director
- [x] 随机化通关测试（500 次遍历 + 覆盖率可视化）
- [ ] Director 弧光权重调优
- [ ] Ren'Py 后端联调（真机跑通一部 galgame）
- [ ] 分支可达性 / 死路 / 结局覆盖率检测
- **出口标准**：随机 5000 次遍历，死路 0，无从未触达的内容块

### M7 · 剧本杀与漫画后端（4 周）
- [x] 分镜 JSON schema
- [ ] 剧本杀后端：多智能体信息不对称状态机（每玩家知识状态 + 隐藏真相 + 揭示阶段）
- [ ] 分镜 → 图像流水线对接（参考图 / LoRA / 共享种子）
- **出口标准**：同一 IR 能产出可玩的剧本杀本子

---

## 8. 测试策略

| 层次 | 方法 | 目标 |
|---|---|---|
| Schema | 往返序列化 + `extra=forbid` + 非法值拒绝 | IR 是硬契约 |
| 校验器 | 每个校验器配正反例 fixture | 不误报、不漏报 |
| 渲染器 | Golden file 快照测试 | 渲染可回归 |
| 一致性 | 注入已知矛盾，验证被捕获 | 检出率 |
| 运行时 | **随机化通关测试**（数千次遍历） | 死路 0、内容死角可视化 |
| 质量 | 成对比较 + 训练过的奖励模型 | 替代零样本 LLM 评委 |
| 人工 | 盲测成对比较协议 | 最终判据 |

> **评估红线：不要 ship 零样本 LLM 评委。** 已核实：UNION 这类连贯性指标得分
> 48.7% ≈ 随机，对创意质量毫无判别力。评委的已知偏差包括长度偏差、顺序偏差、
> 冗长偏好。必须用成对比较 + 训练过的奖励模型（LitBench, EACL 2026）。

---

## 9. 成本模型（10 万字长篇估算）

| 环节 | 调用量 | 模型档位 | 备注 |
|---|---|---|---|
| 内核 + 结构 | ~20 次 | 强模型 | 一次性，值得用好模型 |
| 场景卡 | ~60 次 | 中等模型 | 结构化输出 |
| 正文生成 | ~60 次 × 3000 字 | 强模型 | 主要成本 |
| 审校 + 反 slop | ~120 次 | 中等/小模型 | 可缓存 |
| 观众模拟 | ~10 次 × 5 人格 | 中等模型 | 按需触发 |

**优化手段**：prompt 前缀缓存（IR 的硬约束部分高度可缓存）、
场景卡与正文分离（结构用便宜模型，文笔用贵模型）、
审校走小模型 + 规则优先、批量离线生成。

---

## 10. 风险登记册

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| **平台规则收紧**（起点 10% 规则扩散到更多平台） | 高 | 高 | 定位「AI 帮你写」+ 内建溯源计量 + 一键合规报告 |
| **短剧新规扩展**（《微短剧发展管理办法》后续细则） | 中 | 高 | Provenance 层已前置；AI 参与度做成可配置阈值 |
| 用户不为 AI 生成付费 | 高 | 高 | 付费点放在「体检 + 导出」，不是「生成」 |
| 结构模板被指公式化 | 中 | 中 | 内置 Reagan 实证弧线与起承转合，方法论中立 |
| 奖励模型训练数据不足 | 中 | 中 | 先用内部 rubric + 成对比较，逐步积累偏好数据 |
| 长篇一致性仍不达标 | 中 | 高 | 三层记忆 + 设定审计批处理 + 别名消歧 |
| 换模型导致风格断裂 | 高 | 中 | 模型与 prompt 版本化 + 风格指纹参数化 |
| 2.0 内容经济学失控 | 中 | 高 | Waypoint 骨架锁死必达点 + Director 安全阀 |

---

## 11. 非功能需求

| 指标 | 目标 |
|---|---|
| IR 序列化 | 10 万字体量 IR < 5 MB JSON |
| 单场景生成延迟 | P95 < 25 s（含 lore 编译与审校） |
| 确定性 | 同一 IR + 同一 seed + 同一模型版本 → 完全可复现 |
| 成本上限 | 单次生成可设 token 硬上限，超限即停 |
| 溯源覆盖 | 100% 场景有 Provenance 记录 |
| 合规报告 | 一键导出，含 AI 占比与等级判定 |

---

## 12. 已验证的端到端结果

### 12.1 IR 层（`scripts/demo.py`）

示例刻意含 5 类缺陷，以证明校验器真的在工作：

```
1. 构建三层 IR      3 事件 / 2 角色 / 3 承诺 / 5 场景 / 3 谜题 / 4 lore / 8 storylet
2. Schema 往返      ✓ 指纹一致，未知字段被拒，零增量 StateDelta 被拒
3. 故事体检         健康分 21/100 · 错误 2 · 警告 12 · 提示 7
                    ✗ 谜题被遗弃 / ✗ 场景无价值转折
4. 反 slop          sc3 得分 72/100，命中「空气仿佛凝固」「时间仿佛静止」
5. Lore 激活        探针「沈砚掏出腰牌」→ 激活 4/4 条（含递归链）
6. 五渲染器         novel / fountain / storyboard / ink / renpy 全部产出
7. 运行时           sc1→sc2→sc3→sc4→sc5 走通，寻路 +0.60 生效
8. 随机通关 500 次   零选项事件 0 · 死路 0 · 检出 2 个从未触达的内容块
9. 合规报告         判定 BLOCKED（AI 占比 50% > 10% 阈值）
10. 结构模板        13 个模板并列，好莱坞与东亚体系共存
```

> **第 3 步的数字是 2026-09-19 实测值**（此前快照为 32/100 · 错误 3 ·
> 警告 6 · 提示 8，已失效）。两处变化都是**修正**，不是退化：
>
> * **错误 3 → 2**：`✗ 承诺未兑现` 一行已删除。那条判定基于一个在中文上
>   **恒假**的词法代理（它把整句中文切成一个 token），实测对着正常故事
>   7/7 误报。主题兑现**不可机判**，故该判定被移除，只保留「承诺必须有
>   落点」这个为真的结构判据 —— 本示例的承诺都有落点，所以它不报。
> * **警告 6 → 12**：注册表与校验器自快照以来已扩展（`emotion_curve_match`、
>   `slop:metaphor_density`、`need_revelation_at_climax`、`provenance_coverage`
>   等），这些都是**真实命中**，逐条列在输出里。
>
> 这正是本文档自己那条纪律的实例：**字数与分数快照必须重测，不能沿用。**

第 8 步检出的 `st_hesitate` 与 `st_walk_away` 从未被触达，是**真实的显著性失衡问题**——
这正是随机通关测试存在的意义。

### 12.2 想法 → 正文全链路（`scripts/pipeline_demo.py`）

离线参考生成器，**无需 API key**，因此同时是回归测试基线。

```
想法  一个替人收尸的刀客，发现自己要收的那具尸体是自己十年前的名字
1. 七阶段流水线  前提 7 承诺 → 卡司 2 人 → 结构 6 场（价值翻转 6/6）
                → 角色 2 人 / 行动元 7 → 记忆层 12 条（常驻 10）→ 台账 5 谜题 + 6 事实
                → 张力 3 点（最强「戏剧反讽」0.80）
2. 正文          926 字 / 6 场
3. 结构体检      健康分 93/100 · 错误 0 · 警告 1 · 提示 3
                唯一警告 = AI 占比 100%（这是真实信号，不是 bug）
                → 结构提案 1 条（待作者裁决，**不自动应用**）
4. 观众模拟      加权终局留存 81.7%，4 个人格各自给出不同的抱怨
5. A/B 对比      6 场版 vs 10 场版 → 单场存活率基本持平（最大差 0.4pp），
                终局留存差 4.0~16.6pp → 差距主要来自篇幅
6. 校准          观测 6 点 → base_hazard 0.0478，RMSE 0.0125
7. 合规          BLOCKED（AI 占比 100%，需人工改写至 90% 以上）
8. 八路产物      novel / outline / fountain / storyboard / ink / renpy / ir / audience
9. Token 记账    28 次调用 / 24,200 tokens / $0.1601（粗估）
```

> **本块数字为 2026-09-19 实测值**，与更早的快照有三处差异，都是**修正**：
>
> * **正文 1,106 → 926 字**、**记忆层 6 → 12 条**：离线桩件的随机种子取自
>   场景卡的完整 `model_dump()`，给 `SceneNode` 加字段（`StateDelta.forbidden`）
>   与接入 P1 动态记忆都会改变生成的句子。桩件「确定性但 schema 敏感」，
>   这是它的性质，不是缺陷。
> * **提示 4 → 3**、**健康分 92 → 93**：`commitment_satisfied` 的词法判据
>   已删除（在中文上恒假）。它此前在这里是**沉默**的（该 IR 的承诺都有落点），
>   但那条被删掉的判据曾让 `scripts/demo.py` 的故事 7/7 误报。
> * **tokens 18,518 → 24,200 / $0.1331 → $0.1601**：P1 把动态记忆注入了提示词。
>   多花的是**输入** token —— 这是「IR 始终是真值」的代价，是设计选择不是泄漏。
>
> 结论：**文档里的字数 / 分数 / token 快照必须重新测，不能沿用。**
> 本文件此前已因沿用旧快照漂移过两次。

**第 5 步是观众模拟最有价值的地方**：它没有说「哪个版本更好」，
而是指出「这两个版本在单场抓人力上基本等价（最大差 0.4pp，噪声量级），
终局留存的差距是篇幅效应」—— 一个如果只看绝对分数就一定会误判的结论。
（注意：单场存活率 A 胜 2 / 平 2，**不是全平**；但那 2 场胜差都在 0.3pp 内，
按未校准的 `base_hazard` 读不出意义。报告里两个指标并列，就是让人自己判断。）

**第 1 步的「张力 3 点」是「向前看」能力的第一个可见产物**：
它不是「你写错了什么」，而是「接下来可以写什么」——
每一条都带可执行的下一步建议（schema 层面强制非空）。
第 3 步的「结构提案 1 条」则说明结构类问题不再是打完日志就没了，
而是变成了一个作者可以一键裁决的待办。

---

## 13. 待你确认

1. **媒介优先级**：1.0 先做网文还是先做影视剧本？（影响 Premise/Structure Engine 的重心）
2. **观众模拟是否作为 1.0 的核心卖点**？（我建议是——这是唯一避开用户最不满意位置的功能）
3. **是否接受「AI 占比必须 <10%」作为产品硬约束**？（若接受，产品形态是辅助工具；若不接受，需要另找发行渠道）
4. **2.0 首发媒介**：互动小说（Ink）还是 galgame（Ren'Py）？（前者成本低，后者市场明确）
5. **「健康分」要不要容纳非结构信号？**（**部分已决，仍需你确认边界**）

   现状：`score()` 名为「结构健康分」，但历史上工艺信号（craft / anti_slop）
   与结构缺陷**共用**这一个数字。实测过代价：craft 的 6 条 INFO 让干净基线
   95 → 89，而读者分不清是「结构变差了」还是「多装了 6 个检查」。

   本次已做的处理：新引入 `Report.advisory` 通道，把**新**的非结构信号
   （风格漂移 / 传输度 / 认知负荷 / 向前看的张力点）从 `score()` 里摘出去。
   `dramatic_irony_available` 也从「只进 REPORTS」升级为「REPORTS + advisory」
   —— 因为只进 REPORTS 是不够的：REPORTS 只保证不产出 WARN/ERROR，
   它的 INFO 仍然每条扣 1 分，于是「故事可写的张力越多，健康分越低」。

   **仍需你定**：`mirror_bookends` / `revelation_regression` / `thread_budget`
   这三个**老报表项**要不要一起迁到 advisory？迁了更一致（它们同样是
   「通报性」而非「结构性」），但会动头条数字。

   **【已执行】** 三个老报表项已迁入 advisory，基线 95 → 96（micro_drama 94 → 95）。
   其中 `thread_budget` 单独归为**读数型**（`ADVISORY_READOUT`）—— 它是无条件
   测量不是缺陷，硬塞进缺陷型会逼出一个不存在的反例。详见 `base.py` 的说明。
   我的倾向：**迁**。理由与本次一致 —— 一个不能解释的头条指标比一个
   稍低但语义清晰的指标更糟。但这会改 README/文档里所有基线快照，
   所以等你点头再动。
