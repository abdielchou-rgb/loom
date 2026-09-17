# Æsirian 吸收评估

> 评估对象：`D:\Claude\projects\aesirian`（Æsirian — ToM-driven Human-AI Collaborative Fiction Engine）
> 评估目的：判定其中哪些设计值得 Loom 吸收，哪些明确不要碰
> 评估方式：源码通读（core/ 约 1.9 万行 Python）+ 设计文档交叉验证（蓝图 44KB、V3 战略、自我审计）
> 日期：2026-09-14

---

## 一、总体判断

**一句话：Æsirian 的真正资产不是它宣传的「167 道门禁」，而是四件被它自己低估的东西 ——
CHANGES 自申报协议、递归 ToM 的张力生成、事件冷却矩阵、以及门禁治理三件套。
前者是它自己审计报告里明确说「踩中行业级需求」的四卡+提案制，后三者是它做得比我好、
但没当成卖点的地方。**

两者定位有实质差异，不是同类产品：

| | Æsirian | Loom |
|---|---|---|
| 命题 | 叙事是「作者意图 → 文本介质 → 读者体验」三极的**全息协同** | 叙事是**可编译的中间表示**（Idea → IR → Renderers） |
| 产物 | 长篇小说（Markdown / EPUB） | IR 本体 + 5 种媒介视图（小说 / 剧本 / 分镜 / Ink / Ren'Py） |
| 交互模型 | **作者主导**，AI 提案、作者批准（永不静默改写） | **流水线主导**，IR 层设人在回路确认点 |
| 强度 | 一致性治理、ToM、工艺门禁密度 | 结构正交性、媒介可移植性、离线可验证性、合规计量 |
| 覆盖媒介 | 仅长篇（无剧本/分镜/互动小说导出） | 8 种媒介 + 2.0 运行时（Waypoint/Storylet/Director） |
| 测试 | 109 pytest + 门禁自证样本库 | 2 个端到端脚本（离线确定性） |

**结论：不是「谁抄谁」，是两套互补的资产。** Æsirian 在「长篇一致性」这一个维度上比我深得多；
Loom 在「结构可移植 + 多媒介 + 2.0 运行时」上是它完全没有的。下面的清单只收真正能补我短板的。

---

## 二、必吸收（按价值排序）

### ① CHANGES 自申报协议 —— 补上「结构说 A、正文写了 B」的漂移缺口 ★最高价值

**是什么**（`core/changes_protocol.py`）：
AI 生成每章时，必须在正文末尾附加一份结构化 JSON 变更声明，声明 10 类变化
（`character_state` / `relationship` / `event` / `foreshadowing` / `location_state` /
`item_transfer` / `secret` / `time_progression` / `belief_change` / `new_character`）。
G0 门禁校验声明的格式与完整性，G1–G5 用「**声明 vs 文本提取**」双通道做精确验证。

三条设计原则，每条都值得抄：

1. **不要求 AI 严格遵守格式 —— 容忍并修复偏差。**
   `ChangesParser._repair_json()` 处理中文引号→英文、单引号→双引号、尾逗号、中文冒号。
   支持 4 种格式探测（XML 块 / `---CHANGES---` 标记 / `### CHANGES` 头 / 尾部裸 JSON）。
2. **声明越详细，门禁越准确 —— AI 有动力详细声明。**
   这是激励机制设计：声明是 AI 的「自证」，而自证越细，下游检查越准，AI 因此愿意写细。
3. **声明与文本矛盾时以 KG 为准 —— 防止 AI 虚构声明。**
   声明只是**提示通道**，提取/KG 才是**真值通道**。这条是整套协议的安全阀。

**为什么 Loom 缺**：
Loom 的 `StructureEngine` 在**场景卡层**产出 `state_deltas`，然后 `Scripter` 据此写正文。
**但没有任何机制检查正文是否真的做了场景卡说的那件事。** 这是当前架构里最大的一处
「说一套写一套」漏洞 —— 结构体检 92 分，但正文可能一场戏都没兑现。

**落到 Loom 哪**：
- 新增 `loom/llm/prompts.py` 的 `CHANGES` 提示词（第 7 个版本化提示词）
- `Scripter.run()` 返回值从 `str` 改为 `(prose, declaration)`；或在 `Scripter` 后加一个
  `DeclarationParser`（复用 `_repair_json` 的修复思路）
- 新增校验器 `declaration_consistency`：对比声明的 `state_deltas` 与场景卡的 `state_deltas`，
  不一致即 WARN/ERROR；并把正文里出现的新实体回填到 `ir.bible`
- 新增 `SceneNode.declared: dict` 字段存声明原文（可溯源）

**成本**：中等（1 个提示词 + 1 个解析器 + 1 个校验器 + Scripter 签名变更）。
**风险**：低 —— 声明失败时优雅降级（无声明 = 跳过该校验器，而不是报错）。

---

### ② 递归 ToM 的张力生成 —— 从「检查器」升级为「生成器」 ★最高价值

**是什么**（`core/tom_engine/__init__.py`，686 行）：
维护每个角色的信念状态图，支持 **3 层嵌套**（A 认为 B 以为 C 知道 D 的秘密）。

核心数据结构：
```python
BeliefSource = 目击 / 二手信息 / 推理 / 欺骗 / 误解   # 后两者 → is_erroneous=True
Belief = {proposition, value, confidence, source, updated_at, is_erroneous}
CharacterBeliefState = {
    world_beliefs,          # 对世界的信念
    about_others,           # ToM 第 1 层：A 对 B 的了解
    recursive_beliefs,      # ToM 第 2-3 层：A 以为 B 相信什么
    known_secrets, active_goals,
}
TensionType = 信念冲突 / 戏剧反讽 / 递归错位 / 秘密暴露风险 / 目标冲突
```

**两个关键洞察**：

1. **张力点是「生成资产」，不是「违规报告」。**
   每个 `TensionPoint` 带 `suggestion` 字段：
   > 「制造一场 A 和 B 争论 X 的场景」
   > 「让 A 基于错误的认知做出行动 —— 读者会替 ta 着急」

   这与 Loom 所有校验器的立场相反：Loom 的 24 个校验器全部是**向后看的**
   （你写错了什么），ToM 是**向前看的**（你接下来可以写什么）。
   Loom 的 enigma ledger 追踪「问题」，ToM 追踪「信念分歧」—— 后者是丰富得多的生成源。
   递归错位的张力被赋 0.9（最高），信念冲突按两者置信度均值，戏剧反讽固定 0.8。

2. **戏剧反讽需要「客观真值层」，而 Loom 完全没有这一层。**
   `get_dramatic_irony(reader_knowledge)` 拿角色的 `world_beliefs` 与
   `engine.reader_knowledge`（客观真相字典）比对，输出「读者知道 X，但 A 以为 Y」。

   Loom 的 `KnowledgeFact.known_by` 只是「谁在第几天知道」的映射，
   **没有真值可比**。这意味着 Loom 结构上无法表达戏剧反讽 —— 而这是最基础的悬念机制之一。

**为什么 Loom 缺**：Loom 的 L2 角色层有 `want/need/flaw/goals/states`，
`CharacterState.knows` 是一个 id 列表。没有命题、没有置信度、没有来源、没有嵌套。

**落到 Loom 哪**：
- 新增 `loom/ir/tom.py`：`Belief` / `BeliefSource` / `CharacterBeliefState` /
  `TensionPoint`（pydantic，`extra="forbid"`，与 IR 一致）
- `Character` 增加 `beliefs: list[Belief]`；`NarrativeIR` 增加 `objective_truth: dict[str, Any]`
  （真值层）与 `tension_points: list[TensionPoint]`
- 新增校验器：`belief_consistency`（角色行为 vs 信念）、`dramatic_irony_available`（提示可用反讽点）、
  `secret_reveal_ordering`（秘密揭示顺序）
- **新增生成器**：`loom/pipeline/engines.py` 加 `TensionSeeder` —— 从场景骨架自动派生
  可用的张力点，喂给 `StructureEngine` 作为下一轮约束。这是 Loom 第一个「向前看」的引擎。

**成本**：高（新数据层 + 2 个校验器 + 1 个引擎）。
**风险**：中 —— 需要设计 `objective_truth` 从哪来（建议：由 `PremiseEngine` 的
`ending_anchor` 与 `commitment` 反推，不引入额外 LLM 调用）。

**不要抄的部分**：`validate_action()` 的实现。它是关键词 + 否定词启发式
（`negations = ["举报","背叛","出卖",...]`），且硬编码了 80+ 个 `non_character_words`
（「然而」「值得注意的是」「毫无疑问」…）来抵消上游 NER 把副词误认成角色名的失败。
**那是补丁，不是设计。** 该修的是实体抽取，不是在验证器里堆黑名单。

**不要抄**：`advance_chapter()` 的信念衰减（超过 50 章后 confidence ×0.95，注释写「角色会遗忘」）。
我认为这是错的：**读者不会遗忘，角色也不该因为章节数变多而降低对既定事实的置信度。**
这会产生虚假的 `is_erroneous` 信号。

---

### ③ 事件冷却矩阵 —— 强制工艺层面的多样性 ★高价值、低成本

**是什么**（`core/reader_model/__init__.py` 的 `EventCooldownMatrix`）：
对**叙事模式**做指数衰减冷却。

```python
PLEASURE_TYPES  = 打脸/碾压/降维打击/逆袭/身份揭晓/突破/觉醒/反击/揭穿/震惊/甜/虐/感人/帅
CONFLICT_TYPES  = 身份冲突/资源冲突/价值观冲突/关系冲突/生存冲突/认知冲突
EMOTIONAL_ARCS  = 从绝望到希望/从仇恨到和解/从迷茫到坚定/从恐惧到勇气/从自私到牺牲

record_usage(p)  → matrix[p] += 1.0
advance_time()   → matrix[k] *= 0.7 ** steps        # 每章衰减
get_cooldown(p)  → 查询
get_hot_patterns(threshold=0.5)  → 过热模式（该歇了）
get_recommendations(3)           → 冷却值最低的 3 个（该用了）
check_saturation(window=5, threshold=0.6) → 「模式 X 在过去 5 章出现 4 次（80%）」
```

**为什么 Loom 缺**：
Loom 的 `Director.score()` 有**每个 storylet 的**冷却惩罚，但没有**工艺设备层面**的冷却。
后果：5 个不同的 storylet 可以全是「打脸」，`outcome_distribution` 校验器看不出问题
（它只看 yes/no/yes_but 分布），`mao_repeat_variation` 只在单场景内查重复。

**这是 Loom 唯一一个「生成侧」缺失的约束**：Loom 的 Director 只做选择（在合法块里挑），
不做**模式层面的降权**。加上它，Director 就同时受「弧光对齐」和「模式冷却」两个约束。

**落到 Loom 哪**：
- 新增 `loom/runtime/cooldown.py`：`EventCooldownMatrix`（纯 Python，无依赖）
- `Storylet` 增加 `patterns: list[str]` 字段（声明这个块用了哪些工艺设备）
- `Director.score()` 加入 `-cooldown_penalty * matrix.get_cooldown(pattern)`
- `StoryRuntime.advance_waypoint()` 里调 `matrix.advance_time()`
- 新增校验器 `pattern_saturation`：对**线性叙事**（小说）也能用 ——
  从场景的 `value` + `outcome` + `turning_point` 关键词推断模式，跨章查饱和

**成本**：低（一个 80 行的类 + 一个字段 + 一处 score 改动）。
**风险**：极低 —— 纯加法，不影响现有路径。

**顺带吸收**：`check_saturation()` 的**窗口化重复检测**思路。
Loom 的校验器全部是「全篇统计」，缺「最近 N 场」的窗口视角。

---

### ④ 门禁治理三件套 —— Loom 这一层是薄的 ★高价值、低成本

Æsirian 在这一层踩过的坑，Loom 正在踩（我这次会话就踩了其中一个）。

**(a) registry 单一真源 + 从签名派生 schema**

```python
def _gate_meta(cls) -> dict:
    g = cls(); sig = _inspect.signature(g.evaluate)
    params = [p for p in sig.parameters if p != "self"]
    return {"gate_id": g.gate_id, ..., "params": params}

GATE_CATALOG = {gid: _gate_meta(cls) for gid, cls in ALL_GATES.items()}
GATE_TOTAL = len(GATE_CATALOG)          # 167
BLOCKING_TOTAL = sum(1 for m in ... if m["severity"] == "block")   # 23
GATE_FAMILIES = dict(Counter(gid.split("-")[0] for gid in GATE_CATALOG))
```

文档里的数字**必须**从 `gate_registry_stats()` 取，不许手写。
配套测试 `test_gate_registry_consistency.py` **用正则扫描 README / user-guide /
attribution / api_server / mcp_server / dashboard，任何「NNN 道门禁」都必须等于 registry 计数。**

> **Loom 已经踩了这个坑**：本次会话我写的 README 与 ENGINEERING_PLAN 都写「16 个校验器」，
> 实际是 24 个。Æsirian 用一条测试永久性地消灭了这类漂移。这条测试值得直接抄。

**(b) SKIPPED ≠ PASS**

`STRUCTURAL_GATE_REQUIREMENTS`：约 60 道跨章门禁显式声明必需字段
（如 `"SVT-01": ("entry_value", "exit_value")`）。单章缺字段 → **SKIPPED**
（`passed=True, skipped=True`），而不是静默通过。

> Loom 现状：校验器拿不到数据时返回 `[]`，**与「检查通过」在返回值上完全不可区分**。
> `Report` 里没有 `skipped` 计数。这意味着「24 个校验器全过」这句话在 Loom 里可能
> 只是「大部分校验器没数据可查」。**这是一个真实的、现在就在骗自己的指标。**

**(c) 噪声降噪（NOISE_GATES）**

23 道装饰性门禁 + `_denoise_for_short_chapter()`：短章（<2000 字）把 WARN 降为 INFO。
治理效果：干净文本的 ch1 从 **2 BLOCK → 0 BLOCK**。

> Loom 的 `CriticLoop` 已经做对了一半（只自动修文风类，结构类留人决策），
> 但没有按篇幅/上下文做严重度降噪。

**(d) 死门禁静态检测**

`test_gate_dead_dispatch.py`：静态解析 `safe_eval` 源码，提取所有 `if gid ==` 分支，
断言**每道 registry 门禁要么有 dispatcher 分支、要么声明进 `STRUCTURAL_GATE_REQUIREMENTS`**，
并实际跑 `run_full` 检测「静默假通过」。

> 这是为了修一个真实事故：23 道「registry 有、dispatcher 无」的死门禁。
> Loom 的 `@register` 装饰器结构上更好（不会出现注册了却没实现），
> 但**「校验器被调用了吗」这个断言仍然值得加**。

**落到 Loom 哪**：
- `loom/validators/base.py`：`Finding` 加 `skipped: bool`；`Report` 加 `skipped` 计数与
  `skipped_codes` 属性；`score()` 不计 SKIPPED
- 新增 `loom/validators/base.py::registry_stats()` → `{total, by_severity, by_module}`
- 新增 `tests/test_registry_drift.py`：扫 README / ENGINEERING_PLAN 的「N 个校验器」，断言等于 registry
- 新增 `tests/test_validators_live.py`：对每个 code 跑一遍，断言不是「全部返回空」
- 新增 `tests/test_validator_fixtures.py`：正反例 fixture（见 ⑤）

**成本**：低。**风险**：极低。

---

### ⑤ 净命中率验证口径 —— Loom 的校验器从来没被验证过 ★高价值

**是什么**（`tools/gate_verification/` + `docs/gate-verification-report.md`）：

样本分三族：
- **S1 人工植入**（16 例）：如「十一年→二十一年」时间矛盾、空间 A-3/B-7 混用
- **S2 AI 历史输出**（6 例）：从真实生成文本抽取
- **S3 边界**（10 例）：空文本 / 纯对话 / 超长单段

**关键指标不是命中率，是「净命中率」**：
> 以干净的第 1 章为基线，计算 `净命中 delta = 样本命中 − 基线命中`。
> 同一个 gate 仅当 `warn → block` 升级时才算命中。

结果：Recall 100%（32/32），**净命中率 62%（20/32）**，
干净文本误报 FP = **0/166**，SKIP 覆盖均值 71/166。

报告**诚实列出 12 例零净命中** —— 时间线 / 身份 / 空间 / 事实 / 称谓矛盾，
即 167 道规则门禁**完全没覆盖**的那一类。这个诚实的负面结果直接催生了 ⑥。

**为什么 Loom 缺**：
Loom 有 24 个校验器，**一个 fixture 都没有**。`scripts/demo.py` 里的「健康分 35/100」
只证明了校验器**会报警**，没证明它**报得对**（也没证明它对干净文本不误报）。
「24 个校验器全绿」目前是一个没有证据支撑的宣称。

**落到 Loom 哪**：
- 新增 `tests/fixtures/validators/`：每个校验器至少 1 正例 + 1 反例
- 新增 `tests/test_validator_precision.py`：
  - 断言 `examples/demo_story.py` 的**故意干净部分** FP = 0
  - 断言每个校验器在反例上确实触发，且 severity 符合预期
  - 报告**净命中率**，而非绝对命中率
- 新增 `scripts/gate_report.py`：产出 `docs/validator-verification-report.md`

**成本**：中（24 个校验器 × 2 例 = 48 个 fixture）。**风险**：低，纯增量。

---

### ⑥ CSN 数值事实一致性 —— 中文数值归一化 + 保守抽取 ★中高价值

**是什么**（`core/csn_consistency.py`，217 行，零依赖）：
- 中文数词 ↔ 阿拉伯数字归一化：`十一年→11`、`二十一→21`、`三十岁→30`
  （支持 0–9999，`_CN_DIGITS` + `_CN_UNITS` 逐位累加）
- 保守抽取 `(subject, predicate, value, unit)` 数值事实：
  只认「2-3 汉字人名 + 动作桥词 + 数词 + 单位（年/岁/个月/天/层/号/次/点/楼）」
- 跨章比对：同 `(subject, predicate)` 值不同 → `BLOCK`，带
  `{before, after, conflict_chapter, current_chapter}` 精确定位

**最值得抄的是它的「误报治理」**，这是从失败中学到的：
- 跳过非人名词（这个/那个/整个/公司/房间）
- 跳过含「的」的主语（「曹渊的女儿今年八岁」→「的女儿」是修饰关系）
- 跳过机构后缀（局/公司/学校/医院/政府/部队/委员会）
- **跳过地名后缀**（阳/京/州/城/港/镇/村/区/海/山/河/江/湖/街/路/楼/层/市/省/县/星/国/宫/殿）
- 逐句切分后再扫（避免跨句错误配对）
- 文件头明写「**刻意保守…误报治理优先**」

**为什么 Loom 缺**：
Loom 的 `consistency.py` 有 `knowledge_matrix` / `revelation_regression` /
`timeline_monotonic` / `world_rule_violation`，但**没有任何数值事实比对**。
长篇最常见的吃书形态之一就是数值矛盾（年龄、时长、楼层、编号），
而这类矛盾恰恰是**纯规则能 100% 抓准**的 —— 不需要语义理解。

**落到 Loom 哪**：
- 新增 `loom/audit/numeric_facts.py`：`chinese_numeral_to_int()` + `scan_numeric_facts()` +
  `find_cross_scene_conflicts()`（Loom 的「章」= 场景）
- 新增校验器 `numeric_fact_conflict`（severity=ERROR）
- 新增 IR 字段：`NarrativeIR.numeric_facts: list[NumericFact]`（供增量比对与溯源）

**成本**：低（一个自包含模块 + 一个校验器）。**风险**：低。

**一个改进**：Æsirian 的抽取器靠正则 + 后缀黑名单，仍然脆弱。
Loom 有 IR，**场景卡的 `state_deltas` 已经结构化地记录了数值变化** ——
所以 Loom 可以做得更实：优先用 IR 里的结构化事实，正则抽取只作为**兜底通道**
（正好是 CHANGES 协议的「双通道」思路）。

---

### ⑦ 四卡锚机制 + 「永不静默改写」提案协议 + 决策遥测 ★中高价值

**是什么**：

**(a) 四卡不是四个 JSON，是同一引擎的四个视图**（`core/four_cards.py`，96 行）：
```
CharacterBiography  ← 锚（最高优先级真源）  want / wound / lie / change / voice_traits
FrameworkBeat       ← 张力轨迹              goal / value_turn / tension_source
ChapterBeat         ← 翻转快照              summary / value_turn / causally_linked
SampleStory         ← pilot                 text / transportation_score
```
`FrameworkBeat.tension_source` **直接引用 `tom_engine.TensionType`** ——
四卡与 ToM 是同一个模型的两个投影。`ChapterBeat.causally_linked` 的判据是
「**因为…所以**」而非「然后」。

**(b) 传播方向是不对称的**（`core/diff_engine.py`，763 行）：
```
小传被改  → 重算 框架 + 章节 + 试样    （强制，锚级全量重算）
框架 ↔ 章节 互提提案                    （需作者确认）
试样被改  → 反向提案改小传               （需作者确认）
```
原型是 Pensive 的「**what you pin, the AI must keep**」。

**(c) Diff 数据结构**：
```python
Diff{ id, target_card, field, before, after, rationale, source_card,
      status: pending | accepted | rejected | conflicted }
```

**(d) 决策遥测**（`_record_decision` / `decision_stats`）：
记录每次作者裁决，输出 `accept_rate` + `by_source_card` / `by_target_card` / `by_field` 分布。
目的写在注释里：
> 「把『diff 接受率 / 拒绝率 / 来源→去向分布』变成可查数据，供周级门禁/产品调参
> （避免靠感觉判断『作者是否信任 AI 提案』）」

**为什么 Loom 缺**：
- Loom 的 L2 有 `want/need/flaw/arc_from/arc_to`，**但没有 `wound` 和 `lie`**。
  `flaw` 近似 `lie` 但不是一回事 —— **lie 是一个「角色信以为真的命题」**，
  因此可以对着 ToM 信念图做一致性校验。这是从「形容角色」到「可验证角色」的升级。
- Loom 的 `CriticLoop` **自动应用**修订（虽然只限文风类）。
  Æsirian 的铁律是「永不静默改写」+ 提案 + 遥测。
  两者可以合并：**Loom 保留「只自动修文风类」的边界，但把「结构类」从
  『留给人决策』升级为『生成 Diff 提案给人一键采纳』，并记录采纳率。**

**落到 Loom 哪**：
- `Character` 增加 `wound: str` 与 `lie: str`；`arc_to` 语义改为「高潮时放弃或死守这个 lie」
- 新增 `loom/ir/proposal.py`：`Diff` + `DiffStatus` + `ProposalSet`
- 新增 `loom/pipeline/engines.py::Proposer`：结构类问题产出 Diff 提案（不自动应用）
- `CriticLoop` 返回值加 `proposals: list[Diff]`
- 新增 `loom/provenance/telemetry.py`：采纳率埋点（与现有 provenance 台账同源）
- 新增校验器 `lie_arc_closure`：高潮是否真的处理了这个 lie

**成本**：中。**风险**：中低（需要产品决策：UI 上如何呈现提案）。

---

## 三、可选吸收（视路线而定）

### ⑧ 认知负荷模型（`estimate_update_cost` / `predict_confusion`）

学术权重（Magliano et al. 2024）：
```
pov_switch ×4   time_jump ×2   location_change ×2   new_character ×3   flashback ×3
时间跳变按量级加权：年→×10、月→×3，上限 ×3
已出现过的角色成本减半（×0.5）
累计成本 > 12 → 警告「可能让读者感到困惑」
```

**Loom 的 hazard 模型是「逐场无记忆」的，Æsirian 这个是「窗口累加」的。**
两者互补：Loom 抓「这一场本身弱」，它抓「这一串操作即使每场都不弱，合起来也会压垮读者」。

**值得抄的是「窗口累加」这个结构**，不是那几个具体权重（那些是断言，没有引用来源）。
Loom 的 `SceneNode` 已有 `focalizer` / `fabula_time` / `location`，**可以直接算**：
换聚焦者、时间跳变、地点变化、新角色登场 —— 全部可从 IR 派生，零额外 LLM 调用。

**落到 Loom**：`loom/audience/signals.py` 加 `cognitive_load` 维度；
`AudienceSimulator` 的 hazard 加一个「最近 3 场累计负荷」项。

---

### ⑨ 叙事传输度 6 维评分（`TransportationScore`）

```
传输度 = 0.3×感官细节 + 0.2×对话比例 + 0.15×句长变异
       + 0.15×视角一致性 + 0.1×未解释密度 + 0.1×打断率
```

**两个值得抄的点**：

1. **「太少未解释」也是错的。**
   `unexplained_count == 0` → 得分 30，注释写「完全没未解释 = too clean」。
   这是一个反直觉但正确的工艺洞察：**一切都当场解释清楚的故事没有拉力。**
   Loom 的 `anti_slop` 只惩罚「坏」，不奖励「留白」。

2. **目标带（target band）而非单调指标。**
   `sentence_variety = 100 - |CV − 0.7| × 100` —— 变异系数 0.7 最好，
   太低（单调）和太高（杂乱）都扣分。
   Loom 的 `anti_slop` 有句长 CV 但没有目标带。

**不抄**：那 6 个权重（写死为「学术加权公式」但无引用）、感官词表（20 个词太粗）、
`open_questions`（只是数「？」的个数，不是台账）。

---

### ⑩ 四个工艺检测器（Loom 完全没有）

| 检测器 | 理论来源 | 检测什么 | Loom 现状 |
|---|---|---|---|
| `micro_tension.py` | Maass《Writing the Breakout Novel》 | 段落级张力信号密度（攥紧/屏住/僵住/警觉…）；张力与平淡混同（自我抵消） | 无 |
| `control_illusion.py` | Peter Storr | 6 规则：因果解释延迟 / 模式中断 / 视角跳变 / 信息超载 / 无回报 / 细节缺失 | 无 |
| `reality_effect.py` | Barthes 现实效应 | 抽象名词密度 vs 感官具体名词密度，输出具体化建议 | 无 |
| `show_dont_tell.py` | 展示不告知 | 情绪「告诉」词（他很生气）→ 检查邻近有无生理/动作信号（攥紧/青筋/拍桌） | 只在 `PROSE` 提示词里写了，**无检测器** |
| `ai_tell_detector.py` | InkOS 4 条确定性规则 | 段落均匀度 CV<0.15 / 模糊词密度>3‰ / 过渡词≥3 次 / 连续 3 句同头 | ≈ Loom `anti_slop` |

**最值得抄的是 `show_dont_tell.py` 的「否定式豁免」逻辑**：
检测到「他很生气」后，先看文本里有没有 `SHOW_SIGNALS["愤怒"] = [攥紧, 青筋, 拍桌, 摔, 咬紧, 涨红, 瞪着]`，
**有就不算违规**。这是「检测 + 豁免」而非「纯命中」—— 大幅降低误报。
Loom 的 `anti_slop` 是纯命中式的。

**落到 Loom**：新增 `loom/audit/craft.py`，4 个检测器（`micro_tension` / `control_illusion` /
`reality_effect` / `show_dont_tell`），每个约 60–80 行，复用 `anti_slop` 的
`SlopHit` / `SlopReport` 结构。**成本低，收益明确。**

> **✅ 已落地（2026-09-14）。** 实际 915 行（其中代码 701 行、注释 61、空行 153）——
> 超出 60–80 行/个的估算，超出部分主要是中文工艺词表与「已知局限」文档。
> 接入点**不是**门禁 registry，而是**照 `anti_slop` 的先例**接入 `loom/cli.py`
> 的 `audit` 命令（`report.add(*scan_craft_ir(ir))`）。理由见 §八。
> 关键验收：`show_dont_tell` 的豁免逻辑经**变异测试**证明是承重的
> （掐掉 `_find_show_signal` 后，「有呈现信号的直述」立刻从 0 条变成 1 条 finding）。

---

### ⑪ 风格漂移三维检测（DRESS 框架）

```
overall_authenticity = style_fidelity × content_independence × fluency
passed = overall >= 1 - threshold        # 默认 threshold = 0.15
```

**`content_independence` 是这三者里最关键的维度** ——
「风格保真度」如果只是因为内容没变才保持，那它毫无意义。
基线用多章**中位数聚合**并剔除 2σ 离群（比均值稳健）。

Loom 现在只靠**提示词版本化 + `model_id` 溯源**来保证风格一致，没有任何**度量**。
抄这个能补上「换模型后风格是否真的漂了」这个可测问题。

**不抄**：`fingerprint.py`（2028 行）里大量已死的东西 ——
`NarrativeFingerprint` 声明的 5 个网文 v3.4 字段（`shuang_dian_density` /
`power_progression_speed` / `avg_hook_score` / `twist_density` / `foreshadow_recovery`）
**全仓库无任何赋值，永远是 0.0**；`from .narrative_analyzer import get_analyzer` 与
`from .baselines import load_genre_baseline` 指向**不存在的模块**，
被 `except Exception: pass` 静默吞掉。**只抄 DRESS 公式与中位数基线，不抄这个文件。**

---

### ⑫ 时序知识图谱的边有效期

`Edge{ source, target, type, valid_from_chapter, valid_to_chapter, is_active }`
—— **边是有时间有效期的**，不是永久事实。
`Node` 有 `is_provisional` / `provisional_confidence` / `is_enriched` / `graduated_at`
（临时节点 → 丰富 → 毕业），来自 SAGA 的「临时节点生命周期」。

Loom 的 `Relation` 只有 `{src, dst, kind, polarity, note}`，**没有时间维度**。
「他们第 12 章还是朋友，第 30 章反目」在 Loom 里无法表达，只能覆盖原关系。
`CharacterState` 有时间维度，但 `Relation` 没有 —— 这是一个真实的不对称。

**落到 Loom**：`Relation` 增加 `valid_from_day` / `valid_to_day`；
`Character.state_at(day)` 已有，`StoryBible.relations_at(day)` 照抄这个模式。

**不抄**：`FactSnapshot`（把角色状态/关系/物品持有者/派系平衡打成每章快照）——
内存开销大且与 Loom 的 `CharacterState` 时间线重复。

---

## 四、明确不要吸收

| 项 | 为什么不要 |
|---|---|
| **167 道「工艺门禁」的具体内容** | 大量是关键词计数 + 硬阈值，且入参常是**派生代理量**而非真语义（`PLE-01` 传 `int(tp//2)`、`G3-05` 传 `gd > 0`）。Æsirian 自己的自证报告承认**时间/空间/身份/事实类矛盾 0/12 检出**。密度不等于深度。 |
| **手写 `ALL_GATES` 字典 + 143 分支 `safe_eval` 上帝函数** | 两处维护、必然漂移（他们自己写了 `test_gate_dead_dispatch` 来抓漂移，说明问题真实存在）。Loom 的 `@register` 装饰器结构上更优，不要倒退。 |
| **`validate_action` 的 80 词 `non_character_words` 黑名单** | 上游 NER 失败的下游补丁。正确做法是修实体抽取，不是在验证器里堆黑名单。 |
| **`advance_chapter` 的信念置信度衰减** | 「超过 50 章后 ×0.95」在语义上错误：读者不遗忘，角色也不该因章节数增加而降低对既定事实的置信度。会产生虚假 `is_erroneous` 信号。 |
| **读者模型的文本抽取正则** | `re.findall(r"在([^，。]{1,10})[，。]", text)` 取地点 —— 「在」是最高频汉字之一，必然产出垃圾。`char_mentions = r"([一-鿿]{2,3})(?:说\|想\|看\|走\|笑\|哭\|站)"` 同理。 |
| **`open_questions` 作为悬念台账** | 它只是数「？」的个数（`len(question_markers) > len(open_questions)` 就 append 一条「第 N 章出现的新问题」）。Loom 的 `Enigma` 状态机（posed→delayed→partial→resolved→abandoned）严格优于它。 |
| **`TransportationScore` 的 6 个权重** | 注释写「学术加权公式」但无任何引用来源，权重是断言的。可以抄「目标带」和「太少未解释也是错」这两个**结构性洞察**，不要抄数字。 |
| **`fingerprint.py` 的 `NarrativeFingerprint`** | 5 个字段永远是 0.0（无赋值）；2 处 import 指向不存在的模块，被 `except Exception: pass` 吞掉。这是静默失败的教科书案例。 |
| **四卡的具体字段命名** | `FrameworkBeat` / `ChapterBeat` 与 Loom 的 `PlotLayer` / `SceneNode` 语义重叠。抄「锚 + 不对称传播」的**机制**，不要抄一套并行的数据结构。 |
| **`mcp_server.py`（旧）与 `llm_engine.py`（旧）** | Æsirian 自己的审计判定为「新旧双轨并存」的技术债，旧路径仍在生产链路里。不要参考。 |

---

## 五、合规警示（必须遵守）

### ① 许可证红线 —— 不要抄 wenjian 的门禁内容

`docs/attribution.md` §2 明确记载：

| 借鉴对象 | 许可证 | 状态 |
|---|---|---|
| **InkOS**（完整性写作系统） | **AGPL-3.0** | 曾以完整副本存在于 `reference_notes/inkos_full/`，公开前**物理移出** |
| Novel OS | 未标注 | 曾完整存在于 `archive/novel_os/`，公开前移出 |
| Tianming | 私有 | 仅 2 个 .cs 片段，公开前移出 |

`attribution.md` §5 明写：**「Apache-2.0 与 AGPL 不兼容混用」**。
`engineering-plan-github-020.md` 把这件事列为 🔴 合规级问题。

**对 Loom 的含义**：
- **可以吸收的**：`core/wenjian/` 的**工程模式** —— registry 单一真源、SKIPPED 语义、
  NOISE 降噪、净命中率验证口径。这些是通用工程思想，不受版权保护。
- **不要吸收的**：具体门禁的**文本/词表/阈值**（尤其 `webnovel-pleasure-zh.md` 这类
  craft 知识文件与 `gates/*.py` 里的词表）—— 它们可能携带 InkOS 的 AGPL 传染性。
  Loom 的 24 个校验器**必须自己从方法论原著推导**（这也正是 Loom 现有做法：每个校验器
  的 docstring 标注 McKee / Todorov / Barthes / Genette / 李渔 等真实出处）。

### ② 引用完整性 —— Æsirian 自己做得不够，Loom 要做得更好

Æsirian 的 `attribution.md` **遗漏**了：
- **SAGA**（知识图谱项目）—— 在 `reference_notes/absorbed_patterns.md` 里自述借鉴了
  其「临时节点生命周期（provisional→enrich→graduate）+ 共现防误合并」，
  且 `core/knowledge_graph/__init__.py` 里确实有 `is_provisional` / `graduated_at` 字段，
  **但 attribution.md §2 表格里没有 SAGA**。
- 蓝图 §1.5 引用的 **11 篇学术论文**（WriteHERE / DOME / CreAgentive / EvoSpark / IVIE /
  CASPER / CAE / CHARCO / StoryArcNet / PNAS Sui Generis / EACL 2026）与
  §1.4 的 **20 条方法论**（MICE / Barthes / Storr / Freytag / Campbell / Propp /
  Greimas / Todorov / Genette / Booker / Polti / Pixar / Dan Harmon / Yorke / Egri / Netflix …）
  —— 这些只存在于内部文档，**未进入对外版权声明**。

**对 Loom 的含义**：如果 Loom 吸收上述任何一项，必须在
`docs/attribution.md`（或 ENGINEERING_PLAN 的引用章节）里逐条标注来源。
Loom 现有的做法（每个校验器 docstring 标出处）是对的，继续沿用并扩展到新模块。

### ③ AIGC 标识

Æsirian 有 4 篇内部文档带 **AIGC frontmatter 水印**
（`Label: "1"` + `ContentProducer: 001191440300708461136T1XGW03` + `ProduceID` / `PropagateID`），
属中国 AIGC 内容标识体系，公开前计划剥离。

**对 Loom 的含义**：Loom 的 `Provenance` + `ProvenanceLedger` + 合规报告
（`loom.cli compliance`）在这一点上**已经比 Æsirian 完整** ——
Loom 有逐场景的 AI 占比计量与 `OK/CAUTION/BLOCKED` 判定，
Æsirian 只有文档级水印，没有产品级的 AI 参与度计量。
**这一项 Loom 保持领先，不需要吸收。**

### ④ 值得注意的空白：Æsirian 从未点名中国平台

全库检索（`起点|番茄|墨狐|蜜巢|SillyTavern|阅文|晋江|七猫|掌阅`）在 `.py` 与 `.md` 中
**零命中** —— 中国平台一律以「平台侧工具」「网文行业经验」泛称。

而 Loom 的 ENGINEERING_PLAN 已经写明了：
《微短剧发展管理办法》（广电总局令第 16 号）2026-09-01 施行、起点 2026-08-18
AI 占比 >10% 撤榜。**Loom 在这一块的具体度是它的优势，保持。**

---

## 六、优先级建议

按「价值 ÷ 成本」排序，建议分三批：

### 第一批（立即可做，纯增量，无架构风险）—— ③④⑤⑥ 已落地 ✅

1. ✅ **门禁治理三件套**（④）—— `skipped` 语义 + `registry_stats()` + 文档漂移测试 +
   校验器 live 测试。**已实现，并扩展为「报表项 vs 门禁项」的机检分类。**
2. ✅ **事件冷却矩阵**（③）—— `loom/runtime/cooldown.py`（143 行）+
   `Storylet.patterns` 字段 + `Director.score()` 一处改动。
   补上 Loom 唯一缺失的「生成侧模式约束」。**向后兼容已证明**：
   `patterns` 为空时分数逐位相同（`0.9 == 0.9`）。
3. ✅ **CSN 数值事实一致性**（⑥）—— `loom/audit/csn.py`（267 行）+ 门禁项
   `numeric_fact_consistency`。数值矛盾是纯规则能 100% 抓准的，性价比最高。

4. ✅ **净命中率验证口径 + fixture 库**（⑤）—— **已实现**（24 个反例，
   不是 48 个 —— 见下文「落地记录」为什么减少）。

### 第二批（需要设计决策，价值高）—— ①⑦ 已落地 ✅

5. ✅ **CHANGES 自申报协议**（①）—— 补上 Loom 架构里最大的漂移漏洞
   （结构说 A、正文写 B）。落地为 `loom/llm/declaration.py`（`Declaration` 数据结构）
   + 提示词 `changes@changes.v1` + 门禁项 `declaration_consistency`。
   **降级策略的答案**：声明缺失时**不判定**（SKIPPED），而不是判定为「无漂移」——
   自申报是模型的自愿行为，拿不到声明就说「没漂移」等于把沉默当成合格。
6. ✅ **四卡锚机制 + Diff 提案 + 遥测**（⑦）—— `wound` / `lie` 两个字段进入
   `Character`（提示词 `characters.v3`），让角色变得**可验证**；
   `ir.proposals` + `Diff` 状态机（`pending/accepted/rejected/conflicted`）承载提案；
   `loom/provenance/telemetry.py` 记录裁决遥测。**UI 呈现问题被绕开了，不是被解决了**：
   `cli.py proposals` / `decide` 是命令行出口，产品级呈现仍待决策（见 §13.5）。

### 第三批（大工程，明确收益后再做）—— ② 已落地 ✅

7. ✅ **递归 ToM + 客观真值层**（②）—— 按建议的路径做的：先落 `objective_truth`
   与 `Belief` / `CharacterBeliefState`（`loom/ir/tom.py`），再上全量 ToM。
   现在**递归三层也做了**（`RECURSIVE_MISMATCH` 是 `TensionType` 的一档），
   但 `TensionSeeder` 默认**不播种递归信念** —— 递归信念需要作者显式声明，
   播种器替作者发明一层「我以为他以为」是在制造自己的反例。
8. ✅ **认知负荷窗口累加**（⑧）—— `loom/audience/cognitive.py`，
   `windowed_loads()` 是唯一的累加实现（`scan_ir` 与它共用，不重写第二份），
   `window=1` 退化为逐场负荷、作为与 `hazard` 对比的基线。
   ✅ **工艺检测器四件套**（⑩）—— `loom/audit/craft.py`（915 行）。
   ✅ **DRESS 风格漂移**（⑪）—— `loom/audit/dress.py`（产 `audit:style_drift`）。
   ✅ **Relation 时间维度**（⑫）—— 门禁项 `relation_temporal`。
   **第三批至此全部落地。**

---

## 七、落地记录：④⑤ 实现后的实测结果

写方案和真跑一遍是两件事。④⑤ 落地后，fixture 库**第一次运行就抓到了五个
真缺陷**——其中三个是「Loom 正在骗自己」的那一类：

| # | 缺陷 | 性质 |
|---|---|---|
| 1 | `li_yu_reduce_threads` 窗口宽 3 而判据是「>3 条」——**判据数学上恒为假** | 静默通过：场景数 <12 的故事它一次都没检查过 |
| 2 | `emotion_curve_match` 只看 Pearson r，放行一条**没有谷**的单调上升曲线（r=0.49） | 判据选错：测的是「趋势同向」不是「形状对」 |
| 3 | STRUCTURE 提示词从不告诉模型声明了哪条弧线，却要求它填 `emotion` | 信息断层：要求在信息上不可满足 |
| 4 | 桩件把 emotion 写死成与 `arc_shape` 无关的上升直线 | 自相矛盾：流水线过不了自己的校验器 |
| 5 | 三个函数源码里根本没有 WARN/ERROR，却被算进「24 个校验器」 | 虚报覆盖：**正是我在 Æsirian 167 道门禁上批评过的问题** |

第 5 条值得停一下：**我在评估里批评 Æsirian 的门禁数量虚高，结果 Loom 自己
有 3/24 是永远不会失败的。** 这个同构错误是 fixture 库抓出来的，不是我自己
想出来的 —— 这就是为什么「验证口径」本身要工程化。

### 三处与方案不同的决定

1. **反例 23 个而不是 48 个。** 方案里按「每个校验器 × 正反例」估了 48。
   实际做的是一条**正例基线**（流水线产出，覆盖两种媒介）+ 每个门禁项一条反例。
   理由：手写正例会不自觉地把校验器实现细节抄进去，变成「为了通过校验器而写的
   样本」；用流水线产出的 IR 当基线才能问出真问题——**它会不会对着一个正常故事
   乱报警**。48 条手写样本的信息量低于 1 条流水线基线 + 21 条反例。
2. **判据从「布尔触发」改成「严重度升级」。** 原口径是「变异后触发了就算命中」。
   但 `thread_budget` 在健康时也输出 INFO，只判「有输出」它永远命中 ——
   那是在给自己的指标注水。现在要求 `变异严重度 > 基线严重度`。
3. **基线覆盖两种媒介。** 只用一个小说基线时，`hook_cadence` /
   `paywall_gate_present` 永远 SKIPPED，它们的「没问题」是**没跑过**。
   加了短剧基线后才真的被验证。

### 实测数字

```
registry 完整性        24 个 code 全部声明了数据需求
报表项分类            3 个（源码扫描断言无 WARN/ERROR）
计数漂移（文档+脚本）  0 处漂移（修掉了 README/方案里的 24、demo.py 里的 14）
死校验器              0 个（24/24 至少在一种媒介基线上可评估）
基线误报              0（novel 95/100 · micro_drama 94/100，均 0 错 0 警）
反例覆盖              22/22 门禁项
净命中率              100%（22/22）
```

一个额外的收获：新的「转折点位置」判据在 `scripts/demo.py` 那份手工构造的
`听雪楼` IR 上，抓出了一个**旧的 Pearson 判据放过了**的形状违规
（声明谷底在 42%，文本谷底在 75%）。判据变强，立刻在真实样例上见效。

---

## 八、落地记录（二）：③⑥⑩ 与一次并行派发实验

### 做了什么

| 项 | 产物 | 验证 |
|---|---|---|
| ③ 事件冷却矩阵 | `loom/runtime/cooldown.py`（143 行）+ `Storylet.patterns` + `Director.score()` | `tests/test_cooldown.py` 45 断言；**向后兼容逐位相同** |
| ⑥ CSN 数值事实 | `loom/audit/csn.py`（267 行）+ 门禁 `numeric_fact_consistency` | `tests/test_csn.py` 64 断言；净命中 22/22 |
| ⑩ 四个工艺检测器 | `loom/audit/craft.py`（915 行）+ `cli.py` 接入 | `tests/test_craft.py` 75 断言；豁免逻辑经变异测试 |

合计新增单元测试 **184 项断言**，`scripts/verify.py` 从 20 项升到 **24 项**断言全过。

### 一个方法论实验：并行派发

`ultrawork` 这个触发词的实质是**并行代理模式**。但并行派发的前提是
「任务之间**没有共享状态**」——先做了文件所有权分析，结论是：
**只有 ③ 与 ⑩ 两个域是真正独立的**（前者只碰 `loom/runtime/` + 一个 IR 字段，
后者只碰 `loom/audit/` 新文件）。

其余项**不能并行**，因为它们都碰 `loom/ir/models.py`（①⑦⑫）或
**共享门禁治理状态**（`REQUIRES` 表 + fixture 库 + 文档计数）。
后者的冲突是致命的：两个代理同时改 `tests/fixtures.py` 与文档计数，
合并结果会互相覆盖，而这类错误**不会被任何测试抓到**（因为每个代理各自跑都是绿的）。

所以派发的是 2 个，注册（registry / fixture / 计数）留作串行。
这本身就是那条铁律的实例：**「能不能并行」不是感觉问题，是文件所有权问题。**

### 集成时抓到的问题（并行派发之后才暴露）

1. **`craft.py` 差点成为死代码。** 原本打算把它注册进门禁 registry，
   但先查了先例：`anti_slop` **不是**门禁，它被 `cli.py` / `signals.py` /
   `CriticLoop` 三处消费。照先例接入 `cli.py audit`，而不是新发明一种接法。
   ——**「跟随先例」比「看起来合理的接法」更可靠，因为先例已经被验证过。**
2. **`craft.py` 的 docstring 说错了一句话。** 它写「INFO 只做通报，不参与判断」，
   但 `Report.score()` 是 `100 − 12×ERROR − 4×WARN − **1×INFO**` ——
   INFO **会**扣分。实测：干净基线 novel 95→89、micro_drama 94→88。
   这句话只对 `passed()` 成立，对 `score()` 不成立。**已改成精确表述并标注待决。**
3. **计数漂移又出现两处，而 `verify.py` 抓不到。** README 写「**六**个引擎」
   （实际 8）、`test_csn.py` 写「**56** 项断言」（实际 64）。
   抓不到的原因是漂移检查的两个盲区：
   * 模式只匹配 `\d+` —— 「六」是中文数词，**静默跳过**；
   * 模式只覆盖「个校验器 / 个报表项」，引擎数与断言数**根本不在扫描范围**。

   **修复：把 `verify.py` 第 4 节从 2 类扩到 4 类**（新增「个引擎」「个反例变异」），
   数字部分同时吃阿拉伯数字与中文数词（复用 `csn.normalize_cn_number`，
   不重写一遍），并从源码派生真值（`ast` 数顶层类 / `len(MUTATIONS)`）。
   顺带发现一个陷阱：泛化的「个反例」模式会命中 `verify.py` 自己建议文案里的
   「补**一个反例** fixture」，故锚在具体说法「个反例变异」上。

   **检查器本身也做了变异测试**：改成「六个引擎」→ 红，改成「八个引擎」→ 绿，
   改成「48 个反例变异」→ 红。**一个抓不到东西的漂移检查器等于没有检查器。**

### 待决（留给作者）

`score()` 的语义是「**结构**健康分」，而 `craft` 与 `anti_slop` 都是**非结构性**信号，
却按统一规则扣同一个分 —— 「健康分」实际混入了工艺噪声。三条出路：
(a) 维持现状；(b) 让 INFO 不扣分（两条基线回到 100，但 README/verify 的数字要同步改）；
(c) 把工艺项从结构分里拆出来单列。**这是产品决策，未擅自改动。**

---

## 九、落地记录（三）：两个「向前看」的引擎

这一轮把评估里价值最高、也是最后剩下的两块补完了：**①②⑦**（以及顺带收尾的 ⑧⑩⑪⑫）。
至此 §六 的三批清单**全部落地**，Loom 的门禁不再是清一色向后看。

### 做了什么

| 项 | 产物 | 验证 |
|---|---|---|
| ① CHANGES 自申报 | `loom/llm/declaration.py` + 提示词 `changes@changes.v1` + 门禁 `declaration_consistency` | 反例 fixture + `verify.py` 净命中；声明缺失 → SKIPPED 由 `REQUIRES` 表声明 |
| ② 客观真值层 + ToM | `loom/ir/tom.py`（`Belief` / `CharacterBeliefState` / `TensionPoint` / `derive_tension_points`）+ 门禁 `belief_consistency` / `secret_reveal_ordering` / `lie_arc_closure` / `dramatic_irony_available` | `tests/test_tom.py` 69 断言 |
| ⑦ 四卡锚 + Diff 提案 + 遥测 | `Character.wound` / `Character.lie` + 提示词 `characters.v3`；`loom/ir/proposal.py` 状态机；`ir.proposals` / `accept_proposal` / `reject_proposal`；`loom/provenance/telemetry.py` | `tests/test_proposer.py` 116 断言 + `tests/test_telemetry.py` 43 断言 |
| **② 的引擎化** | `TensionSeeder`（流水线第 8 阶段，**向前看**） | `tests/test_tension.py` 55 断言 |
| **⑦ 的引擎化** | `Proposer`（`CriticLoop` 尾部产出待裁决提案，**不自动应用**） | 同上 |
| ⑪ DRESS | `loom/audit/dress.py`（`audit:style_drift`） | `tests/test_dress.py` 61 断言 |
| ⑫ Relation 时间维度 | 门禁 `relation_temporal` | 反例 fixture + `verify.py` 净命中 |

本轮**新增三个测试文件**（`tests/test_tension.py` 55 + `test_proposer.py` 116 +
`test_devices.py` 49 = **220 项断言**），并改造了 `tests/fixtures.py`（收尾改为
幂等「补齐」而非「构造」）。加上既有的 9 套，全量 **12 套 · 745 项断言**。
`scripts/verify.py` 从 31 项升到 **45 项**断言全过，注册表 32 = **28 门禁 + 4 报表项**。

### 这两个引擎为什么是「第一个向前看的」

所有既有校验器问的是「**你写错了什么**」——输入是已完成的 IR，输出是缺陷。
`TensionSeeder` 问的是「**接下来可以写什么**」：它从锚（`wound` / `lie`）与信念层
派生 `TensionPoint`，每个点**必须带 `suggestion`**（「下一场怎么用」），
这是 schema 强制的 —— 只报告「这里有冲突」而不说「怎么用」，
等于把谜题账本做了两遍。

`Proposer` 问的是「**结构问题该由谁决定**」：`CriticLoop` 仍然只自动修文风类问题，
结构类问题转成 `Diff` 提案进入 `ir.proposals`，等作者裁决。
**「永不静默改写」在这里是可机检的性质，不是态度**：
`Diff.after` 在 `status` 变成 `accepted` 之前始终只是「提案内容」，
而唯一的翻转入口是 `accept_proposal()` / `reject_proposal()`。
`tests/test_proposer.py` 直接比对 `model_dump()` 在 `Proposer.run()` 前后、
以及 `decide(accept=True)` 前后的**逐字节相同** —— 采纳是**决定**，不是**应用**。

### 抓到的四个缺陷（两个是潜伏的，一个是真崩溃）

| # | 缺陷 | 为什么之前没被发现 |
|---|---|---|
| 1 | `pattern_saturation` 在任何带 storylet 的 IR 上崩（`st.storylet_ids`，字段其实在 `SceneNode` 上） | 列表推导遍历**空的** `ir.storylets` 时**函数体从不求值**，所以永不报错；基线全绿与「这条分支从未运行」可以同时为真 |
| 2 | `Proposer` 的 id 不确定 → 提案每跑一轮翻一倍（8 → 16） | 消歧后缀取自 `ir.proposals` 的**当前内容**，重跑即重新分配 |
| 3 | `skip_prefixes` 五个前缀错两个 —— 风格漂移与「低运输性」被排成**待作者裁决的结构缺陷** | 手写前缀表必然漂移；`dress.py` 产 `audit:*`、`cognitive.py` 产**无前缀**的裸 code |
| 4 | `pattern_saturation` 能从**单次观察**判定「饱和」（分母是「可识别场景数」，1 场即频率 1.0） | 原语把「算出来」当成了「该说话」 |

第 1 条最值得停一下：**崩溃被 `run_all` 包装成了一条普通的 INFO Finding。**
一个代码 bug 伪装成了一条创作观察 —— 它在报告里的样子和「这里写得有点平」完全一样。
这就是下面两处架构改动的原因。

### 两处架构改动

**1. 第四种状态 `CRASHED`。** 状态从 PASS / FAIL / SKIPPED 扩为四种。
崩溃**不产出 Finding**，记进 `Report.crashes`，因此**不扣作者的健康分**。
效果可测量：`scripts/demo.py` 的分数 31 → 32，差的正是那条被移除的人造 Finding。
`verify.py` 现在在「两条基线 + 示例 IR + 全部 30 个变异」上断言 `crashes` 为空 ——
**因为一个被吞掉的崩溃读起来和一条普通发现一模一样。**

**2. `ADVISORY` 通道。** 这是 §八「待决」里那个 `score()` 问题的答案，
但只回答了一半，且边界划得很清楚：
`REPORTS` 保证的是「不会产出 WARN/ERROR」（源码可扫），
而它的 INFO **仍然每项扣 1 分**（`score() = 100 − 12·ERROR − 4·WARN − 1·INFO`）。
后果是：**一个故事里可写的张力越多，它的健康分越低** —— 一个无法解释的头条指标。
所以新增的 `dramatic_irony_available` 走 `ADVISORY`（`Report.advisory`，不计分），
并在 `verify.py` 里加了不变式 **`ADVISORY ⊆ REPORTS`** ——
一个会产出 WARN 的「只通报」校验器会被静默吞掉，那比分类错误更糟。

**§八 里那三个老报表项（`mirror_bookends` / `revelation_regression` / `thread_budget`）
故意没动**：迁移它们会改动每一份已记录的基线快照，属产品决策，见 §13.5。

### 实测数字（本轮结束时）

```
registry 完整性        32 个 code 全部声明了数据需求（28 门禁 + 4 报表项）
按模块                 consistency 8 · narrative 6 · structure 18
净命中率              100%（28/28）· 死校验器 0 个
崩溃                  0（3 个探测 IR × 30 个变异，Report.crashes 全空）
基线误报              0（novel 95/100 · micro_drama 94/100，均 0 错 0 警）
advisory 非空性        1/1（向前看的报表项必须真的在基线上说话）
scripts/verify.py     45/45 断言
单元测试              12 套全绿 · 合计 745 项断言
模块导入              48/48 干净
```

**「加法是纯的」已证明**：干净基线**未变**（novel 95、micro_drama 94，均 0 错 0 警）、
`pipeline_demo.py` 仍然正好 **92/100**、`scripts/demo.py` 32/100
（与上一轮记录的 31/100 结构相同，只差那条被移除的人造 Finding）。

### 三处诚实的偏差（记录，不掩饰）

1. **fixture 仍会注入 `known_secrets` 与 `Relation`。** 因为流水线**本来就不该**
   发明秘密 —— 秘密必须来自作者声明。`TensionSeeder` 的能力边界（不播种秘密、
   不播种递归信念）是**刻意的**，不是没做完：播种器替作者发明一个秘密，
   会让 `secret_reveal_ordering` 输出一条作者看不懂的 WARN。
   **播种器制造自己的反例，是本项目最该避免的那种自欺。**
2. **fixture 的收尾 4（`ir.proposals = []`）只为 fixture 存在。**
   提案必须与产出它的那份体检同源；生产路径上没有「体检之后改 IR」这一步。
3. **`verify.py` 的覆盖率分母仍是注册表。** 五个未注册的散文分析器
   （`anti_slop` / `craft` / `dress` / `transportation` / `cognitive`）
   不在分母里 —— 因为注册才是治理边界。这一条**尚未被报告出来**，是已知的缺口。

### 一处方法论收获：漂移检查器本身也要变异测试

扩展 `verify.py` 第 4 节的扫描范围（新增「个渲染器」「个版本化提示词」「个模板」）
**当场**就抓到一处陈旧断言：方案里写「6 个版本化提示词」，实际 7。
这不是巧合 —— 它说明**检查器的扫描范围本身就是覆盖率**：
不在范围内的数字，写得再错也是绿的。检查器改完后立刻做了变异测试
（`11 个模板` → 12 红、`7 个版本化提示词` → 「六」红、`五个渲染器` → 「六」红、还原 → 绿）。

---

## 附：一句话总结

> Æsirian 值得抄的不是它的门禁数量，而是**四个「向前看」的机制**：
> CHANGES 让 AI 自证、ToM 把信念分歧变成可写场景、冷却矩阵告诉下一个该用什么模式、
> Diff 提案让作者的信任变成可测量数据。
> Loom 在补完这一轮之前的门禁**全部是向后看的** —— 这是两套系统最本质的差距，
> 也是「帮你写」和「和你想」的分界。
>
> 补充（④⑤ 落地后）：**「向后看」这件事本身也需要被验证。**
> Loom 的门禁在实现 ④⑤ 之前，有 1 个判据数学上不可满足、
> 1 个判据选错了统计量、3 个根本不会失败却计入了数量。
> 门禁的可信度不是靠方法论的引用撑起来的，是靠**净命中率**撑起来的。
>
> 补充（①②⑦ 落地后）：**四个机制都已经在了，但它们都栽在同一类坑上。**
> 本轮抓到的四个缺陷里，两个是「代码崩了却伪装成一条发现」，
> 一个是「检查器自己的清单漂移了」，一个是「算得出不等于该说话」。
> 共同点是：**它们都能在测试全绿的情况下存活。**
> 所以这一轮真正的产出不是两个引擎，是三条新的不变式 ——
> 崩溃必须是自己的状态且不扣分、派生清单胜过手写清单、
> 证据不足时不判定。**一个向前看的报表项如果从不运行，
> 和一个不存在的报表项无法区分** —— 这条也进了 `verify.py`。
