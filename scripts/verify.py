"""Loom 自证工具 —— 零依赖，不需要 pytest，不需要 API key。

跑法：
    .venv/Scripts/python.exe scripts/verify.py
    .venv/Scripts/python.exe scripts/verify.py --json out/verify.json

它回答八个问题（前六个在此之前从来没被问过）：

  1. registry 完整吗？       每个注册的校验器都声明了数据需求吗？
  2. 报表项真的是报表项吗？   REPORTS / ADVISORY 名单里的函数，源码里真的没有
                             WARN/ERROR 吗？advisory 名单是 REPORTS 的子集吗？
  3. 提示词字段齐吗？         模板里的占位符真的有人填吗（还是静默退化了）？
  4. 计数漂移了吗？           README / 方案 / 脚本里的「N 个校验器」「N 个引擎」
                              「N 个反例变异」等硬编码数字，等于单一真源的实际值吗？
  5. 有死校验器吗？           每个门禁项在真实 IR 上真的会被执行吗（而不是永远跳过）？
  6. 干净文本会误报吗？       基线 IR 上有没有 ERROR/WARN？advisory 项会不会空转？
  7. 反例抓得住吗？           注入缺陷后，对应的校验器严重度真的升级了吗？
  8. 校验器会崩吗？           所有输入（基线 / 示例 / 每个变异）上 Report.crashes
                             是不是空的？**崩溃是第四种状态** —— 它不产出 Finding，
                             所以不会自己浮出来，只能靠断言抓。

第 8 条是 2026-09-14 补的。它抓到的真实缺陷：`pattern_saturation` 把
`SceneNode.storylet_ids` 写成了 `Storylet.storylet_ids` —— 在没有 storylet 的
IR 上，那个生成器表达式的循环体根本不求值，于是**永远不报错**；
在有 storylet 的 IR 上必崩。「干净基线全绿」与「这个分支从来没跑过」
可以同时成立，而它漂了很久。

**净命中率**（第 5、6 条合起来）而不是绝对命中率。绝对命中率是自欺的：
对着任何文本都报警的校验器命中率是 100%，但信息量为零。
净命中要求「变异后严重度升级」且「≥ 预期严重度」。

也不是「变异后触发了就算」。因为 `thread_budget` 在健康时也输出 INFO，
只判「有输出」的话它永远命中 —— 那是在给自己的指标注水。

设计出处：Æsirian `tools/gate_verification/`（样本三族 + 净命中率 delta），
但本工具做了四处改动：
  * 用「流水线产出的干净 IR」当基线，而非手写样本（手写样本容易变成
    「为了通过校验器而写的样本」）
  * 用严重度升级代替布尔触发（见上）
  * 基线覆盖多种媒介 —— 否则 medium 相关的门控项永远 SKIPPED，
    它们的「没问题」只是没跑过
  * 把「校验器崩溃」当成第四种状态单独断言（见第 8 条）
"""

from __future__ import annotations

import argparse
import inspect
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loom.ir.enums import Medium, Severity  # noqa: E402
from loom.validators import (  # noqa: E402
    ADVISORY,
    ADVISORY_DEFECT,
    ADVISORY_READOUT,
    ALWAYS_EVALUABLE,
    NEEDS,
    REPORTS,
    REQUIRES,
    available,
    coverage_report,
    get_validator,
    registry_stats,
    run_all,
)
from tests.fixtures import (  # noqa: E402
    BASELINE_MEDIA,
    MUTATIONS,
    build_clean_ir,
    clean_copy,
)

SEV = {Severity.INFO: 0, Severity.WARN: 1, Severity.ERROR: 2}
NONE = -1  # 该 code 在这个 IR 上一条 Finding 都没有
GLYPH = {-1: "—", 0: "·", 1: "!", 2: "✗"}


# ---------------------------------------------------------------------------


class Checker:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[str] = []
        self.notes: list[str] = []

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        if ok:
            self.passed += 1
            print(f"  ✓ {label}")
        else:
            self.failed.append(label)
            print(f"  ✗ {label}" + (f"\n      {detail}" if detail else ""))
        return ok

    def note(self, text: str) -> None:
        self.notes.append(text)
        print(f"  · {text}")


def head(n: str, title: str) -> None:
    print()
    print("═" * 64)
    print(f"  {n} {title}")
    print("═" * 64)


# ---------------------------------------------------------------------------
# 1. registry 完整性
# ---------------------------------------------------------------------------


def check_registry(c: Checker) -> None:
    head("1.", "registry 完整性")
    codes = set(available())

    undeclared = sorted(codes - set(REQUIRES) - ALWAYS_EVALUABLE)
    c.check(
        not undeclared,
        f"每个校验器都声明了数据需求（{len(codes)} 个）",
        f"未声明：{undeclared}\n"
        f"      → 加进 validators/base.py 的 REQUIRES 或 ALWAYS_EVALUABLE。\n"
        f"        这条断言防的是「注册了却永远不会被真正执行」的死校验器。",
    )

    ghost = sorted(set(REQUIRES) - codes)
    c.check(
        not ghost,
        "REQUIRES 没有指向不存在的校验器",
        f"幽灵条目：{ghost}（注册表里没有这些 code）",
    )

    bad_needs = sorted(
        {n for needs in REQUIRES.values() for n in needs} - set(NEEDS)
    )
    c.check(
        not bad_needs,
        "所有声明的需求都有对应的探针",
        f"未定义的探针：{bad_needs}",
    )

    stats = registry_stats()
    c.note(
        f"门禁项 {stats['gating']} · 报表项 {stats['reports']}"
        f" · 合计 {stats['total']}"
        f"（已声明需求 {stats['with_declared_requirements']}"
        f" · 恒可评估 {stats['always_evaluable']}）"
    )
    c.note(f"按模块：{stats['by_module']}")


# ---------------------------------------------------------------------------
# 2. 报表项 vs 门禁项
# ---------------------------------------------------------------------------


def check_reports(c: Checker) -> None:
    head("2.", "报表项 vs 门禁项 vs 只通报通道")
    c.note(
        "报表项 = 设计上只做通报的函数。它们出现在体检报告里，但永远不会"
        "让作品不通过，\n    因此不算进「N 个校验器」。"
    )
    # REPORTS 与 ADVISORY 是两个不同的轴，一起扫源码：
    #   REPORTS  = 不可能产出 WARN/ERROR → 不是门禁
    #   ADVISORY = 产出的是非结构信号 → Finding 走 advisory 通道、不进健康分
    # 两个名单里的函数都**必须**不含 WARN/ERROR。对 ADVISORY 来说这不是
    # 分类习惯问题：一条会报警的检查若走 advisory，报警会被静默吞掉，
    # 于是「永远不失败」—— 那就把一道门禁偷偷变成了装饰。
    for code in sorted(REPORTS | ADVISORY):
        fn = get_validator(code)
        if fn is None:
            c.check(False, f"{code} 仍在 registry 中", "名单已过期")
            continue
        src = inspect.getsource(fn)
        hits = [s for s in ("Severity.WARN", "Severity.ERROR") if s in src]
        tags = []
        if code in REPORTS:
            tags.append("报表项")
        if code in ADVISORY:
            tags.append("advisory 通道")
        c.check(
            not hits,
            f"{code}（{'/'.join(tags)}）：源码中不含 WARN/ERROR 严重度",
            f"源码里出现了 {hits}\n"
            f"      → 它其实是门禁项。应从名单移出，并为它补一个反例 fixture。\n"
            f"        分类必须可机检，否则名单会变成一句口号。",
        )

    stray = sorted(ADVISORY - REPORTS)
    c.check(
        not stray,
        "ADVISORY ⊆ REPORTS",
        f"只在 ADVISORY 里、不在 REPORTS 里：{stray}\n"
        f"      → 两个名单语义不同但方向一致：advisory 项必须是「不可能失败」的，\n"
        f"        否则它会把一道真门禁的报警静默吞掉。",
    )

    # ADVISORY 内部还有第二层区分：机会型 vs 缺陷型（见 base.ADVISORY_DEFECT）。
    # 它不是分类癖，是**非空转判据**的分叉点：
    #   机会型（「你接下来可以写什么」）在干净稿子上沉默 = 空转，必须报警；
    #   缺陷型（「文本落在平台的机器区间」）在干净稿子上沉默 = 正确结果，
    #   若沿用同一条判据，就会逼着检测器对干净稿子硬报假阳性 ——
    #   为了让指标好看而制造假阳性，正是本文件反复警告的注水行为。
    orphan = sorted(ADVISORY_DEFECT - ADVISORY)
    c.check(
        not orphan,
        "ADVISORY_DEFECT ⊆ ADVISORY",
        f"只在 ADVISORY_DEFECT 里：{orphan}\n"
        f"      → 缺陷型是 advisory 的一个子类，不可能是它的超集。",
    )
    unproven = sorted(ADVISORY_DEFECT - set(MUTATIONS))
    c.check(
        not unproven,
        "每个缺陷型 advisory 项都有反例（非空转由反例证明，不由基线证明）",
        f"缺反例：{unproven}\n"
        f"      → 缺陷型项在干净输入上**应当**沉默，它的「会说话」只能靠\n"
        f"        自己的反例变异证明。没有反例，它和不存在无法区分。",
    )

    # 第三类：**读数型**（`ADVISORY_READOUT`）。
    # 它是**测量**不是判断（`thread_budget` 只是在报「价值线分布：X×3（共 N 条）」），
    # 永远产出一条。它既不是机会、也不是缺陷 —— 硬塞进缺陷型会逼出一个
    # **不存在的故障**的反例，那是给分类整齐而造假。
    # 判据：读数型必须在**基线**上说话（这正是它的定义），且**不需要**反例。
    orphan_r = sorted(ADVISORY_READOUT - ADVISORY)
    c.check(
        not orphan_r,
        "ADVISORY_READOUT ⊆ ADVISORY",
        f"只在 ADVISORY_READOUT 里：{orphan_r}\n"
        f"      → 读数型是 advisory 的一个子类，不可能是它的超集。",
    )
    overlap = sorted(ADVISORY_READOUT & ADVISORY_DEFECT)
    c.check(
        not overlap,
        "读数型与缺陷型互斥",
        f"同时属于两者：{overlap}\n"
        f"      → 缺陷型是「条件触发、干净稿上应沉默」；读数型是「无条件产出」。\n"
        f"        一条结论不可能同时满足这两条，重叠说明分类写错了。",
    )


# ---------------------------------------------------------------------------
# 2b. 基线读数：读数型项必须在干净基线上说话
# ---------------------------------------------------------------------------


def check_readout_speaks(c: Checker) -> None:
    """读数型 advisory 项必须在干净基线上产出。

    理由与机会型不同，但落点相同（都要在基线上说话）：
      机会型 —— 永远沉默等于不存在；
      读数型 —— **永远说话是它的定义**，沉默就是坏了。
    """
    if not ADVISORY_READOUT:
        return
    for medium in (Medium.NOVEL, Medium.MICRO_DRAMA):
        rep = run_all(clean_copy(medium))
        spoke = {f.code for f in rep.advisory}
        silent = sorted(ADVISORY_READOUT - spoke)
        c.check(
            not silent,
            f"读数型项在 {medium.value} 基线上说话（{len(ADVISORY_READOUT)} 个）",
            f"沉默的读数型项：{silent}\n"
            f"      → 读数型是无条件测量，沉默意味着它坏了或数据没了。",
        )


# ---------------------------------------------------------------------------
# 3. 提示词字段完整性
# ---------------------------------------------------------------------------


def check_prompts(c: Checker) -> None:
    """提示词模板里的每个占位符都必须真的有人填。

    这是一类真实故障（本次会话抓到）：STRUCTURE 模板要求 `{arc_shape}`，
    但 `StructureEngine` 的 payload 里从来没有这个键 —— 渲染静默退化，
    模型拿不到弧线信息，而 `emotion_curve_match` 随后因「模型没照做」报警。
    **根因在提示词层，症状出现在校验层**，没有留痕就查不出来。

    `Prompt.render()` 的降级设计是对的（一个字段不该让整条流水线挂掉），
    但它必须留痕。这条检查断言：跑一遍真实流水线后，没有任何模板
    出现未填充的占位符。
    """
    head("3.", "提示词字段完整性")
    from loom.audience import AudienceSimulator
    from loom.ir.enums import Medium
    from loom.llm import MockGenerator
    from loom.llm.base import REGISTRY as PROMPT_REGISTRY
    from loom.pipeline import LoomPipeline

    # 遍历**全部**媒介，而不是只跑小说。
    # 只跑小说，正是「选了剧本却产出小说」这一类缺陷能长期存活的原因：
    # 提示词里新加的占位符若只在某些分支上填了，
    # 小说路径照样全绿，而剧本路径静默退化。
    class _RenderingGenerator:
        """把 payload **真的**喂给 `Prompt.render()`。

        为什么必须有这一层包装：`MockGenerator` 按 task 分派到确定性函数，
        **从头到尾不调用 `Prompt.render()`**。于是 `render_misses` 恒为空，
        这一节**一直是假绿** —— 把 payload 里的键全删掉，它也照样通过。

        实测：桩件跑完整条流水线 + 观众模拟，`Prompt.render` 被调用 **0 次**。
        也就是说这节此前检查的不是「占位符填了没」，是「有没有人去查过」。
        """

        def __init__(self, inner: MockGenerator) -> None:
            self._inner = inner

        @property
        def model_id(self) -> str:
            return self._inner.model_id

        def generate(self, task: str, payload: dict) -> dict:
            try:
                PROMPT_REGISTRY.get(task).render(payload)
            except KeyError:
                pass  # 没有注册提示词的任务不归这一节管
            return self._inner.generate(task, payload)

    gen = _RenderingGenerator(MockGenerator())
    for medium in Medium:
        ir = LoomPipeline(gen).run(
            "一个替人收尸的刀客，发现自己要收的那具尸体是自己十年前的名字",
            medium=medium,
            scene_count=3,
            words_per_scene=200,
            max_rounds=1,
        ).ir
        AudienceSimulator(gen).run(ir)

    misses = {
        p.id: p.render_misses
        for p in PROMPT_REGISTRY.all()
        if p.render_misses
    }
    c.check(
        not misses,
        f"所有提示词模板的占位符都被填上了（{len(Medium)} 个媒介各跑一遍）",
        f"未填充：{misses}\n"
        f"      → 模板要求了这个字段，但调用方没提供。模型会拿到一份\n"
        f"        缺信息的提示词，而校验器随后会因「模型没照做」报警。\n"
        f"        要么补 payload，要么删掉模板里的占位符。",
    )
    c.note(
        f"提示词 {len(PROMPT_REGISTRY.all())} 条："
        + "、".join(
            f"{k}@{v}" for k, v in sorted(PROMPT_REGISTRY.versions().items())
        )
    )


# ---------------------------------------------------------------------------
# 3b. 媒介形态
# ---------------------------------------------------------------------------


#: 每个媒介的**形态标记**。判断的不是「写得好不好」，而是
#: 「它到底是不是这个媒介」—— 一句话就能说清、改坏了立刻变红的那种事实。
#:
#: 为什么需要这一节：`prose` 提示词曾经写死「你是小说作者」，于是选了
#: 「剧本」产出的仍是小说散文，只是被渲染器套了层场景标题。
#: 那不是排版问题，是**形态规格缺失**；而形态只能靠标记检测 ——
#: 散文读起来也通顺，它只是不是剧本。
MEDIUM_SHAPE_MARKS: dict[str, tuple[str, ...]] = {
    # 剧本：人物提示行独占一行 + 转场
    "screenplay": ("CUT TO:",),
    # 微短剧：同剧本形态，但更短且不给转场（收在悬念上）
    "micro_drama": ("？",),
    # 漫画：画格 + 转场类型
    "comic": ("格 1｜画面：", "转场："),
    # 互动小说：选项行
    "interactive_fiction": ("* ",),
    # 视觉小说：立绘/背景提示 + 「」对白
    "visual_novel": ("【立绘：", "「"),
    # 剧本杀：幕结构
    "murder_mystery": ("【第一幕", "【本幕任务】"),
    # 小说/网文：无强制形态标记（散文体），故不参与形态断言
}


def check_medium_shape(c: Checker) -> None:
    """生成的正文必须**看起来像**它被要求写的那个媒介。

    判据是形态标记，不是文风评分。只判有硬格式的媒介
    （小说/网文是散文体，没有可断言的形态标记，强行造一个就是假门禁）。

    这一节的由头是一起真实缺陷：选了「剧本」，产出的是小说散文。
    根因是 `prose` 提示词不感知媒介。修法在 `ir/medium_craft.py`
    （形态规格的唯一定义）+ 桩件按媒介产出。
    """
    head("3b.", "媒介形态（正文是不是它该是的那个东西）")
    from loom.llm import MockGenerator
    from loom.pipeline import LoomPipeline

    gen = MockGenerator()
    bad: list[str] = []
    checked = 0
    for medium in Medium:
        marks = MEDIUM_SHAPE_MARKS.get(medium.value)
        if not marks:
            continue
        checked += 1
        ir = LoomPipeline(gen).run(
            "一个替人收尸的刀客，发现自己要收的那具尸体是自己十年前的名字",
            medium=medium,
            scene_count=2,
            words_per_scene=150,
            max_rounds=1,
        ).ir
        bodies = [(s.prose or "") for s in ir.ordered_scenes()]
        joined = "\n".join(bodies)
        missing = [m for m in marks if m not in joined]
        if not bodies or missing:
            bad.append(
                f"{medium.value}：缺形态标记 {missing}"
                + ("（正文为空）" if not any(b.strip() for b in bodies) else "")
            )
    c.check(
        not bad,
        f"每种媒介的正文都带本媒介的形态标记（{checked} 种媒介）",
        "以下媒介的正文没有它该有的形态：\n        "
        + "\n        ".join(bad)
        + "\n      → 典型根因：prose 提示词不感知媒介，桩件/模型一律写成小说散文。\n"
        "        形态规格的唯一定义在 ir/medium_craft.py。",
    )


# ---------------------------------------------------------------------------
# 4. 计数漂移
# ---------------------------------------------------------------------------

RE_VALIDATORS = re.compile(r"(\d+)\s*个校验器")
RE_REPORTS = re.compile(r"(\d+)\s*个报表项")
#: 数字部分要同时吃阿拉伯数字与**中文数词** —— README 原先写的是「六个引擎」，
#: 只匹配 \d+ 会静默跳过它，这正是它漂了很久没人发现的原因。
_NUM = r"(?:\d+|[零〇一二两三四五六七八九十百千]+)"
RE_ENGINES = re.compile(rf"({_NUM})\s*个引擎")
#: 锚在「个反例变异」这个**具体说法**上，不用泛化的「个反例」：
#: 本文件下面的建议文案里就有「补一个反例 fixture」，
#: 泛化模式会把那句提示当成计数断言，制造假失败。
RE_MUTATIONS = re.compile(rf"({_NUM})\s*个反例变异")
#: 渲染器数 / 提示词数 / 结构模板数。这三个此前是**完全没人看管**的手写数字：
#: 「6 个版本化提示词」在提示词加到 7 条之后仍然是 6，而没有任何机制会发现。
#: 凡是「手写 + 无人看管」的数字都会漂，只是时间问题。
RE_RENDERERS = re.compile(rf"({_NUM})\s*个渲染器")
RE_PROMPTS = re.compile(rf"({_NUM})\s*个版本化提示词")
RE_TEMPLATES = re.compile(rf"({_NUM})\s*个(?:内置)?模板")

#: 扫描范围：文档 + 脚本。**脚本也要扫** —— 本次就发现 `scripts/demo.py`
#: 里硬编码着「14 个校验器」（实际 24）。文档漂移是脸面问题，
#: 脚本漂移是产品问题：用户会直接从输出里读到那个数字。
DOCS = ("README.md", "ENGINEERING_PLAN.md")
SCRIPT_GLOB = "scripts/*.py"


def _as_int(token: str) -> int | None:
    """阿拉伯数字或中文数词 → int。中文数词复用 CSN 的归一化（单一实现，不重写一遍）。"""
    if token.isdigit():
        return int(token)
    from loom.audit.csn import normalize_cn_number

    return normalize_cn_number(token)


def _renderer_count() -> int:
    """渲染器数从 `loom/render/__init__.py` 的导出面派生。"""
    from loom import render

    return len(render.__all__)


def _prompt_count() -> int:
    from loom.llm.base import REGISTRY as PROMPT_REGISTRY

    return len(PROMPT_REGISTRY.all())


def _template_count() -> int:
    from loom.ir.templates import list_templates

    return len(list_templates())


def _pipeline_engine_count() -> int:
    """从源码派生流水线引擎数 —— 单一真源，不手写。

    判据是「**顶层类里有 `run()` 方法的**」，不是「顶层类的个数」。
    这个区别踩过一次：`engines.py` 里除了 8 个阶段还住着数据类
    （如 `ScriptedScene`），按类计数会把数据类也算成引擎，
    于是 README 的「8 个引擎」被误判为漂移。
    **计数口径要落在语义上（有没有 run），不是落在语法上（是不是 class）。**
    """
    import ast

    src = (ROOT / "loom" / "pipeline" / "engines.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    return sum(
        1
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(
            isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)) and b.name == "run"
            for b in node.body
        )
    )


def check_doc_counts(c: Checker) -> None:
    head("4.", "计数漂移（文档 + 脚本）")
    stats = registry_stats()
    expect: dict[str, tuple[int, re.Pattern[str], str]] = {
        "个校验器": (stats["gating"], RE_VALIDATORS, "registry_stats()['gating']"),
        "个报表项": (stats["reports"], RE_REPORTS, "registry_stats()['reports']"),
        "个引擎": (_pipeline_engine_count(), RE_ENGINES, "engines.py 里有 run() 的顶层类数"),
        "个反例变异": (len(MUTATIONS), RE_MUTATIONS, "fixtures.MUTATIONS 的长度"),
        "个渲染器": (_renderer_count(), RE_RENDERERS, "loom.render.__all__ 的长度"),
        "个版本化提示词": (_prompt_count(), RE_PROMPTS, "PromptRegistry.all() 的长度"),
        "个模板": (_template_count(), RE_TEMPLATES, "templates.list_templates() 的长度"),
    }

    targets: list[Path] = [ROOT / n for n in DOCS]
    targets += sorted(ROOT.glob(SCRIPT_GLOB))
    # 本文件自己在讲这件事，跳过以免自指
    targets = [p for p in targets if p.resolve() != Path(__file__).resolve()]

    found_any = False
    for p in targets:
        if not p.exists():
            continue
        rel = p.relative_to(ROOT).as_posix()
        text = p.read_text(encoding="utf-8")
        for label, (want, pattern, source) in expect.items():
            for m in pattern.finditer(text):
                found_any = True
                n = _as_int(m.group(1))
                line = text[: m.start()].count("\n") + 1
                c.check(
                    n == want,
                    f"{rel}:{line} 写「{m.group(1)} {label}」",
                    f"{source} 实际是 {want}。\n"
                    f"      → 数字必须从单一真源派生，不许手写。\n"
                    f"        手写的数字必然漂移，因为它没有任何机制与代码同步。\n"
                    f"        （校验器数踩过两次：文档写 16 / 14，实际 24；\n"
                    f"          引擎数写「六」，实际 8；断言数写「56」，实际 64；\n"
                    f"          提示词数写「6 个版本化提示词」，实际 7 ——\n"
                    f"          最后这条是本次把扫描范围扩到「个版本化提示词」时才发现的。）",
                )
    if not found_any:
        c.note("没有「N 个校验器」这类硬编码数字 —— 这是好事")


# ---------------------------------------------------------------------------
# 4~6. 基线 / 反例 / 净命中
# ---------------------------------------------------------------------------


def check_precision(c: Checker) -> dict:
    head("5.", "基线：可评估性 与 误报")
    codes = available()
    baselines = {m.value: build_clean_ir(m) for m in BASELINE_MEDIA}
    reports = {m: run_all(ir) for m, ir in baselines.items()}
    c.note(f"基线媒介：{'、'.join(baselines)}")

    # -- 全部反例变异只算一遍，供 4a / 4d / 第 7 节复用 --
    #
    # 原先变异只在第 7 节算，结果 4a（无死校验器）与 4d（advisory 非空转）
    # 只能在**基线**这一族输入上判断。对缺陷型检测器来说这是错的：
    # 它们需要的输入（对白、等长段落）基线里根本没有，于是被判成
    # 「死校验器」——而真正的问题是**基线太干净**，不是校验器死了。
    # 把变异族也纳入可评估性判据，是让判据落在「有没有任何输入能跑它」上。
    mutated_reports: dict[str, object] = {}
    mut_crashes: list[str] = []
    for mcode, (mutate, _expected) in MUTATIONS.items():
        mutated = clean_copy()
        mutate(mutated)
        rep = run_all(mutated)
        mutated_reports[mcode] = rep
        for crashed_code, err in sorted(rep.crashes.items()):
            mut_crashes.append(f"{crashed_code} @ 变异 {mcode}: {err}")

    # -- 4a. 每个门禁项至少在一种输入上真的会被执行 --
    live: set[str] = set()
    per_medium: dict[str, int] = {}
    for m, ir in baselines.items():
        cov = coverage_report(ir)
        live |= {r["code"] for r in cov["rows"] if r["evaluable"]}
        per_medium[m] = f"{cov['evaluable']}/{cov['total']}"
    for rep in mutated_reports.values():
        live |= set(rep.evaluated)
    dead = sorted(set(codes) - live)
    c.check(
        not dead,
        f"无死校验器（{len(live)}/{len(codes)} 至少在一种输入上可评估）",
        f"在任何输入（{len(baselines)} 条基线 + {len(MUTATIONS)} 个变异）上都不执行：{dead}\n"
        f"      → 要么所有输入都缺它要的数据，要么需求声明过严。\n"
        f"        一个永远 SKIPPED 的校验器，它的「没问题」是没跑过，不是通过。",
    )
    c.note(
        "各媒介评估覆盖："
        + " · ".join(f"{m} {v}" for m, v in per_medium.items())
    )

    # -- 4b. 基线无误报（跨全部基线取并集）--
    false_positives: list[str] = []
    for m, rep in reports.items():
        for code in codes:
            fs = [f for f in rep.findings if f.code == code]
            if any(SEV[f.severity] >= SEV[Severity.WARN] for f in fs):
                worst = max(fs, key=lambda f: SEV[f.severity])
                false_positives.append(f"{code}({worst.severity.value}@{m})")
    c.check(
        not false_positives,
        "干净 IR 上零误报（0 ERROR + 0 WARN）",
        f"误报：{false_positives}\n"
        f"      → 校验器对着一个正常故事乱报警。要么收紧判据，要么修基线。",
    )
    for m, rep in reports.items():
        c.note(
            f"{m} 健康分 {rep.score()}/100"
            f"（错 {len(rep.errors)} · 警 {len(rep.warnings)}"
            f" · 提示 {len(rep.infos)}）"
        )

    # -- 4c. 校验器不许崩溃（CRASHED 是第四种状态）--
    #
    # 这一条抓的是一类特别隐蔽的缺陷：校验器里有一个分支从来没被真正执行过。
    # 真实案例：`pattern_saturation` 把 `SceneNode.storylet_ids` 写成了
    # `Storylet.storylet_ids`。在没有 storylet 的 IR 上，那个生成器表达式的
    # 循环体根本不求值，所以**永远不报错**；而在有 storylet 的 IR 上必崩。
    # 于是「干净基线全绿」与「这个分支从没跑过」同时成立，漂了很久。
    #
    # 崩溃不产出 Finding（代码 bug 不该扣稿子的健康分），所以它不会自己
    # 浮出来 —— 必须靠这条断言。示例 IR 是**对抗性输入**：它有 storylet、
    # 已登记的谜题等基线没有的结构，能走到基线走不到的分支。
    crash_probes: list = [(f"基线 {m}", ir) for m, ir in baselines.items()]
    try:
        from examples.demo_story import build_demo_ir

        crash_probes.append(("examples/demo_story", build_demo_ir()))
    except Exception as exc:  # 示例本身坏了不算校验器的错，但要留痕
        c.note(f"跳过示例 IR 崩溃探测：{exc!r}")

    crashed: list[str] = []
    for label, probe_ir in crash_probes:
        for code, err in sorted(run_all(probe_ir).crashes.items()):
            crashed.append(f"{code} @ {label}: {err}")
    c.check(
        not crashed,
        f"校验器不崩溃（{len(crash_probes)} 个输入上 Report.crashes 全空）",
        "\n      ".join(crashed)
        + "\n      → 校验器抛异常 = 它有一个分支从来没被真正跑过。\n"
        "        崩溃**不产出 Finding**，所以不会自己浮出来 —— 必须靠这条断言抓。",
    )

    # -- 4d. advisory 通道不许空转（判据按类型分叉）--
    #
    # 机会型（「你接下来可以写什么」）：干净稿子上沉默 = 空转 → 必须在基线上说话。
    # 缺陷型（「文本落在平台的机器区间」）：干净稿子上沉默 = **正确** →
    #   必须在自己的反例上说话。
    #
    # 这条分叉是加合规检测器时被迫发现的：若沿用「基线必须有输出」，
    # 三个合规检测器（等长段落 / 高频副词 / 工整对话）就必须对着一份
    # 干净稿子硬报 —— 为了让断言通过而制造假阳性。
    quiet: list[str] = []
    for code in sorted(ADVISORY):
        on_baseline = any(
            f.code == code for rep in reports.values() for f in rep.advisory
        )
        if code in ADVISORY_DEFECT:
            rep = mutated_reports.get(code)
            on_mutation = rep is not None and any(
                f.code == code for f in rep.advisory
            )
            if not on_mutation:
                quiet.append(f"{code}（缺陷型：反例上未产出）")
        elif not on_baseline:
            quiet.append(f"{code}（机会型：基线上未产出）")
    c.check(
        not quiet,
        f"advisory 项真的会产出（{len(ADVISORY)} 个）",
        f"从不产出：{quiet}\n"
        f"      → 一个永远沉默的报表与不存在没有区别，\n"
        f"        而它还会让覆盖率的分母看起来更完整。\n"
        f"        缺陷型看反例、机会型看基线 —— 用错一边就会逼出假阳性。",
    )

    # -- 5. 反例覆盖 --
    head("6.", "反例覆盖")
    missing_fx = sorted(set(codes) - set(MUTATIONS) - REPORTS)
    c.check(
        not missing_fx,
        f"每个门禁项都有反例 fixture（{len(MUTATIONS)} 个）",
        f"缺反例：{missing_fx}\n"
        f"      → 没有反例的校验器，其「能抓缺陷」是没有证据的宣称。",
    )

    # -- 6. 净命中（严重度升级）--
    head("7.", "净命中率（严重度升级口径）")

    def base_sev(code: str) -> int:
        """在**可评估该 code 的**基线里取最高严重度。"""
        best: int | None = None
        for m, rep in reports.items():
            if code in rep.skipped:
                continue
            sevs = [SEV[f.severity] for f in rep.findings if f.code == code]
            s = max(sevs) if sevs else NONE
            best = s if best is None else max(best, s)
        return best if best is not None else NONE

    print()
    print(f"  {'校验器':<26}{'基线':<6}{'变异':<6}{'净命中':<8}判定")
    print("  " + "─" * 62)

    net_hits = 0
    covered = 0
    misses: list[str] = []
    mut_crashes: list[str] = []
    for code in codes:
        entry = MUTATIONS.get(code)
        if code in REPORTS:
            print(f"  {code:<26}{'·':<6}{'·':<6}{'—':<8}⊘ 报表项")
            continue
        if entry is None:
            print(f"  {code:<26}{'—':<6}{'—':<6}{'—':<8}⊘ 无 fixture")
            continue
        covered += 1
        _mutate, expected = entry
        mutated_report = mutated_reports[code]
        fs = [f for f in mutated_report.findings if f.code == code]
        got = max((SEV[f.severity] for f in fs), default=NONE)
        base = base_sev(code)
        net = got > base and got >= SEV[expected]
        net_hits += int(net)
        if net:
            mark = "✓ 净命中"
        elif got < SEV[expected]:
            mark = "✗ 未达标"
        elif got == base:
            mark = "✗ 基线本就报"
        else:
            mark = "✗ 未升级"
        if not net:
            misses.append(code)
        print(
            f"  {code:<26}{GLYPH[base]:<6}{GLYPH[got]:<6}"
            f"{'是' if net else '否':<8}{mark}"
        )

    print()
    if covered:
        rate = net_hits / covered
        c.note(f"净命中率 {rate:.0%}（{net_hits}/{covered}）")
        if misses:
            c.note(f"未净命中：{misses}")
    c.check(
        net_hits == covered,
        f"全部反例都净命中（{net_hits}/{covered}）",
        "未净命中说明：fixture 没注入到校验器真正检查的字段，"
        "或校验器抓不住这类缺陷。两者都要查。",
    )
    c.check(
        not mut_crashes,
        f"变异输入上校验器不崩溃（{covered} 个变异）",
        "\n      ".join(mut_crashes)
        + "\n      → 缺陷输入把校验器逼进了它从没跑过的分支。",
    )

    return {
        "registry_total": len(codes),
        "gating": registry_stats()["gating"],
        "reports": registry_stats()["reports"],
        "baselines": {m: reports[m].score() for m in reports},
        "false_positives": false_positives,
        "fixtures": covered,
        "net_hits": net_hits,
        "net_hit_rate": (net_hits / covered) if covered else 0.0,
        "misses": misses,
    }


# ---------------------------------------------------------------------------
# 8. 单元测试
# ---------------------------------------------------------------------------


def check_unit_tests(c: Checker) -> None:
    """跑 tests/test_*.py —— 纯函数级的测试也是自证的一部分。

    自动发现，不写死文件名：新增测试文件不需要回来改这里，
    否则「忘了把新测试接进来」会变成一个没人发现的空洞。
    """
    head("8.", "单元测试（tests/test_*.py）")
    files = sorted((ROOT / "tests").glob("test_*.py"))
    if not files:
        c.note("没有单元测试文件")
        return
    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        proc = subprocess.run(
            [sys.executable, str(f)],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        out = proc.stdout + proc.stderr
        tail = [ln for ln in out.strip().splitlines() if ln.strip()][-1:]
        c.check(
            proc.returncode == 0,
            f"{rel} 通过",
            f"退出码 {proc.returncode}\n      {out.strip()[-600:]}",
        )
        if tail:
            c.note(f"{rel}：{tail[0].strip()}")


# ---------------------------------------------------------------------------
# 9. 打包一致性
# ---------------------------------------------------------------------------


def check_packaging(c: Checker) -> None:
    """打包元数据与代码现状是否一致。

    两个真实漂移点：

    1. **版本号**。`pyproject.toml` 里的 `version` 与 `loom.__version__`
       是两处手抄。发版时只改一处，装出去的包就会报一个错的版本 ——
       而这件事**没有任何测试会抓到**，因为本地 import 走的是源码。
    2. **子包覆盖**。若 `packages` 是手抄列表，新增子包忘了同步会
       **静默**从发行包里消失：本地全绿，装出去就缺模块。
       现在用的是 `packages.find`，故这里断言的是「配置确实没有退化成手抄列表」，
       以及「find 的规则真的能覆盖全部子包」。
    """
    head("9.", "打包一致性（pyproject ↔ 代码）")

    pp = ROOT / "pyproject.toml"
    if not c.check(pp.exists(), "pyproject.toml 存在"):
        return
    text = pp.read_text(encoding="utf-8")

    import loom

    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    declared = m.group(1) if m else None
    c.check(
        declared == loom.__version__,
        f"版本号一致（pyproject {declared} == loom.__version__ {loom.__version__}）",
        f"漂移：pyproject 声明 {declared}，代码里是 {loom.__version__}。"
        f"装出去的包会报错版本，而本地测试抓不到。",
    )

    # 手写 packages 列表 = 一定会漂。用 find 就没有列表可漂。
    c.check(
        "packages.find" in text,
        "packages 用 find 派生（不是手抄列表）",
        "检测到手抄的 packages 列表 —— 新增子包忘了同步会静默从发行包里消失。"
        "请改用 [tool.setuptools.packages.find]。",
    )

    actual = sorted(
        d.name for d in (ROOT / "loom").iterdir()
        if d.is_dir() and (d / "__init__.py").exists()
    )
    # 刻意**不做**「无 include 规则就当通过」：那时前缀为空、`startswith("")`
    # 恒真，这一项会变成永远绿却什么也没查的假绿。变异测试抓到过 ——
    # 退化成手抄列表时它照绿不误。没有规则就是**不能判**，要说出来。
    include = re.search(r'include\s*=\s*\[([^\]]+)\]', text)
    if include is None:
        c.note("子包覆盖：跳过（packages 未用 find，无 include 规则可判；"
               "上一项已就此事报错）")
    else:
        # 规则形如 loom*；匹配的目标是 loom.<子包名>，故按前缀判
        prefix = include.group(1).strip().strip('"').rstrip("*")
        missing = [s for s in actual if not f"loom.{s}".startswith(prefix)]
        c.check(
            not missing,
            f"子包覆盖完整（{len(actual)} 个：{', '.join(actual)}）",
            f"以下子包不会被打进发行包：{missing}",
        )

    # 声明了 license 就必须有正文，否则是「声明了一个不存在的授权」。
    lic_declared = re.search(r'^license\s*=', text, re.M) is not None
    lic_file = any(
        (ROOT / n).exists() for n in ("LICENSE", "LICENSE.txt", "COPYING")
    )
    c.check(
        (not lic_declared) or lic_file,
        "声明了 license 且有 LICENSE 正文",
        "pyproject 声明了 license 但仓库里没有 LICENSE 文件 —— "
        "这等于声明了一个不存在的授权。",
    )


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 10. 门禁可信度（校验器自检）
# ---------------------------------------------------------------------------


def _safe_run(fn, ir):
    """跑单个校验器，捕获崩溃（CRASHED 是第四种状态，不能让这一节整体挂掉）。

    返回 finding 列表；若校验器自身抛异常，返回 Exception 实例作为哨兵。
    """
    try:
        return list(fn(ir))
    except Exception as exc:  # noqa: BLE001
        return exc


def check_selfcheck(c: Checker) -> dict:
    """门禁可信度：用合成自检样本给每个门禁 code 算 precision / recall。

    **这不是门禁。** 这里报的是「Loom 之前只报结构分 89、从不报 precision/recall」
    缺失的那块可信度读数。外部证据（ConStory-Checker 等）表明自动一致性检查器
    约 ~68% 准确 —— 我们的门禁也该把自己的命中率摊开给人看。

    硬门禁（违背即 RED）：每个门禁 code 必须至少 1 条 positive + 1 条 negative；
    缺任何一条，这一节 FAIL。

    可信度读数（不门禁，避免 flaky 红）：逐 code 打印 precision/recall；
    precision<0.5 或 recall<0.5 的 code 只打 WARN 行（列出误报样本的
    scene_id / entity_id / evidence），**不计入 verify.py 的失败数**。
    """
    head("10.", "门禁可信度（校验器自检）")
    from loom.validators.base import REPORTS, REQUIRES
    from tests.validator_selfcheck_sets import (
        NOT_FIRING,
        SELFCHECK as SELFCHECK_SETS,
    )

    gating = sorted(set(REQUIRES) - set(REPORTS))

    c.note(
        "诚实声明：本节的 precision/recall 来自**合成/构造**自检样本，不是真实分布；\n"
        "    只用于**校验器之间的相对比较**，不构成绝对准确率。\n"
        "    外部证据（ConStory-Checker 等）显示自动一致性检查器约 ~68% 准确；\n"
        "    Loom 此前只报「结构分 89」而从不报 precision/recall —— 这里补上可信度读数。\n"
        "    样本构造方式见 tests/validator_selfcheck_sets.py 的模块 docstring。"
    )

    # -- HARD GATE：每个门禁 code 必须 ≥1 正例 + ≥1 反例 --
    missing: list[str] = []
    for code in gating:
        entry = SELFCHECK_SETS.get(code)
        if (
            not entry
            or len(entry.get("positive", [])) < 1
            or len(entry.get("negative", [])) < 1
        ):
            missing.append(code)
    c.check(
        not missing,
        f"全部门禁 code 都有 ≥1 正例 + ≥1 反例（{len(gating) - len(missing)}/{len(gating)}）",
        f"缺覆盖：{missing}\n"
        f"      → 每个门禁 code 必须在 SELFCHECK 里同时有 positive 与 negative，\n"
        f"        否则无法计算可信度。去 tests/validator_selfcheck_sets.py 补。",
    )

    # -- 逐 code 计算 precision / recall --
    print()
    print(f"  {'门禁 code':<26}{'P':<7}{'R':<7}{'TP/FN/FP':<12}判定")
    print("  " + "─" * 60)

    rows: list[dict] = []
    warns: list[str] = []
    crashes: list[str] = []
    for code in gating:
        fn = get_validator(code)
        entry = SELFCHECK_SETS.get(code, {"positive": [], "negative": []})
        positives = entry.get("positive", [])
        negatives = entry.get("negative", [])

        tp = fn_count = 0
        for ir in positives:
            res = _safe_run(fn, ir)
            if isinstance(res, Exception):
                crashes.append(f"{code} @ positive: {res!r}")
                continue
            if res:
                tp += 1
            else:
                fn_count += 1

        fp = 0
        for ir in negatives:
            res = _safe_run(fn, ir)
            if isinstance(res, Exception):
                crashes.append(f"{code} @ negative: {res!r}")
                continue
            if res:
                fp += 1
                for f in res:
                    warns.append(
                        f"{code}: {f.code} scene={f.scene_id} ent={f.entity_id} "
                        f"ev={f.evidence}"
                    )

        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn_count) if (tp + fn_count) else None
        pstr = f"{precision:.2f}" if precision is not None else "n/a"
        rstr = f"{recall:.2f}" if recall is not None else "n/a"

        verdict = "✓"
        if precision is not None and precision < 0.5:
            verdict = "!精度低"
        elif recall is not None and recall < 0.5:
            verdict = "!召回低"
        if code in NOT_FIRING:
            verdict = f"⚠未命中({NOT_FIRING[code]})"

        print(
            f"  {code:<26}{pstr:<7}{rstr:<7}"
            f"{tp}/{fn_count}/{fp:<8}{verdict}"
        )
        rows.append(
            {
                "code": code,
                "precision": precision,
                "recall": recall,
                "tp": tp,
                "fn": fn_count,
                "fp": fp,
            }
        )

    if crashes:
        c.note("自检样本中校验器崩溃（不计入门禁失败，但需查）：")
        for cc in crashes:
            c.note("  " + cc)

    c.note(
        f"自检覆盖 {len(gating)} 个门禁 code（positive/negative 各 1 条合成样本）。\n"
        "    低精度/低召回只作可信度 WARN，不判失败：自检集合是合成分布，\n"
        "    用来让门禁之间可比，不代表真实世界准确率。"
    )
    if warns:
        c.note("低精度 code 的误报样本（scene_id / entity_id / evidence）：")
        for w in warns:
            c.note("  " + w)

    return {"gating": len(gating), "rows": rows, "warns": warns, "crashes": crashes}


def main() -> int:
    ap = argparse.ArgumentParser(description="Loom 自证工具")
    ap.add_argument("--json", help="把结果写入 JSON")
    args = ap.parse_args()

    print("═" * 64)
    print("  Loom 自证 —— registry / 报表项 / 文档漂移 / 误报 / 净命中")
    print("═" * 64)

    c = Checker()
    check_registry(c)
    check_reports(c)
    check_readout_speaks(c)
    check_prompts(c)
    check_medium_shape(c)
    check_doc_counts(c)
    summary = check_precision(c)
    check_unit_tests(c)
    check_packaging(c)
    selfcheck = check_selfcheck(c)

    head("结果", "")
    print(f"  通过 {c.passed} · 失败 {len(c.failed)}")
    if c.failed:
        print("  失败项：")
        for f in c.failed:
            print(f"    ✗ {f}")
    print("─" * 64)
    print("  自证未通过。" if c.failed else "  自证通过。")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps(
                {
                    "passed": c.passed,
                    "failed": c.failed,
                    "summary": summary,
                    "selfcheck": selfcheck,
                    "notes": c.notes,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n  已写入 {args.json}")

    return 1 if c.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
