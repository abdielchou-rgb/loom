"""全局漂移门禁 —— 自主长跑（`loom run`）专用的**累积**检查。

**它补的是哪一类缺口（为什么既有校验器都抓不到）：**
仓库里其它校验器全部是**逐场局部**检查 —— 每一场都合格、合起来什么都不证明，
正是本项目存在的理由（铁律 2：「每段都合理、合起来什么都不证明」）。
自主模式一旦开始连续写场景，这个缺口就变成主要风险：模型每一步都局部合理，
但**全局在漂**，而没有任何一个校验器会喊停。本模块只做两件事，都取**尾窗**口径：

    thesis_drift   尾窗是否还在碰「论点面」（控制理念 + 尚未兑现的承诺）
    padding        尾窗是否带来了**任何净推进**（新的状态变量 / 新的价值运动）

── 与相邻校验器的分工（重复报 = 同一件事罚两次分）────────────────

* `premise_fidelity`（structure.py）：**绝对水位**。它问「结局与承诺层还锚定着
  前提吗」，并且读 prose。本模块问的是**水位变化**：尾窗相对**前段**是否掉到零。
  分工因此很干净：一篇**从头到尾都没锚定**前提的稿子归它报 —— 本模块看不到，
  因为「前段命中 > 0」不成立；那时候的病叫「没锚定」，不叫「漂移」。
* `pattern_saturation` / `li_yu_reduce_threads`：**频次**口径（同一装置的
  出现率、窗口内并发支线数）。本模块是**净推进**口径：不关心同一件事出现几次，
  只关心有没有**新东西**进入故事（新的 `(实体, 属性)` 状态键、新的价值-极性走向）。
* `state_delta` / `value_charge_flip`：**逐场**口径。三场各自都翻转价值、
  各自都有状态增量，逐场检查全绿，但合起来可能只是把同一个变量来回拨了三次 ——
  只有尾窗口径抓得到。
* `mice_thread_closure`：ADVISORY **读数项**（无条件产出一行测量，永远不失败）。
  本模块是真门禁：产出 WARN，按自主模式的约定 **WARN 即暂停运行等人**。

── 为什么「漂移」必须比前段，不能只看绝对值 ─────────────────────

「尾窗与控制理念零重叠」这个绝对判据在本仓库的干净基线上**会误报**：
桩件流水线的场景卡是模板化的（「信任的代价第一次被摆到台面上」），
与控制理念（「真正的背叛不是被出卖，而是从未允许别人靠近」）字面上毫无交集 ——
逐场检查谁也不报，因为谁也不看这一层。按绝对值判，基线立刻变红，
而真正要抓的缺陷（**原本在论点上、跑着跑着跑掉了**）会被淹在噪音里。
故本模块取**相对口径**：前段碰过、尾窗完全不碰 = 漂移。

── 出处（每条判据都必须有）────────────────────────────────────

* McKee《Story》(1997) **controlling idea**（控制理念 = 价值 + 原因）：
  它必须由**每一场**的价值转折来表达。`ir.commitment.controlling_idea` 这个
  字段就是按它命名的 —— 本模块只是终于有了一个会读它的校验器
  （这正是本项目反复出现的「有数据、没判据」型缺口）。
* Egri《The Art of Dramatic Writing》(1946)：前提是戏的脊骨，
  每一场都必须推进对前提的论证；停止推进的场次即游离场次
  （`Commitment` 的 docstring 里那句「防漂离论点」就是这条）。
* PLOTTER（*Planning Beyond Text*, ACL 2026 Findings, arXiv:2604.21253）：
  在图上做迭代精炼会**偏离原初前提**（该文 premise fidelity 维度只有 40%）。
  这是**由迭代本身产生的、已知的**漂移 —— 自主长跑正是迭代精炼。
  `premise_fidelity` 只在结尾装了刹车，本模块装的是**跑动中**的那一个。
* Todorov（`Grammaire du Décaméron`, 1969；「叙事即状态变换」）：
  一个事件 = 一个谓词的改变，没有变量移动就没有事件。
  ⇒「尾窗有没有引入**新**的 `(实体, 属性)` 状态键」是推进的直接度量。
* McKee 同书的 **progression**：每一场都要把价值推向**更远**，不是拨回原处。
  ⇒「尾窗有没有出现**新**的价值-极性走向」是第二条度量。

── 判据（只取两端，中间不猜）──────────────────────────────────

两条判据都只在**极端**处开口：命中数为 0 / 净推进为 0。
不用「覆盖率 < 30%」这类阈值 —— 那是一个编出来的数字（铁律 3：无出处的
启发式不许发货）。同项目 `lie_arc_closure` / `secret_reveal_ordering` /
`prose_structure_fidelity` 都只在零重叠时开口，本模块沿用同一条纪律。

── 局限（铁律 7：不宣称做不到的事）────────────────────────────

1. **字面判据**（字符二元组重叠），认不出同义改写：一边反复说着「信任」
   「交付」、一边把故事带到别处，本模块**看不见**。
2. 只比对**结构字段**（turning_point / conflict / value / goal / outcome），
   **不读 prose** —— 正文是渲染视图，不是真值（铁律 1）。代价：只发生在
   正文里的漂移看不见（那部分归 `prose_structure_fidelity` / `premise_fidelity`）。
3. 相对口径 ⇒ **全程都没在论点上**的稿子由本模块沉默（归 `premise_fidelity`）。
4. 不判断「漂移得对不对」：有意的反讽式离题、有意的静场都会被报。
   报出来是给人类裁决的 —— 本模块不产出任何提案，也不改 IR 一个字段。

**数据需求（交给集成方写进 `base.REQUIRES`，本模块刻意不动那张表）：**
`REQUIRES["drift_guard"] = ("scenes>=4", "commitments")` 最贴合 —— 两条判据
都是「尾窗 vs 前段」，前段为空时不可评估。若沿用既有的 `"scenes>=3"` 亦可
（它是必要非充分条件）：3 场时函数自守返回 `[]`（见 `_MIN_RUN`）。
"""

from __future__ import annotations

from ..ir.enums import Severity
from ..ir.models import NarrativeIR
from .base import Finding, register
from .structure import _commitment_evident

__all__ = ["drift_guard"]

#: 尾窗最小宽度与最短可评估运行长度。
#:
#: 窗口 ≥3（「最近一段」低于 3 场不成其为一段），且**必须留出非空的前段** ——
#: 两条判据都是「尾窗 vs 前段」的相对口径，**没有可比对象时判定为不可评估
#: （返回 []），而不是判定为通过**（SKIPPED ≠ PASS）。
_WINDOW_MIN = 3
_MIN_RUN = _WINDOW_MIN + 1


def _shingles(text: str, n: int = 2) -> set[str]:
    """字符 n-gram。中文没有词边界，字符二元组是最省事且零依赖的近似。

    与 `validators/narrative.py::_shingles` 同形 —— 刻意**不 import 那个私有
    函数**：它只有两行，而 import 会在 drift 与 narrative 之间多拉一条与校验
    逻辑无关的耦合边（那正是 `ir/base.py` 下沉基类要躲的那类环）。
    """
    t = "".join(ch for ch in text if not ch.isspace())
    return {t[i : i + n] for i in range(len(t) - n + 1)} if len(t) >= n else set()


def _signature(scene) -> str:
    """场景的**结构**文本 —— 不含 prose（铁律 1：正文是渲染视图，不是真值）。"""
    return " ".join(
        part or ""
        for part in (
            scene.turning_point,
            scene.conflict,
            scene.value,
            scene.goal,
            getattr(scene.outcome, "value", None),
        )
    )


def _delta_keys(scene) -> set[tuple[str, str]]:
    """本场移动的 Todorov 变量：`(实体, 属性)`。"""
    return {(d.entity_id, d.attribute) for d in scene.state_deltas}


def _transition(scene) -> tuple[str, str, str]:
    """本场的 McKee 价值-极性走向：（承载的价值, 起, 止）。"""
    return (scene.value or "", scene.value_charge_start, scene.value_charge_end)


def _trailing_window(scenes: list) -> tuple[list, list]:
    """(前段, 尾窗)。不可评估时返回 `([], [])` —— 调用方据此返回 []。

    窗口宽度取 `max(3, n // 3)`：长跑的「最近一段」理应随篇幅变长
    （30 场里的 3 场只是一口气，不是一段），且**恒留出至少一个前段场次**。
    """
    n = len(scenes)
    if n < _MIN_RUN:
        return [], []
    width = min(n - 1, max(_WINDOW_MIN, n // 3))
    return scenes[:-width], scenes[-width:]


def _thesis_grams(ir: NarrativeIR) -> set[str]:
    """论点面 = 控制理念 + 尚**未兑现**的承诺。

    只收未兑现的：已兑现的承诺不再需要推进，把它们的措辞算进论点面，
    会让一个已经写完的故事因为「尾窗没再提那句已经兑现的话」而报警 ——
    那种报警只会逼作者往结尾里塞口号。
    """
    grams = _shingles(ir.commitment.controlling_idea or "")
    scene_map = {s.id: s for s in ir.scenes}
    for c in ir.commitment.commitments:
        if not _commitment_evident(c, scene_map):
            grams |= _shingles(c.statement or "")
    return grams


@register("drift_guard")
def drift_guard(ir: NarrativeIR) -> list[Finding]:
    """全局漂移门禁：尾窗是否还在论点上、是否还在推进。

    返回 0~2 条 WARN（`evidence["kind"]` 区分 `thesis_drift` / `padding`）。
    不可评估（运行太短、没有可比前段、论点面为空、结构字段全空）时返回 `[]` ——
    **那是「没判」，不是「判过了没问题」**；把它变成 SKIPPED 是
    `base.REQUIRES` 的职责，不是本函数的。
    """
    scenes = ir.ordered_scenes()
    early, window = _trailing_window(scenes)
    if not early or not window:
        return []

    out: list[Finding] = []
    window_ids = [s.id for s in window]
    head = window[-1].id

    # -- ① 论点漂移：前段碰过、尾窗一个字都不碰 --------------------------
    thesis = _thesis_grams(ir)
    if thesis:
        early_grams = _shingles(" ".join(_signature(s) for s in early))
        win_grams = _shingles(" ".join(_signature(s) for s in window))
        # 两侧都得有字数可比 —— 空的那一侧不是「没命中」，是没数据。
        if early_grams and win_grams:
            early_hits = len(thesis & early_grams)
            win_hits = len(thesis & win_grams)
            if early_hits > 0 and win_hits == 0:
                scene_map = {s.id: s for s in ir.scenes}
                open_c = [
                    c.statement
                    for c in ir.commitment.commitments
                    if not _commitment_evident(c, scene_map)
                ]
                out.append(
                    Finding(
                        code="drift_guard",
                        severity=Severity.WARN,
                        scene_id=head,
                        message=(
                            f"论点漂移：最近 {len(window)} 场"
                            f"（{window_ids[0]}…{window_ids[-1]}）与论点面"
                            f"零重叠，而前段 {len(early)} 场命中 {early_hits} 处 —— "
                            "运行正在离开自己的控制理念"
                        ),
                        suggestion=(
                            "自主运行应在此暂停（WARN 即等人）。两条路选一条："
                            "让下一场重新处理控制理念——把它写进 turning_point；"
                            "或者承认控制理念已经变了、改掉它。"
                            "若这段离题是有意的，请在承诺层登记，"
                            "否则它与「忘了」在结构上无法区分。"
                            "继续往下写只会把漂移写得更长"
                        ),
                        evidence={
                            "kind": "thesis_drift",
                            "window_scene_ids": window_ids,
                            "early_scene_count": len(early),
                            "early_hits": early_hits,
                            "window_hits": 0,
                            "controlling_idea": ir.commitment.controlling_idea,
                            "open_commitments": open_c,
                            "thesis_grams": len(thesis),
                            "limitation": (
                                "字面判据（字符二元组）：认不出同义改写，"
                                "也看不见只发生在正文里的漂移（本模块不读 prose）"
                            ),
                        },
                    )
                )

    # -- ② 原地踏步：尾窗没有任何净推进 ----------------------------------
    win_keys = set().union(*(_delta_keys(s) for s in window))
    early_keys = set().union(*(_delta_keys(s) for s in early))
    new_keys = sorted(win_keys - early_keys)

    win_trans = {_transition(s) for s in window}
    early_trans = {_transition(s) for s in early}
    new_trans = sorted(win_trans - early_trans)

    win_deltas = sum(len(s.state_deltas) for s in window)
    win_flips = sum(1 for s in window if s.value_charge_start != s.value_charge_end)

    # (a) 死水：整段既没有状态增量、也没有一场翻转价值 —— Todorov 的「没有事件」
    #     与 McKee 的「没有转折」同时成立，是原地踏步的强形态。
    # (b) 空转：有新变量或新走向中的**任何一个**就算推进；两者皆无，
    #     说明这一整段只把已经拨过的变量拨回原处（净推进为零）。
    # 两条都是**窗口级**判据：逐场检查在 (b) 上全绿（每场都有增量、都翻转），
    # 这正是「每段都合理、合起来什么都不证明」的字面形态。
    if win_deltas == 0 and win_flips == 0:
        reason = "flat_window"
    elif not new_keys and not new_trans:
        reason = "no_new_ground"
    else:
        reason = ""

    if reason:
        out.append(
            Finding(
                code="drift_guard",
                severity=Severity.WARN,
                scene_id=head,
                message=(
                    f"原地踏步：最近 {len(window)} 场"
                    f"（{window_ids[0]}…{window_ids[-1]}）没有带来任何净推进 —— "
                    + (
                        f"整段 {len(window)} 场既无状态增量也无价值翻转"
                        if reason == "flat_window"
                        else f"新状态键 {len(new_keys)} 个、"
                        f"新的价值-极性走向 {len(new_trans)} 个"
                    )
                ),
                suggestion=(
                    "让它推进一件**新**事：引入一个新的 (实体, 属性) 状态键，"
                    "或把价值推向一个没去过的极性。"
                    "若这一段的意图就是静场/呼吸，请把它缩短 —— "
                    "连续若干场零净推进在自主运行里等于空转，"
                    "它消耗的是停止条件之前仅剩的篇幅"
                ),
                evidence={
                    "kind": "padding",
                    "reason": reason,
                    "window_scene_ids": window_ids,
                    "new_delta_keys": new_keys,
                    "new_transitions": new_trans,
                    "window_delta_count": win_deltas,
                    "window_flip_count": win_flips,
                    "window_scene_count": len(window),
                    "limitation": (
                        "只看 IR 结构字段，不读正文；"
                        "若模型每场都新造一个无关紧要的属性名，"
                        "「新状态键」会被刷出来而本条不报"
                    ),
                },
            )
        )

    return out
