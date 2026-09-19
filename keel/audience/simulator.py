"""观众模拟器。

**先说清楚这个模块能做什么、不能做什么。**

不能做的：替代真实观众数据。LitBench (EACL 2026) 的结论很硬 ——
零样本 LLM 判断在若干一致性指标上接近随机（UNION 指标 48.7%），
所以「让模型打分」这条路本身不可靠。任何声称「AI 预测爆款」的产品都在撒谎。

能做的，有三件：

  1. **结构性的流失预测**。留存曲线由 IR 的结构信号 + 人格参数算出，
     全程确定性、可复现、可回归测试。它不是「模型的感觉」，
     是一个显式的 hazard 模型 —— 参数可以被团队指着吵，也可以被数据拟合。

  2. **相对比较（这才是真正的用法）**。同一批人格跑两个版本，
     比较留存曲线的差异。LitBench 同样指出：绝对评分不可靠，
     但**配对偏好稳定得多**。所以本模块把 A/B 做成一等公民，
     而不是把绝对分做成卖点。

  3. **把数值翻译成人话**。数值只能告诉你「第 4 场留存掉了 12%」，
     不能告诉你观众会怎么骂。后者交给 Generator（真模型时就是 LLM），
     并且 —— 关键 —— 当确定性模型与 LLM 判断**不一致**时，
     把那场标记出来给人看。分歧本身就是最有价值的信息。

校准状态是显式的：未校准的模拟器只是先验，不是预测。
`calibrate()` 接受真实留存数据，拟合出 base_hazard，
并报出残差 —— 只有一个自由度可拟合，别指望它学到平台的全部规律。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..ir.models import NarrativeIR
from ..llm.base import Generator
from .personas import Persona, panel, select
from .signals import SceneSignals, ir_signals, scene_signals


# ---------------------------------------------------------------------------
# 风险模型
# ---------------------------------------------------------------------------


def hazard(sig: SceneSignals, p: Persona) -> float:
    """单场流失风险（hazard）。

    这是整个模拟器唯一需要「相信」的东西，所以它写得尽量透明：
    七个乘性因子，每一个都对应一条可辩论的创作常识。
    """
    h = p.base_hazard

    # 1. 无钩子 —— 节奏风险。「这章啥也没发生」是网文第一死因。
    if not sig.has_hook:
        h *= 1.0 + 2.5 * p.pacing_standard

    # 2. 文笔风险。slop_score 越高（越像人写的）风险越低。
    prose_gap = max(0.0, (p.prose_standard * 100.0 - sig.slop_score) / 100.0)
    h *= 1.0 + 3.5 * prose_gap

    # 3. 悬念真空。一个未解之谜都没有 = 没有理由翻下一页。
    #
    # 重要例外：**终局不适用**。结尾把所有线收完不是缺陷，是完成度。
    # 把「没有悬念」当成流失原因会系统性地惩罚收得干净的作品，
    # 所以这条只在故事中段生效（position < 1.0）。
    if sig.open_enigmas == 0 and sig.position < 0.999:
        h *= 1.0 + 2.5 * p.curiosity

    # 4. 信息过载。单场塞太多谜题动作，观众消化不了。
    if sig.info_density > p.max_info_density:
        h *= 1.0 + 0.6 * (sig.info_density - p.max_info_density)

    # 5. 反转稀缺。累计缺乏价值翻转会让「想要反转」的人群失去兴趣。
    if not sig.flips:
        h *= 1.0 + 1.5 * p.twist_appetite

    # 6. 回收奖励。这一场「给到了」就大幅降低流失 —— 兑现承诺是有回报的。
    if sig.resolved_enigmas > 0:
        h *= max(0.25, 1.0 - 0.55 * p.payoff_need)

    # 7. 情绪平坡。与上一场几乎没有落差 = 读起来像温水。
    if sig.index > 0 and abs(sig.emotion_delta) < 0.15:
        h *= 1.0 + 0.8 * p.pacing_standard

    # 开场宽限：观众会多给前两场一点耐心（但只给两场）。
    if sig.index < 2:
        h *= 0.55

    return min(0.95, max(0.0, h))


def retention_curve(
    signals: list[SceneSignals], p: Persona
) -> list[float]:
    """逐场留存率。S_i = S_{i-1} · (1 - h_i)，S_{-1} = 1.0。"""
    curve: list[float] = []
    s = 1.0
    for sig in signals:
        s *= 1.0 - hazard(sig, p)
        curve.append(round(s, 4))
    return curve


def _persona_brief(p: Persona) -> str:
    """把人格渲染成人能读的一段话。

    直接把 dict 塞进提示词会得到 `{'id': 'prestige_viewer', ...}` 这种
    Python 字面量 —— 模型能读，但那是在浪费它的注意力，而且每次格式都可能变。
    """
    return (
        f"{p.label}（{p.platform}）\n"
        f"{p.notes}\n"
        f"偏好刻度：爱反转 {p.twist_appetite} · 好奇心 {p.curiosity} · "
        f"文笔要求 {p.prose_standard} · 节奏要求 {p.pacing_standard} · "
        f"回报需求 {p.payoff_need}"
    )


def _scene_brief(ir: NarrativeIR, *, per_scene_chars: int = 120) -> str:
    """逐场摘要。给模型的**不是全文** —— 定性判断只需要骨架 + 一点质地。

    截断是刻意的：观众模拟会为**每个人格**调一次模型（默认 3 个），
    把全文灌三遍是纯浪费；而截断到 120 字仍然保留了「这一场发生了什么」。
    """
    lines: list[str] = []
    for i, s in enumerate(ir.ordered_scenes(), start=1):
        body = (s.prose or "").strip().replace("\n", " ")
        if len(body) > per_scene_chars:
            body = body[:per_scene_chars] + "…"
        lines.append(
            f"第 {i} 场《{s.title or s.id}》"
            f"（{s.location or '地点未定'} · {s.fabula_time.label or ''}）\n"
            f"  目标：{s.goal}\n"
            f"  转折：{s.turning_point}\n"
            f"  结果：{s.outcome.value}　价值：{s.value}"
            f"{s.value_charge_start}→{s.value_charge_end}\n"
            f"  正文片段：{body or '（未写）'}"
        )
    return "\n\n".join(lines) or "（没有场景）"


def per_scene_survival(signals: list[SceneSignals], p: Persona) -> float:
    """单场平均存活率（几何平均）。

    为什么需要这个：累计留存必然随篇幅变长而下降 —— 那是「篇幅」的效应，
    不是「质量」的效应。拿两个长度不同的版本比终局留存，
    等于在比谁更短，是个混杂了长度的伪结论。

    几何平均把长度效应除掉，回答的是「每一场平均有多抓人」，
    这才是跨篇幅可比的量。两个指标一起看才有意义：
      单场存活率高 + 终局留存低 → 每场都好，但太长了
      单场存活率低 + 终局留存高 → 靠短取胜，内容本身不抓人
    """
    import math

    if not signals:
        return 1.0
    logs = [math.log(max(1e-6, 1.0 - hazard(s, p))) for s in signals]
    return float(math.exp(sum(logs) / len(logs)))


# ---------------------------------------------------------------------------
# 结果
# ---------------------------------------------------------------------------


@dataclass
class PersonaVerdict:
    persona: Persona
    curve: list[float]
    drop_at_index: int | None
    """留存跌破 drop_floor 的场次下标；None = 看完。"""
    retained_at_end: float
    peak_risk_index: int
    peak_risk: float
    per_scene: float = 1.0
    """单场平均存活率（长度无关）。"""
    llm: dict[str, Any] = field(default_factory=dict)
    llm_drop_at: int | None = None

    @property
    def drop_at_scene(self) -> str | None:
        return None if self.drop_at_index is None else f"sc{self.drop_at_index + 1}"

    @property
    def disagreement(self) -> bool:
        """确定性模型与 LLM 判断是否冲突 —— 冲突场次值得人工看一眼。"""
        if self.llm_drop_at is None and self.drop_at_index is None:
            return False
        if self.llm_drop_at is None or self.drop_at_index is None:
            return True
        return abs(self.llm_drop_at - (self.drop_at_index + 1)) >= 2

    def sparkline(self, width: int = 8) -> str:
        """留存曲线的字符可视化。一眼看出在哪一场掉的。"""
        blocks = "▁▂▃▄▅▆▇█"
        if not self.curve:
            return ""
        return "".join(
            blocks[min(7, max(0, int(round(v * (len(blocks) - 1)))))]
            for v in self.curve
        )


@dataclass
class AudienceReport:
    medium: str
    signals: list[SceneSignals]
    verdicts: list[PersonaVerdict]
    aggregate: dict[str, Any] = field(default_factory=dict)
    calibration: dict[str, Any] = field(default_factory=dict)

    @property
    def weighted_retention(self) -> float:
        tot_w = sum(v.persona.weight for v in self.verdicts) or 1.0
        return sum(v.retained_at_end * v.persona.weight for v in self.verdicts) / tot_w

    @property
    def weakest_scene(self) -> str | None:
        """全评审团平均流失最高的那一场 —— 最该改的地方。"""
        if not self.signals:
            return None
        n = len(self.signals)
        worst_i, worst = 0, -1.0
        for i in range(n):
            avg_h = sum(
                hazard(self.signals[i], v.persona) for v in self.verdicts
            ) / max(1, len(self.verdicts))
            if avg_h > worst:
                worst_i, worst = i, avg_h
        return f"sc{worst_i + 1}"

    @property
    def disagreement_scenes(self) -> list[str]:
        """结构模型与 LLM 判断不一致的场次 —— 最该人工看一眼的地方。"""
        out: list[str] = []
        for v in self.verdicts:
            if not v.disagreement:
                continue
            # 优先用结构模型的判定（它是确定性的、可复现的）；
            # 结构模型判「不弃」时才退回到 LLM 的判定。
            if v.drop_at_index is not None:
                sid = f"sc{v.drop_at_index + 1}"
            elif v.llm_drop_at:
                sid = f"sc{v.llm_drop_at}"
            else:
                sid = "全篇"
            if sid not in out:
                out.append(sid)
        return out

    def render(self) -> str:
        L: list[str] = []
        L.append("── 观众模拟 " + "─" * 46)
        if self.calibration.get("status") == "uncalibrated":
            L.append("  ⚠ 未校准：以下数字是**先验**，不是预测。")
            L.append("    用 calibrate() 喂入真实留存数据后才有预测力。")
        else:
            c = self.calibration
            L.append(
                f"  已校准：base_hazard={c.get('base_hazard'):.4f}"
                f"  样本 {c.get('n')}  残差 {c.get('rmse'):.4f}"
            )
        L.append("")
        for v in sorted(self.verdicts, key=lambda x: -x.persona.weight):
            tail = f"看完（终局留存 {v.retained_at_end:.0%}）"
            if v.drop_at_index is not None:
                tail = f"第 {v.drop_at_index + 1} 场弃（留存 {v.retained_at_end:.0%}）"
            L.append(f"  {v.persona.label:<14} {v.sparkline():<10} {tail}")
            if v.llm:
                if v.llm.get("complaint"):
                    L.append(f"      抱怨：{v.llm['complaint']}")
                if v.llm.get("highlight"):
                    L.append(f"      高光：{v.llm['highlight']}")
                if v.disagreement:
                    L.append(
                        f"      ⚠ 分歧：结构模型判 {v.drop_at_scene or '不弃'}"
                        f"，模型判 {v.llm_drop_at or '不弃'} —— 建议人工复核"
                    )
        L.append("")
        L.append(f"  加权终局留存  {self.weighted_retention:.1%}")
        L.append(f"  最弱场次      {self.weakest_scene or '—'}")
        if self.disagreement_scenes:
            L.append(f"  待人工复核    {', '.join(self.disagreement_scenes)}")
        L.append("─" * 56)
        return "\n".join(L)

    def to_dict(self) -> dict[str, Any]:
        return {
            "medium": self.medium,
            "signals": [s.as_dict() for s in self.signals],
            "weighted_retention": round(self.weighted_retention, 4),
            "weakest_scene": self.weakest_scene,
            "calibration": self.calibration,
            "verdicts": [
                {
                    "persona": v.persona.id,
                    "label": v.persona.label,
                    "curve": v.curve,
                    "drop_at": v.drop_at_scene,
                    "llm_drop_at": v.llm_drop_at,
                    "disagreement": v.disagreement,
                    "retained_at_end": v.retained_at_end,
                    "llm": v.llm,
                }
                for v in self.verdicts
            ],
        }


# ---------------------------------------------------------------------------
# A/B
# ---------------------------------------------------------------------------


@dataclass
class ABResult:
    """两个版本的配对比较。

    这是本模块**推荐的主要用法**。绝对留存数字依赖未验证的 base_hazard，
    但「A 在 5 个人格上、8 场里赢了 7 场」这种相对结论要稳得多。
    """

    label_a: str
    label_b: str
    per_persona: list[dict[str, Any]] = field(default_factory=list)

    @property
    def win_rate_a(self) -> float:
        if not self.per_persona:
            return 0.0
        return sum(1 for r in self.per_persona if r["winner"] == "A") / len(
            self.per_persona
        )

    def tally(self) -> dict[str, int]:
        """胜/负/平计数。平局多本身是结论 —— 说明两版在结构上等价。"""
        out = {"A": 0, "B": 0, "平": 0}
        for r in self.per_persona:
            out[r["winner"]] = out.get(r["winner"], 0) + 1
        return out
    def render(self) -> str:
        L = ["── 观众 A/B 对比 " + "─" * 42]
        L.append(f"  A = {self.label_a}")
        L.append(f"  B = {self.label_b}")
        L.append("")
        L.append("  单场存活率（长度无关，看「每场有多抓人」）")
        for r in self.per_persona:
            L.append(
                f"    {r['label']:<14} A {r['per_scene_a']:.1%}  vs  "
                f"B {r['per_scene_b']:.1%}   → {r['winner']}"
            )
        L.append("")
        L.append("  终局留存（含篇幅效应，看「读完的概率」）")
        for r in self.per_persona:
            L.append(
                f"    {r['label']:<14} A {r['retention_a']:.0%}  vs  "
                f"B {r['retention_b']:.0%}   （A 领先 {r['advantage']:+.1%}）"
            )
        L.append("")
        t = self.tally()
        L.append(
            f"  按单场存活率：A 胜 {t['A']} · B 胜 {t['B']} · 平 {t['平']}"
            f"（{len(self.per_persona)} 个人格）"
        )
        if t["平"] == len(self.per_persona) and self.per_persona:
            L.append(
                "  全平 —— 两个版本在**结构上等价**，终局留存的差距纯粹来自篇幅。"
                " 这种情况通常说明改动只加了量，没加质。"
            )
        L.append("")
        L.append("  两个指标必须一起看：")
        L.append("    单场高 + 终局低 → 每场都好，但篇幅太长")
        L.append("    单场低 + 终局高 → 靠短取胜，内容本身不抓人")
        L.append("  只看终局留存会比较谁更短 —— 那是篇幅效应，不是质量。")
        L.append("  另外：相对比较远比绝对分数可信，绝对分依赖未校准的 base_hazard。")
        L.append("─" * 56)
        return "\n".join(L)


# ---------------------------------------------------------------------------
# 模拟器
# ---------------------------------------------------------------------------


class AudienceSimulator:
    """把 IR 跑过一群人格，得到留存曲线与观众原话。"""

    def __init__(
        self,
        gen: Generator | None = None,
        *,
        calibrated: dict[str, Any] | None = None,
    ) -> None:
        self.gen = gen
        self.calibration: dict[str, Any] = calibrated or {"status": "uncalibrated"}

    # -- 主入口 --

    def run(
        self,
        ir: NarrativeIR,
        *,
        personas: list[str] | None = None,
        qualitative: bool = True,
    ) -> AudienceReport:
        sigs = scene_signals(ir)
        people = select(personas) if personas else panel(ir.medium.value)
        agg_signals = ir_signals(ir)

        verdicts: list[PersonaVerdict] = []
        for p in people:
            curve = retention_curve(sigs, p)
            drop = next(
                (i for i, v in enumerate(curve) if v < p.drop_floor), None
            )
            peak_i = (
                max(range(len(sigs)), key=lambda i: hazard(sigs[i], p))
                if sigs
                else 0
            )
            v = PersonaVerdict(
                persona=p,
                curve=curve,
                drop_at_index=drop,
                retained_at_end=curve[-1] if curve else 1.0,
                peak_risk_index=peak_i,
                peak_risk=hazard(sigs[peak_i], p) if sigs else 0.0,
                per_scene=per_scene_survival(sigs, p),
            )
            if qualitative and self.gen is not None:
                v.llm = self._qualitative(agg_signals, p, ir)
                v.llm_drop_at = v.llm.get("drop_at_scene")
            verdicts.append(v)

        return AudienceReport(
            medium=ir.medium.value,
            signals=sigs,
            verdicts=verdicts,
            aggregate=agg_signals,
            calibration=dict(self.calibration),
        )

    def _qualitative(
        self, signals: dict[str, Any], p: Persona, ir: NarrativeIR
    ) -> dict[str, Any]:
        """让模型以某个人格给出定性判断。

        **这里修过一个真缺陷**：AUDIENCE 模板要 `{persona}` / `{genre}` /
        `{logline}` / `{scenes}`，而调用方只给了 `signals` 和 `persona`。
        于是每一次渲染都走 `Prompt.render()` 的降级分支 ——
        模型拿到的是「没填的模板 + 一份 JSON 附录」。

        这个缺陷**在 MockGenerator 下永远看不见**：桩件按 task 分派到确定性函数，
        从头到尾不碰提示词。所以它不是「桩件下正常」，是**桩件下没被检查**。
        """
        assert self.gen is not None
        out = self.gen.generate(
            "audience",
            {
                # `signals` 保持**字典**：桩件与下游代码按结构化取值。
                # 给提示词的是 `signals_text`（渲染好的文本）——
                # 把 JSON 字符串塞进结构化字段，会让所有按字段读的消费者一起崩。
                "signals": signals,
                "signals_text": json.dumps(signals, ensure_ascii=False, indent=2),
                "persona_brief": _persona_brief(p),
                "medium": ir.medium.value,
                "logline": ir.commitment.logline or "（无）",
                "scenes": _scene_brief(ir),
                "persona": {
                    "id": p.id,
                    "label": p.label,
                    "platform": p.platform,
                    "notes": p.notes,
                    "sensitivity": {
                        "twist_appetite": p.twist_appetite,
                        "curiosity": p.curiosity,
                        "prose_standard": p.prose_standard,
                        "pacing_standard": p.pacing_standard,
                        "payoff_need": p.payoff_need,
                        "max_info_density": p.max_info_density,
                    },
                },
            },
        )
        return out if isinstance(out, dict) else {}

    # -- A/B --

    def ab(
        self,
        ir_a: NarrativeIR,
        ir_b: NarrativeIR,
        *,
        label_a: str = "版本 A",
        label_b: str = "版本 B",
        personas: list[str] | None = None,
    ) -> ABResult:
        ra = self.run(ir_a, personas=personas, qualitative=False)
        rb = self.run(ir_b, personas=personas, qualitative=False)
        by_id_b = {v.persona.id: v for v in rb.verdicts}

        res = ABResult(label_a=label_a, label_b=label_b)
        for va in ra.verdicts:
            vb = by_id_b.get(va.persona.id)
            if vb is None:
                continue
            adv = va.retained_at_end - vb.retained_at_end
            adv_ps = va.per_scene - vb.per_scene
            res.per_persona.append(
                {
                    "persona": va.persona.id,
                    "label": va.persona.label,
                    "retention_a": va.retained_at_end,
                    "retention_b": vb.retained_at_end,
                    "per_scene_a": va.per_scene,
                    "per_scene_b": vb.per_scene,
                    "advantage": adv,
                    "advantage_per_scene": adv_ps,
                    # 胜负按长度无关的指标判定 —— 否则「更短」会自动获胜
                    "winner": "A" if adv_ps > 0.002 else ("B" if adv_ps < -0.002 else "平"),
                }
            )
        return res

    # -- 校准 --

    def calibrate(
        self,
        observed: list[float],
        persona: Persona,
        signals: list[SceneSignals],
        *,
        lo: float = 0.001,
        hi: float = 0.5,
        iters: int = 60,
    ) -> dict[str, Any]:
        """用一个自由度拟合 base_hazard，使预测曲线逼近真实留存曲线。

        只有一个自由度。这意味着它能校正**整体量级**（这个人群到底多容易跑），
        但不能学到「第 4 场为什么特别差」这类结构信息 —— 那部分必须来自
        结构信号本身。诚实地把这个限制写在返回里。
        """
        import dataclasses

        if len(observed) != len(signals):
            raise ValueError(
                f"观测长度 {len(observed)} 与场景数 {len(signals)} 不一致"
            )

        def curve_for(bh: float) -> list[float]:
            p2 = dataclasses.replace(persona, base_hazard=bh)
            return retention_curve(signals, p2)

        def err(bh: float) -> float:
            c = curve_for(bh)
            return sum((a - b) ** 2 for a, b in zip(c, observed)) / max(
                1, len(observed)
            )

        for _ in range(iters):
            mid = (lo + hi) / 2
            if err(mid) < err(hi):
                hi = mid
            else:
                lo = mid
        best = (lo + hi) / 2
        c = curve_for(best)
        rmse = (sum((a - b) ** 2 for a, b in zip(c, observed)) / max(1, len(observed))) ** 0.5

        self.calibration = {
            "status": "calibrated",
            "persona": persona.id,
            "base_hazard": best,
            "n": len(observed),
            "rmse": rmse,
            "note": "单自由度拟合，只校正整体量级，不解释逐场差异。",
        }
        return dict(self.calibration)
