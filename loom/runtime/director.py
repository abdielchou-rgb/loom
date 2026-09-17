"""2.0 运行时：Waypoint 骨架 + Storylet 池 + Director。

设计依据：Emily Short《Beyond Branching》(2016)。

    QBN        玩家在「当前合法」的 storylet 中选择
    Salience   系统自动选最贴合当前情境的内容
    Waypoint   系统向下一触发点寻路，玩家可改道 —— 故事自愈

本模块实现三者合一：
    骨架层   Waypoint 序列（作者锁定的必达节拍）
    血肉层   Storylet 池（品质门控 + 显著性排序）
    导演层   Director（用戏剧弧光变量约束选择，防意外坏结局）

为什么 Director 不是可选项：
    Short 明确警告 —— 若显著性被用来编排**事件**（而非只是对白），
    玩家可能「稀里糊涂地满足了被黑帮干掉的全部前置条件」。
    解法是让部分状态变量来自戏剧弧光，而非世界状态。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..ir.models import NarrativeIR, Storylet
from .cooldown import EventCooldownMatrix


@dataclass
class RuntimeState:
    """运行时状态。qualities 是唯一真相源（QBN 的核心）。"""

    qualities: dict[str, object] = field(default_factory=dict)
    current_waypoint: str | None = None
    visited_storylets: list[str] = field(default_factory=list)
    turn: int = 0
    history: list[str] = field(default_factory=list)

    def apply(self, storylet: Storylet) -> None:
        for e in storylet.effects:
            cur = self.qualities.get(e.quality, 0)
            match e.op:
                case "set":
                    self.qualities[e.quality] = e.value
                case "add":
                    self.qualities[e.quality] = (cur if isinstance(cur, (int, float)) else 0) + e.value
                case "sub":
                    self.qualities[e.quality] = (cur if isinstance(cur, (int, float)) else 0) - e.value
        self.visited_storylets.append(storylet.id)
        self.turn += 1


@dataclass
class Selection:
    storylet: Storylet
    score: float
    reason: str


class Director:
    """导演层：drama management。

    学术传统：Weyhrauch (1997) 的搜索式 drama manager / Mateas & Stern 的
    Façade / Magerko 的玩家建模。核心思想是「在合法候选中，按戏剧目标选择」。

    这里实现四个约束：
        1. 弧光对齐   —— 优先推进当前情感弧线所需的方向
        2. 节奏控制   —— 连续高强度后强制降温（防疲劳）
        3. 装置冷却   —— 同一手法/母题用过密则降权（防母题单调）
        4. 安全阀     —— 阻止「意外坏结局」：若某选择会不可逆地关闭主线，降权
    """

    def __init__(
        self,
        arc_shape: str,
        *,
        intensity_window: int = 3,
        cooldown_penalty: float = 0.35,
        safety_penalty: float = 0.8,
        cooldown: EventCooldownMatrix | None = None,
        pattern_penalty: float = 0.35,
    ) -> None:
        self.arc_shape = arc_shape
        self.intensity_window = intensity_window
        self.cooldown_penalty = cooldown_penalty
        self.safety_penalty = safety_penalty
        self.cooldown = cooldown
        self.pattern_penalty = pattern_penalty
        self._recent_intensity: list[float] = []

    def _arc_direction(self, progress: float) -> float:
        """期望的情绪方向（+1 上行 / -1 下行），按弧线形状。"""
        anchors = {
            "rags_to_riches": [(0.0, -1.0), (1.0, 1.0)],
            "tragedy": [(0.0, 1.0), (1.0, -1.0)],
            "man_in_a_hole": [(0.0, 0.0), (0.42, -1.0), (1.0, 0.6)],
            "icarus": [(0.0, -0.6), (0.5, 1.0), (1.0, -1.0)],
            "cinderella": [(0.0, -0.4), (0.35, 0.8), (0.6, -0.8), (1.0, 1.0)],
            "oedipus": [(0.0, 0.6), (0.35, -0.8), (0.6, 0.8), (1.0, -1.0)],
        }.get(self.arc_shape, [(0.0, 0.0), (1.0, 1.0)])

        def interp(x: float) -> float:
            if x <= anchors[0][0]:
                return anchors[0][1]
            if x >= anchors[-1][0]:
                return anchors[-1][1]
            for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
                if x0 <= x <= x1:
                    t = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
                    return y0 + t * (y1 - y0)
            return anchors[-1][1]

        h = 0.02
        return interp(min(1.0, progress + h)) - interp(max(0.0, progress - h))

    def score(
        self,
        storylet: Storylet,
        state: RuntimeState,
        progress: float,
        main_thread_qualities: set[str] | None = None,
        *,
        current_waypoint: str | None = None,
        next_waypoint: str | None = None,
    ) -> Selection:
        base = storylet.salience
        reasons = [f"salience={base:.2f}"]

        # 0. Waypoint 寻路亲和度 —— 这是「故事自愈」的机制
        #    引擎持续把玩家的混乱输入拉回下一个既定节拍。
        if storylet.advances_waypoint:
            if storylet.advances_waypoint == next_waypoint:
                base += 0.6
                reasons.append("寻路+0.60（推进下一节拍）")
            elif storylet.advances_waypoint == current_waypoint:
                base += 0.2
                reasons.append("寻路+0.20（当前节拍）")
            else:
                base -= 0.25
                reasons.append("寻路-0.25（偏离节拍）")
        else:
            base -= 0.1
            reasons.append("寻路-0.10（不推进节拍）")

        # 1. 弧光对齐
        direction = self._arc_direction(progress)
        w = storylet.arc_weights
        if w:
            align = sum(v * direction for v in w.values()) / len(w)
            base += align * 0.5
            reasons.append(f"弧光对齐={align:+.2f}")

        # 2. 节奏冷却
        recent = self._recent_intensity[-self.intensity_window :]
        if recent and sum(recent) / len(recent) > 0.6:
            high = abs(sum(w.values())) if w else 0.0
            if high > 0.5:
                base -= self.cooldown_penalty
                reasons.append(f"冷却-{self.cooldown_penalty}")

        # 3. 装置冷却：手法/母题层面的重复抑制。
        #    逐 storylet 的冷却（上一块）抓不到「五个不同的 storylet 全是打脸」，
        #    这一块按手法冷却均值降权。硬不变量：无矩阵或 patterns 为空时，
        #    增量恒为 0.0，保证既有行为与既有分数完全不变。
        if self.cooldown is not None and storylet.patterns:
            mean_cooldown = sum(
                self.cooldown.get_cooldown(p) for p in storylet.patterns
            ) / len(storylet.patterns)
            penalty = self.pattern_penalty * mean_cooldown
            base -= penalty
            reasons.append(
                f"装置冷却-{penalty:.2f}（{','.join(storylet.patterns)}）"
            )

        # 4. 安全阀：不可逆地关闭主线 = 降权
        if main_thread_qualities:
            for e in storylet.effects:
                if e.quality in main_thread_qualities and e.op == "set" and e.value is False:
                    base -= self.safety_penalty
                    reasons.append(f"安全阀-{self.safety_penalty}（会关闭主线）")

        return Selection(storylet, base, " | ".join(reasons))

    def note_intensity(self, value: float) -> None:
        self._recent_intensity.append(abs(value))


class StoryRuntime:
    """运行时引擎：把 IR 跑成可交互的故事。"""

    def __init__(self, ir: NarrativeIR, *, seed: int | None = None) -> None:
        self.ir = ir
        self.rng = random.Random(seed)
        self.state = RuntimeState(qualities=dict(ir.qualities))
        self.cooldown = EventCooldownMatrix()
        self.director = Director(ir.commitment.arc_shape.value, cooldown=self.cooldown)
        self.waypoints = [s.id for s in ir.ordered_scenes()]
        self.state.current_waypoint = self.waypoints[0] if self.waypoints else None

    # -- 核心：选择下一块内容 --

    def eligible(self) -> list[Storylet]:
        """所有当前合法的 storylet（QBN 的「legal elements」）。

        两道门：
          1. 品质门控 —— preconditions 全部满足
          2. waypoint 门控 —— 挂载在当前 waypoint 上，或全局可用（at_waypoint=None）
        """
        cur = self.state.current_waypoint
        return [
            s
            for s in self.ir.storylets
            if s.eligible(self.state.qualities)
            and (s.at_waypoint is None or s.at_waypoint == cur)
            and (s.repeatable or s.id not in self.state.visited_storylets)
        ]

    def _progress(self) -> float:
        if not self.waypoints or self.state.current_waypoint is None:
            return 0.0
        try:
            idx = self.waypoints.index(self.state.current_waypoint)
        except ValueError:
            return 0.0
        return idx / max(1, len(self.waypoints) - 1)

    def _next_waypoint(self) -> str | None:
        if not self.waypoints or self.state.current_waypoint is None:
            return None
        try:
            idx = self.waypoints.index(self.state.current_waypoint)
        except ValueError:
            return self.waypoints[0]
        return self.waypoints[idx + 1] if idx + 1 < len(self.waypoints) else None

    def _record_patterns(self, selection: Selection) -> Selection:
        """把选中块使用的手法记入冷却矩阵（生成侧的母题使用历史）。"""
        for pattern in selection.storylet.patterns:
            self.cooldown.record_usage(pattern)
        return selection

    def next_storylet(self) -> Selection | None:
        """按 QBN + salience + waypoint 寻路 + director 选择下一块。

        硬不变量（Failbetter 实践）：永远不要给玩家零个选项。
        若合法集为空，回落到兜底块；若连兜底块也没有，回落到骨架推进。
        """
        cands = self.eligible()
        if not cands:
            fallback = [s for s in self.ir.storylets if s.is_fallback]
            if fallback:
                s = self.rng.choice(fallback)
                return self._record_patterns(
                    Selection(s, 0.0, "兜底块（合法集为空 —— 触发硬不变量保护）")
                )
            return None

        progress = self._progress()
        cur_wp = self.state.current_waypoint
        nxt_wp = self._next_waypoint()

        scored = [
            self.director.score(
                s, self.state, progress, None,
                current_waypoint=cur_wp, next_waypoint=nxt_wp,
            )
            for s in cands
        ]
        scored.sort(key=lambda x: -x.score)
        return self._record_patterns(scored[0])

    def advance_waypoint(self) -> str | None:
        """推进到下一个 waypoint（故事自愈：把玩家输入拉回既定节拍）。"""
        if not self.waypoints or self.state.current_waypoint is None:
            return None
        try:
            idx = self.waypoints.index(self.state.current_waypoint)
        except ValueError:
            self.state.current_waypoint = self.waypoints[0]
            return self.state.current_waypoint
        if idx + 1 >= len(self.waypoints):
            return None
        self.state.current_waypoint = self.waypoints[idx + 1]
        self.cooldown.advance_time()
        return self.state.current_waypoint

    def play(self, *, turns: int = 20, verbose: bool = True) -> list[str]:
        """自动跑一段。用于随机化通关测试与回归。"""
        log: list[str] = []
        for _ in range(turns):
            sel = self.next_storylet()
            if sel is None:
                nxt = self.advance_waypoint()
                if nxt is None:
                    log.append("[END] 已到最后一个 waypoint")
                    break
                log.append(f"[WAYPOINT] 推进至 {nxt}（合法集为空，走骨架）")
                continue
            self.state.apply(sel.storylet)
            if sel.storylet.advances_waypoint:
                self.state.current_waypoint = sel.storylet.advances_waypoint
            log.append(
                f"[{self.state.turn:02d}] {sel.storylet.id}  score={sel.score:.2f}  "
                f"({sel.reason})"
            )
            if verbose:
                first = sel.storylet.content.strip().split("\n")[0]
                log.append(f"      「{first}」")
        return log


def randomized_playthroughs(
    ir: NarrativeIR,
    *,
    runs: int = 500,
    turns: int = 30,
) -> dict:
    """随机化通关测试。

    Emily Short 提出的测试方法：跑数千次随机遍历，可视化「从未触达」
    与「过度使用」的序列 —— 这是发现内容死角与热点的主要手段。
    """
    coverage: dict[str, int] = {s.id: 0 for s in ir.storylets}
    waypoint_hits: dict[str, int] = {w: 0 for w in [s.id for s in ir.ordered_scenes()]}
    dead_ends = 0
    zero_option_events = 0

    for r in range(runs):
        rt = StoryRuntime(ir, seed=r)
        if rt.state.current_waypoint in waypoint_hits:
            waypoint_hits[rt.state.current_waypoint] += 1
        for _ in range(turns):
            sel = rt.next_storylet()
            if sel is None:
                zero_option_events += 1
                if rt.advance_waypoint() is None:
                    dead_ends += 1
                    break
                continue
            coverage[sel.storylet.id] = coverage.get(sel.storylet.id, 0) + 1
            rt.state.apply(sel.storylet)
            if sel.storylet.advances_waypoint:
                rt.state.current_waypoint = sel.storylet.advances_waypoint
            if rt.state.current_waypoint in waypoint_hits:
                waypoint_hits[rt.state.current_waypoint] += 1
            # 故事已到最后一个 waypoint，且没有内容再推进 -> 本次遍历结束
            if rt._next_waypoint() is None and sel.storylet.is_fallback:
                break

    never_reached = [k for k, v in coverage.items() if v == 0]
    total = sum(coverage.values()) or 1
    overused = [
        (k, v / total) for k, v in sorted(coverage.items(), key=lambda x: -x[1])[:3]
    ]

    return {
        "runs": runs,
        "dead_ends": dead_ends,
        "zero_option_events": zero_option_events,
        "never_reached": never_reached,
        "overused": overused,
        "coverage": coverage,
        "waypoint_hits": waypoint_hits,
    }
