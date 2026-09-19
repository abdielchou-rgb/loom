# Keel 快速上手（5 分钟）

> 面向第一次打开这个项目的人。**不需要 API key**，不需要注册任何服务。
> 文中的每条命令都在 Windows + Python 3.13 上实测过。

> **一句话定位**：可证明是你写的 · 故事哪里坏了可被指出 · 投入制作前就知道不值得做。
> Keel 不替你写，也不夸你写得好——它是站在你这边的对抗性编辑。

---

## 0. 先说清它是什么、不是什么

Keel 是**叙事编译器**，不是文本生成器。

```
想法 ──▶ Narrative IR（结构化故事）──▶ 小说 / 剧本 / Ink / Ren'Py / 分镜 / HTML 报告
              ↑
        这才是本体。文本只是 IR 的一个视图。
```

所以它**不会**帮你"一键生成十万字"。它做的是另一件事：**告诉你这个故事哪里不成立。**

> 文本的生产成本趋近于零之后，稀缺的不再是故事，而是**关于故事的信息**。
> Keel 的产品是信息，不是故事。

---

## 1. 一分钟：装好并跑出第一条

```bash
# 建虚拟环境并装依赖（只有一个硬依赖：pydantic）
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt    # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS / Linux

# 装成可以全局敲的命令（可选，但推荐）
.venv/Scripts/python.exe -m pip install -e .

# 确认装好了
keel --version          # → keel 1.0.0
```

**第一条命令：**

```bash
keel "一个外科医生发现自己缝合的伤口会预言未来"
```

不写子命令也行 —— `write` 是默认子命令。跑完你会看到：

```
已写入 out\一个外科医生发现自己缝合/：ir.json · novel.md · outline.md · audience.json · report.html

  报告：out\一个外科医生发现自己缝合\report.html（已用默认浏览器打开）
```

**浏览器会自动弹出一份 HTML 报告。** 这就是主交付物。

> 不想自动开浏览器：加 `--no-open`。
> 想指定目录：加 `--out out/demo1`（不填就用 `out/<想法前 40 字>/`，
> 重跑覆盖同一份 —— 刻意不加时间戳，免得堆副本）。

---

## 2. 三分钟：读懂报告

`report.html` 是**单文件、自包含、无 CDN、无外链**的 —— 断网也能看，
可以直接发给别人。它有 7 个区块：

| 区块 | 看什么 | 为什么值得看 |
|---|---|---|
| **结构健康分** | 一个 0–100 的数字 | 但它**必须**和下一个区块一起看 |
| **评估覆盖** | `跑过 31/36 · 跳过 5` | 只报健康分是**隐瞒**了多少项没测到 |
| **人类判断痕迹** | "已做判断 N 次（采纳 / 驳回）· 待你裁决 M 条" | 见 §3.3 |
| **叙事前提（L3 承诺层）** | 你这个故事**承诺**了什么 | 决定"跑题"能不能被自动判定 |
| **体检明细** | 每条问题的严重度 + 改法 | ERROR / WARN / INFO 三级 |
| **非结构信号** | AI 味、张力、风格… | **不计入健康分**，见 §3.2 |
| **待裁决提案** | AI 提的结构改动 | **不会**被自动应用，见 §3.3 |

### 这三个概念不知道，就会用错

**3.1 健康分旁边一定要看"评估覆盖"**

健康分是 `100 − 12×错误 − 4×警告 − 1×提示`。但校验器拿不到数据时是
**SKIPPED，不是 PASS**，且不计入分数。

所以"96 分"有两种：36 项全跑过拿 96，和只跑过 12 项拿 96。
报告的评估覆盖区块会**逐项列出**被跳过的原因（例如
`⊘ 缺 medium:micro_drama：2 个 — hook_cadence, paywall_gate_present`）。

> **SKIPPED ≠ PASS。** 这是本项目反复强调的一条。

**3.2 非结构信号不进健康分**

AI 味、文风张力、认知负荷、"接下来还能写什么"……这些是**工艺/信号**，
不是结构缺陷。它们和结构缺陷共用一个数字会导致：多装几个检测器分数就降，
或者可写的张力点越多分数越低 —— 头条指标变得无法解释。所以单列。

**3.3 只自动修文风，结构提案等你裁决**

这是 Keel 的一条硬边界：

- **文风类**（AI 味措辞等）→ `CriticLoop` 自动修订，最多 `--rounds` 轮（默认 2）。
- **结构类**（"第三幕缺一个反转"）→ 只提**提案**，**绝不**自动应用。

> 自动改结构会毁掉作者意图。它看着像帮忙，实际是把你的故事换成 AI 的故事。

报告里的"待裁决提案"区块就是给你做这个决定的。命令行也可以：

```bash
keel proposals out/<目录>/ir.json              # 列出待裁决提案
keel decide    out/<目录>/ir.json --all --accept   # 全部采纳
keel decide    out/<目录>/ir.json prop_xxx --accept # 只裁决一条
```

> 采纳是一个**决定**，不是一次自动改写 —— 采纳后目标字段**仍原样**，
> 具体怎么改由你或下一轮生成决定。

**未裁决的东西不构成你的判断。** 这也是"人类判断痕迹"区块存在的理由 ——
CHI 2026 的研究（19 次访谈 + 1,291 次写作会话）发现：AI 协同写作中作者
往往**察觉不到** AI 对自己方向的影响，却感觉完全掌控。把判断次数显式回显出来，
是针对这个失效模式的对策。

---

## 3. 命令速查

```bash
P=.venv/Scripts/python.exe

# ── 主流程 ──────────────────────────────────────────────
keel write "想法" --scenes 6 --words 600 --out out/demo1   # 想法 → IR → 正文 → 报告
keel write "想法" --medium micro_drama                     # 换媒介
keel write "想法" --arc icarus --template save_the_cat     # 换情感弧线 / 结构模板
keel web --port 8000                                    # 起本地网页界面（浏览器里填想法、点生成）

# ── 对已有 IR 做事 ──────────────────────────────────────
keel audit       out/demo1/ir.json      # 故事体检
keel recheck     out/demo1/ir.json      # 重跑旧 IR + "上次以来变了什么"
keel audience    out/demo1/ir.json      # 观众模拟（留存曲线 + 观众原话）
keel outline     out/demo1/ir.json      # 大纲（IR 层人工确认）
keel render      out/demo1/ir.json -f renpy                # 渲染成 Ren'Py
keel render      out/demo1/ir.json -f html -o r.html       # 单独出 HTML 报告
keel play        out/demo1/ir.json --runs 500              # 随机化通关测试

# ── 合规 ────────────────────────────────────────────────
keel compliance    out/demo1/ir.json --json out/c.json     # AI 参与度报告
keel submit-check  out/demo1/ir.json                       # 投稿前自检：能不能投
keel process-report out/demo1/ir.json --out 过程.md        # 创作过程留痕（申诉举证）

# ── 自查 ────────────────────────────────────────────────
$P scripts/verify.py        # 自证：全部断言（改完校验器必跑）
$P scripts/pipeline_demo.py # 端到端 10 环节（离线）
$P scripts/demo.py          # IR 层 10 环节（离线）
```

没有 `-m keel` 也能跑：`$P -m keel.cli write "想法"`（等价，不依赖 console script）。

---

## 4. 接真模型

默认用的是**确定性参考生成器** `MockGenerator` —— 这就是你刚才跑出来的东西。
它不是占位符：整条流水线离线可跑，是架构可验证性的证明，也是回归测试基线。

换真模型只需加一个参数：

```bash
pip install litellm
export OPENAI_API_KEY=sk-...
keel write "想法" --model gpt-4o
```

没装 litellm 时会明确报：`未安装 litellm。请执行 pip install litellm，或改用 MockGenerator 做离线验证。`

跑完会打印 token 记账（调用次数 / 输入 / 输出 / 估算成本 / 按任务拆分）。

### 没有 key 也要产出真内容：`--generator workbuddy`

`MockGenerator` 形态对、内容假（固定语料）；真模型内容真、但要 key。
第三条路是**让 Keel 发问，而不是生成**：

```bash
keel write "想法" --generator workbuddy --medium screenplay --scenes 3
# ⏸ 待填 7 个请求 → out/<标题>/.wb_queue/<hash>/answers.json
```

Keel 把**渲染好的提示词**写成 `answers.json`，每条留出空的 `output`。
填的人可以是 WorkBuddy、可以是你自己、也可以是任何一个聊天窗口 ——
把提示词粘进去，把 JSON 粘回来。填好后**重跑同一条命令**：
已填的不会丢，流水线接着往下走（退出码 3 = 在等人，不是出错）。

两个附带好处：

1. **零依赖产出真内容** —— 没有 key、没有网络也能跑出有内容的稿子。
2. **可回放** —— 每一次「模型调用」都落成一个人能读的文件
   （提示词 / 版本号 / payload 哈希 / 答案），而 API 调用是黑盒。
   对 AI 参与度计量来说，这份文件本身就是证据。

---

## 5. 一条合规红线

`--medium web_novel`（网文）默认**挡住正文生成**：

```
keel write "想法" --medium web_novel
# → ⚠ 未生成正文：「web_novel」默认不生成正文 —— 起点 / 番茄 / 晋江 三家网文平台
#     一致禁止 AI 直出正文（起点 AI 占比 >10% 即处理，方式为移出全部榜单/推荐位）。
#     Keel 在网文场景下提供的是结构 + 伏笔表 + 人设卡 + 合规自检，不是代笔。
#   需要正文时加 `--force-prose`（风险自负）。
```

注意它**不报错、退出码 0** —— 结构层产物照常生成，只是没有正文。
（`render_text()` 被直接调用时才抛 `PolicyError`；CLI 把这层转成可读的警告。
刻意不让它崩：**挡住是策略，不是崩。**）

原因：网文平台禁 AI 生成正文，而微短剧只要求**标识**。同一个 Keel，
在网文场景是违规工具，在剧本场景是合规工具 —— 所以这是**策略**，不是删功能。

确有合法用途时用 `--force-prose` 显式越过。挡住是默认值，不是能力缺失。

另有《微短剧发展管理办法》（广电总局令第 16 号）2026-09-01 施行：
AI 参与须显著标识。所以**溯源计量是内建能力**，不是附加功能
（`write` 逐场写 Provenance）。

---

## 6. 出问题怎么办

| 现象 | 原因 / 处理 |
|---|---|
| `keel: command not found` | console script 装了但**不在 PATH** 上。用下面任意一种：`.venv/Scripts/python.exe -m keel.cli ...`；或直接全路径 `.venv/Scripts/keel.exe`（Windows）／`.venv/bin/keel`（macOS/Linux）；或 `pip install -e .` 后重开终端 |
| 报 `未安装 litellm` | 你传了 `--model` 但没装可选依赖；去掉 `--model` 就回到离线模式 |
| 跑完没有 `novel.md` | 大概率是网文媒介被策略挡住了（不报错，会打印 ⚠ 说明），见 §5 |
| 代码里调 `render_text()` 抛 `PolicyError` | 同上；加 `force_prose=True` 显式越过 |
| 健康分很高但故事明显有问题 | 先看**评估覆盖** —— 可能大半校验器被跳过了（§3.1） |
| 改了校验器之后 | 跑 `scripts/verify.py`。它会断言文档里的计数与注册表一致 |
| 浏览器打不开 `http://127.0.0.1:8000` | **多半是系统代理拦了本机地址**：请求被送去代理（常表现为 502）。Windows 执行 `set NO_PROXY=127.0.0.1,localhost`，macOS/Linux 执行 `export no_proxy=127.0.0.1,localhost`，再重开浏览器。服务只监听本机，不是网络问题 |
| 启动时端口被占 | **不用管**：`keel web` 会往后自动找一个空闲端口，并打印实际用的地址（如「已自动改用 8001」）。只有连续 20 个端口都不行才需要 `--port 9000` 手动指定 |

---

## 7. 五分钟之后

想理解为什么这么设计，按这个顺序读：

1. `工程执行计划_第一性原理.md` —— 第一性原理推导，为什么是这些功能
2. `README.md` —— 完整架构、校验器清单、设计取舍
3. `外部调研_2026-09-14_第二轮.md` —— 4 篇 A 级论文 + 2 份 B 级商业数据
4. `交付方案_1.0.md` —— 交付了什么、还剩什么没做（含**明确没做**的部分）
5. `ENGINEERING_PLAN.md` —— 逐模块工程细节

有一件事需要你知道：**Keel 不预测你的故事会不会火。**
它只做结构性排除 —— 告诉你哪里不成立。任何"爆款预测"都是编的。
