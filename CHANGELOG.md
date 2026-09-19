# 变更日志

> **来源说明**：1.0.0 之前的条目是从代码现状 + 开发过程记录**重建**的
> （当时确实还没有版本控制），只记录**有实测依据**的里程碑。
>
> 自 2026-09-18 起本仓库有 git 历史（`main` 分支），
> 之后的条目可从提交历史核对。**这份文件不再需要靠重建维护。**
>
> 版本号遵循语义化版本。`keel --version` 可查当前版本。

---

## [未发布] — 2026-09-19 · 更名：Loom → 龙骨 / Keel

定位：**改名，不改行为。** 这是一次纯机械的标识符替换，功能零变化。

### 为什么改（冲突面是查过的，不是感觉）

| 名字 | 判定 | 证据 |
|---|---|---|
| **Loom** | ❌ | 已被 **Atlassian 收购**（2023-11 交割）；开发圈里 "Loom" 还指 **Java Project Loom**（虚拟线程） |
| **Fabula** | ❌ | 同赛道直接占用：`fabula.productions` 做「剧本→知识图谱」，`fabulaos.io` 自称 "AI-native OS for story development" |
| **Textus** | ❌ | 与 `TextUs`（短信营销软件）读音完全相同 |

Fabula 是最自然的选择（fabula / syuzhet 是叙事学里 IR 与文本的原始对立，
正是本项目「IR 是本体、文本只是视图」的术语来源），但正因为贴切，
同赛道已经挤满了。**越是精确的名字越可能已经被占。**

选 **龙骨 / Keel** 的理由：吊顶与船体里那层**看不见却承重**的结构，
精确对应「决定作品站不站得住的是正文之下那层结构」；中文母语可读，
且未被同赛道占用。

### 改名范围（全量）

| | 从 | 到 |
|---|---|---|
| 包 | `loom/` | `keel/` |
| 发行名 | `loom-narrative` | `keel-narrative` |
| console script | `loom` | `keel` |
| 启动器 | `scripts/loom.bat` / `loom.sh` | `scripts/keel.bat` / `keel.sh` |
| 单文件包 | `loom.pyz` | `keel.pyz` |
| 远端 | `github.com/abdielchou-rgb/loom` | `github.com/abdielchou-rgb/keel` |
| 公开类 | `LoomModel` / `LoomPipeline` | `KeelModel` / `KeelPipeline` |

**破坏性**：`import loom` → `import keel`；上述两个类名已变。
1.0.0 尚未对外发布，故不另发大版本号。

### 改名怎么做的（以及为什么这样做）

先枚举**所有**含 `loom` 的标识符再替换，而不是直接上 `\b` 词边界：

```
loom 778 · Loom 535 · LoomModel 55 · LoomPipeline 40 · LOOM_PKG 4
loom_version 3 · loom_api 3 · loom_main 2 · _loom_shim 2
LoomHTTPRequestHandler 2 · loom_resume_ 1 · LoomLocal 1
```

`\bloom\b` 会**静默漏掉** `loom_version` / `loom_api` / `LOOM_PKG` / `_loom_shim`
（`_` 是词字符，两侧都不构成词边界）。枚举后确认**零误伤**
（无 `bloom` / `gloom` 之类），才用大小写敏感的全量替换。

### 顺带修掉的一处过期断言

`pyproject.toml` 里写着「刻意不写 Homepage：本仓库没有 git 远端」——
这条理由在 2026-09-19 建仓之后**就不成立了**，而它会让后来者以为
「不写 Homepage」仍是一个有效决定，从而没人去补。
现在远端确实存在，已补上真实的 `Homepage` / `Repository` / `Issues`。
**留一条过期的理由，比没有理由更坏。**

### 验收（改名后实测）

```
scripts/verify.py          通过 86 · 失败 0
34 个测试文件               34 / 34 全绿
scripts/demo.py            exit 0
scripts/pipeline_demo.py   exit 0
scripts/check_launch.py    ALL PASS（已改为检查 `python -m keel`）
keel.pyz                   keel 1.0.0
```

---

## [未发布] — 2026-09-19 · 撤回一个恒假的判据（含两处连带修正）

定位：**修掉 P0.5 引入的假门禁，并把它连带的两个问题一起清掉。**

上一轮（P0.5）把 `commitment_satisfied` 从「恒真的假门禁」改成
「承诺措辞 vs 场景文本的词法匹配」。方向对（不再无条件 `satisfied = True`），
**但换上的判据在中文上恒假**，于是变成了「恒假的假门禁」—— 比原来更糟，
因为它对着正常故事开火。

### 实测证据（不是推理）

| 观测 | 数值 |
|---|---|
| `scripts/pipeline_demo.py` 健康分 | **92 → 21**（错误 0 → 6） |
| 该故事 7 条承诺的误报 | **7/7 全部报「未兑现」** |
| 分词实际产出 | `「信任不是一种判断，而是一种交付。」` → `['信任不是一种判断', '而是一种交付']` |
| 逐条核对的场景文本 | `sc4.turning_point` 里**有**「信任」二字 —— 概念命中，token 不命中 |

根因：`re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+")` 在中文上没有词边界，
**整句被切成一个 token**（6~8 字），正文永远不可能逐字复现整句。
退一步用字符二元组（`drift._shingles` 的既有做法）也不行：
实测重叠率只有 0.05~0.10，**没有任何阈值**能把「兑现了」与「没兑现」分开。

结论：**主题兑现不可机判。**

### 改动

| | 改动 | 为什么 |
|---|---|---|
| `validators/structure.py` | 删除 `_commitment_evident`；`commitment_satisfied` 只保留结构判据（`must_hold_at` 必须指向真实场景） | 铁律 24：证据不足时**不判定**，而不是判定为通过、更不是判定为失败 |
| `validators/drift.py` | 论点面改读 IR 的 `satisfied` **声明**，不再现场猜 | 判不出来就不要假装在判 |
| `pipeline/auto.py` | 删除 `_refresh_commitments`、`_commitments_done`、`STOP_COMMITMENTS` | 见下「两个连带问题」 |
| `ir/models.py` | 给 `satisfied` 字段与 `unsatisfied()` 补语义 docstring | 它是**声明式**字段，不是引擎算出来的判定 |
| `render/html.py` | 报告里「已兑现 / 未兑现」→「落点 + 作者标记」 | 印「未兑现」等于把一个声明说成判定结果 |
| `tests/fixtures.py` | 删除「收尾 5」注入；变异改用「落点指向不存在的场景」 | 原注入是**循环论证**：往 fixture 里注入答案好让检查变绿 |
| `tests/test_drift.py` | 撤回为迁就坏判据而加的注入 | 同上 |
| `ENGINEERING_PLAN.md` | §12 两处快照全部重测 | 文档里的分数/字数/token 快照必须重测，不能沿用 |

### 两个连带问题（都是 P0.5 引入、当时都没被发现）

1. **`STOP_COMMITMENTS` 成了永不触发的死分支。**
   旧 `_refresh_commitments` 恒返回 False → `_commitments_done` 恒为 False
   → 自动驾驶的停止判据 #2 从来没生效过。**「干净基线全绿」与「这条分支
   从未运行」可以同时为真**（铁律 33）。

2. **改成结构判据后会恒真。**
   `_bind_commitments` 按「第几场 / 共几场」的**比例**铺锚点，而
   `AutoWriter` 在第一场刚建好时就来绑 —— 此时场景列表长度为 1，
   于是**全部 7 条承诺都落到 `sc1`**（实测）。写满第 1 场后
   「全部承诺已兑现」立刻为真，**整条自动运行在第 1 场就停了**。
   若改成按计划跨度铺开，最后一条锚点落在计划末场，停止时刻与
   `target_scenes` **完全重合** —— 那是冗余判据，不是独立判据。

   → 恒真的判据与恒假的判据一样没用。**删掉**，收敛信号诚实地剩三个
   （场数 / 结局锚点 / 预算闸）。`satisfied` 字段保留为声明式字段，
   仍被 `drift` 与 `preflight` 消费，只是**没有任何引擎再替作者填它**。

### 自证

`scripts/verify.py` **通过 86 · 失败 0**。变异测试 `_m_commitment` 已重定向到
结构判据（落点指向不存在的场景），并在基线/反例两侧都验证过严重度升级。

## [未发布] — 2026-09-17 · 自动驾驶 + 决策留痕闭环

定位：**「AI 替你写」的自主模式，配一套能拿去申诉的人类判断记录。**
合规定位已按作者决策改为接受「AI 替你写」，但**溯源必须诚实** ——
这一轮把「诚实」从态度变成字段。

### 新增：自动驾驶（`keel run`）

| | 改动 | 为什么 |
|---|---|---|
| `keel/pipeline/auto.py` | 自动推进 **IR**（不是续写文本），停止判据全部从 IR 派生 | IR 静止而文本变长 = 校验器在检查一份虚构 |
| `keel/pipeline/preflight.py` | 起飞前体检计划（5 项） | 自主性会**放大**计划质量：坏计划 × 自动驾驶 = 很长很长的烂故事 |
| `keel/pipeline/budget.py` | 场数 / token / 成本 / 时长四轴预算闸 | 没有预算的「一直写」是失控，不是功能 |
| `keel/pipeline/checkpoint.py` | 原子写检查点，损坏 ≠ 不存在 | 崩在第 47 场要能从 47 续，重跑不可接受 |
| `keel/validators/drift.py` | `drift_guard`：全局漂移/注水检测 | 现有校验器全是逐场局部的，只有它问「整体还在不在路上」 |
| 收尾型 vs 进行中破损 | `_CLOSURE_CODES` 区分二类 | 拿「到结束时兑现了吗」去判断未完稿 → 第 2 场必然误停 |

### 新增：决策留痕（主张证据）

| | 改动 | 为什么 |
|---|---|---|
| `Diff.proposed_at` / `decided_at` / `decided_by` | 三个举证字段 | 一条只写着 `rejected` 的记录说不出「谁在何时驳回了它」—— 那不是证据，是主张 |
| `keel decide` **默认写回原文件**（`--no-save` 才不落盘） | 以前只有传 `--out` 才保存 | 不落盘的裁决不是裁决：人做了判断，系统没记住 |
| `keel run --resume-from` | 续跑采用人工修订版，**检查点让位** | 检查点存的是机器暂停那一刻的 IR，直接采用会把人的裁决无声复活成 pending |
| `keel/clock.py` | 全项目唯一取时钟处，本地时区 + 偏移 | 举证时刻要能和文件的 mtime、平台后台时间对上；散着取会拼不成时间线 |
| `DecisionRecord.decided_at` → `story_at` | 与 `Diff.decided_at` 同名不同义，已分开 | 一个是故事内标签（调参），一个是墙钟（举证）；同名必然被用错 |
| 台账从 IR 派生 | `decisions.json` 不再另存一份状态 | 两份必然漂移，且漂移方向永远是「台账比 IR 好看」 |

### 新增：动态记忆 / 修复预算 / 状态转移语义 / 校验器自检 / 一键启动（ultrawork 全量推进）

| | 改动 | 为什么 |
|---|---|---|
| `keel/pipeline/memory.py` | `NarrativeMemory`：场景级增量状态（谁在哪 / 知道什么 / 欠什么 / 承诺进度），记忆进 IR 可持久化、可重跑 | ConWriter（EMNLP 2026）消融：去掉动态记忆 → 0.7499，**记忆贡献大于校验**；Keel 此前缺这一层，是最大能力缺口 |
| `keel/pipeline/repair.py` | `RepairBudget`（次数 / token / 时长硬上限）+ `Conflict` 消解：两条互斥建议记为 `conflicted` 交人裁决 | ConWriter 在 GPT-5 / 6K–12K 因「修复遵从 vs 长度控制」冲突**不收敛**；不设预算会在修复循环里烧完 token |
| `keel/validators/transitions.py` | `state_transition_integrity`：ConWriter 的 Pre/Post/Forbidden 符号化验证，抓「死人复活」类硬冲突 | `StateDelta` 原只有 before/after，缺 `forbidden` + 前置条件校验 |
| `scripts/verify.py` §10 | 门禁可信度自检：每门禁 ≥1 正例 + 1 反例，报 precision/recall（**诚实标注合成样本**） | ConStory-Checker ~68% 准确；Keel 此前只报「结构分 89」从不报可信度读数 |
| `scripts/keel.bat` / `keel.sh` / `build_zipapp.py` / `keel.pyz` | 零配置启动器（双击即用，自动建 venv / 装依赖）+ 单文件 zipapp | P0 可达性：再深的门禁，第一分钟看不到 = 0 |

> **集成状态（诚实记录）**：`transitions.py` 已注册进校验器表（`REQUIRES` + `state_transition_integrity`），
> 随 `run_all` 生效。但 `memory.py` / `repair.py` 本轮**只交付为库**，尚未接入
> `KeelPipeline` / `CriticLoop` / `AutoWriter`（铁律 18：共享状态注册串行，由集成者一处完成）。
> 它们的单元测试已通过（memory 58 / repair 149），接入是下一步独立任务，不是本轮回退。

### 已知缺陷（本轮**未修**，需单独立项）

`StructureEngine._bind_commitments` 无条件执行 `c.satisfied = True`，
把「把承诺排期到了某场」当成「承诺已兑现」，使 `commitment_satisfied`
（L3 防漂离论点，正是本项目存在的理由）的判据恒为假 —— **一个空转的假门禁**。
修它会影响全部既有基线（6 条 ERROR 级承诺会立刻全部报警），
本轮只在自动驾驶这条新路径上取正确语义。

---

## [1.0.0] — 2026-09-14 · 首个可交付版本

定位：**从"能跑的原型"变成"别人装得上、用得到"的东西。**
本轮没有新增叙事理论能力，全部改动都在**可达性**与**可信度**上 ——
一个到不了用户手里的判断，价值为零。

### 交付

| | 改动 | 为什么 |
|---|---|---|
| 打包 | 新增 `pyproject.toml`，`pip install -e .` 后得到 `keel` 命令 | 以前只能 `python -m keel.cli`，等于没发布 |
| 入口 | 新增 `keel/__main__.py`，`python -m keel` 可用 | 覆盖"不想装、只想跑"的人 |
| 默认输出 | `write` 不传 `--out` 时写 `out/<想法前 40 字>/` | 以前不传 `--out` **一个文件都不写** —— 第一分钟的路是断的 |
| 自动打开 | 跑完用默认浏览器打开 `report.html`；`--no-open` 关闭 | 报告存在但没人打开 = 等于没生成 |
| 默认子命令 | `keel "想法"` 等价于 `keel write "想法"` | 少一步操作，多一个人用上 |
| 版本 | `0.2.0` → `1.0.0` | 与交付状态对齐 |
| 文档 | 新增 `QUICKSTART.md`（5 分钟上手） | 以前新用户只能读架构文档 |
| CLI | 新增 `--version` | 打包后的标准件；之前 `keel --version` 会报"缺少子命令" |

默认输出目录**刻意不加时间戳**：重跑应覆盖同一份报告，不是堆副本。

### 核心能力（1.0 首次整体说明）

此前无 CHANGELOG，故在此一并记录 1.0 交付的是什么：

- **三层正交 IR**（Riedl & Young, IPOCL, JAIR 2010）
  L1 因果情节 / L2 角色目标 / L3 作者承诺。IR 是产品本体，文本只是视图。
- **注册表 36 项**：**29 个门禁校验器 + 7 个报表项**。
  门禁项与报表项**分类可机检**，且每个门禁项配**反例 fixture**。
- **5 个渲染器** + HTML 报告：text / fountain / storyboard / ink / renpy / html。
- **11 个结构模板**（含东亚体系：起承转合、章回体、微短剧节拍）。
- **8 引擎线性流水线**：`Premise → Cast → Structure → Character → LoreSeeder
  → LedgerSeeder → Scripter×N → CriticLoop`。
- **观众模拟**：结构性流失预测 + 配对比较。**不预测爆款**，未校准输出显式标注为"先验"。
- **溯源计量**：逐场 Provenance + AI 参与度合规报告（中国市场硬约束的内建能力）。
- **离线可跑**：`MockGenerator` 让整条流水线在无 API key 下端到端可跑。

### 本轮新增的实质能力

- **`keel/render/html.py`** —— 单文件自包含 HTML 报告，无 CDN / 无外链 / 断网可看。
  7 个区块：结构健康分 / 评估覆盖 / 人类判断痕迹 / 叙事前提 / 体检明细 /
  非结构信号 / 待裁决提案。
- **`keel/provenance/awareness.py`** —— 写作时的觉察回显。
  依据 CHI 2026（19 次访谈 + 1,291 次写作会话）：AI 协同写作中作者往往
  **察觉不到** AI 对自己方向的影响，却感觉完全掌控。
  `process.py` 本来就在记录判断，但只在**申诉**时导出；缺的是**写作时**可见。
  这不是新功能，是既有能力的一个新出口。
- **`premise_fidelity` 校验器** —— 结局是否兑现前提。
  依据 PLOTTER（ACL 2026 Findings）：多智能体方法在 Premise Fidelity 上只有
  40%/14%/44%，是最弱的一维。
- **`keel/policy.py`** —— 网文正文策略门禁。
  起点 / 番茄 / 晋江一致禁止 AI 直出正文；微短剧只要求标识。同一个 Keel，
  网文场景是违规工具、剧本场景是合规工具，所以做成**策略**而非删功能。
- **报表项三分**：`ADVISORY`（非结构信号）/ `ADVISORY_DEFECT`（条件缺陷，
  干净输入上必须沉默）/ `ADVISORY_READOUT`（无条件测量，如 `thread_budget`）。
  第三类是被迫加的 —— `thread_budget` 塞不进前两类，硬塞就要**编一个反例**。

### 修掉的重要缺陷

- **⭐ `CriticLoop` 的自动修订分支是死代码，从来没被执行过。**
  两个独立原因：
  1. 它从 `run_all()` 里筛 `slop:` 前缀的 finding，但 slop 走的是 **advisory 通道**，
     且没有任何 `slop:*` 校验器注册 → 结果**永远为空**；
  2. 它在"无结构问题"时 `break`，而这个判断**早于**文风处理 ——
     但"结构干净"恰恰是**最常见**的情况。

  发现方式：`--rounds` 实验在 1/2/3/4/5 轮上跑出**完全一致**的结果。
  现象是"没有方差"，根因是"这段代码没跑"。已由 `tests/test_criticloop.py` 守住，
  两个 bug 分别重新引入后均变红（验证过）。
- `build_clean_ir()` 返回的是**缓存单例** —— 测试里直接改它会污染后续用例。
  已改用 `clean_copy()`。
- 测试夹具用 **3 人工 : 3 AI** 的对称比例，导致把 `_HUMAN_WORK` 整个翻过来
  测试**仍然全绿**（空断言）。已改成 2:4 非对称。

### 测量：修订轮数上限（`--rounds`）

跑了 `scripts/measure_rounds.py`（注入一个真的会改写的 reviser，
因为 `MockGenerator.revise` 按设计返回 `changed: False`）：

```
轮数    残留 slop 命中   reviser 调用
 1          24              6
 2          24             12
 3          12             18
 4           0             24
 5           0             30
 6           0             36
```

- 残留 slop 在**第 4 轮归零**；第 5–6 轮**零收益但仍有成本**。
- 健康分与轮数**无关**（文风走 advisory，不进 `score()`）。
- **本次不改 `--rounds`（仍为 2）。** 本测量只覆盖机制（收敛性 / 边际收益 / 成本），
  **不覆盖**生成质量。PLOTTER 观察到的"K=5 反而变差"来自真实 LLM 的过度编辑，
  用桩件模拟出来等于**编造数据**。宁可留着这个问题，也不报一个假的答案。

### 自证

- `scripts/verify.py`：**62 项断言全绿**（本轮从 54 增至 62）。
- 干净基线：`novel` 96（覆盖 33/36）、`micro_drama` 95（覆盖 35/36）。
- 变异测试：新增模块（awareness / html / criticloop）共 10 个变异，全部 RED。

### 已知未做

- `max_rounds` 的**质量维度** —— 需要真 LLM，见上。
- **健康分是否应容纳非结构信号** —— `score() = 100 − 12×E − 4×W − 1×I`，
  INFO 会扣分，导致"多装几个检测器分数就降"。这是**待作者决策**，未擅自改。
- 网文 / 微短剧的默认媒介选择 —— 同上，待作者决策。
- 观众模拟的**校准** —— 需要真实留存数据；未校准前输出一律标注"先验"。

---

## 约定

- **数字不许手写。** 校验器数量、断言数量一律从单一来源（如 `registry_stats()`）取。
  `scripts/verify.py` 会扫文档里的"N 个校验器"断言与注册表一致 ——
  这个位置漂过两次，所以现在是机检的。
- **SKIPPED ≠ PASS。** 拿不到数据时是 SKIPPED，不计入健康分；
  体检报告必须同时报**评估覆盖率**，只报健康分等于隐瞒有多少项没测。
- **门禁可信度靠净命中率，不靠方法论引用。** 每个门禁项必须有反例 fixture，
  判据是**严重度升级**，不是"变异后触发了"。
