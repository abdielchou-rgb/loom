"""确定性参考生成器（离线可跑）。

这不是「假的 LLM」，而是一份**可执行的架构说明**：它用确定性规则产出
结构合法的中间结果，证明整条流水线的数据流是通的，且每个环节的产物
都能通过校验器。

价值：
  1. 无 API key 也能端到端验证架构
  2. 回归测试的基线（确定性 = 可断言）
  3. 接真模型时只需替换 Generator，下游零改动

注意：它产出的文本刻意**不是 AI 味**的（句长有起伏、无陈词滥调），
以便反 slop 模块的对比有意义。
"""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any

from ..ir.arcs import arc_curve
from ..ir.enums import ArcShape, SceneOutcome


def _rng(payload: dict[str, Any]) -> random.Random:
    raw = repr(sorted(payload.items())).encode("utf-8")
    return random.Random(int(hashlib.sha256(raw).hexdigest()[:12], 16))


def _arc_of(payload: dict[str, Any]) -> ArcShape:
    """从 payload 里取出声明的弧线形状，取不到则退化为 man_in_a_hole。"""
    raw = payload.get("arc_shape")
    if isinstance(raw, ArcShape):
        return raw
    try:
        return ArcShape(raw)
    except (ValueError, TypeError):
        return ArcShape.MAN_IN_A_HOLE


# ---------------------------------------------------------------------------
# 语料（刻意保持朴素，避免任何 AI 味模式）
# ---------------------------------------------------------------------------

_SENT_SHORT = [
    "他没有回头。",
    "风停了。",
    "刀在鞘里。",
    "她把灯吹灭。",
    "门关上了。",
    "雪还在下。",
    "他数到三。",
    "没人应声。",
]

_SENT_MID = [
    "他把手按在门框上，停了很久才推开。",
    "院子里的脚印一直延伸到墙根，然后消失。",
    "她把碗推到他面前，没有看他。",
    "远处有人在敲更，敲了三下就停了。",
    "桌上的茶凉透了，杯壁结着一圈印子。",
    "他数了数包袱里的东西，比昨天少了一件。",
]

_SENT_LONG = [
    "他想起很多年前的一个下午，父亲在院子里磨刀，磨了很久，久到太阳偏西，"
    "而他从头到尾没敢问那把刀是给谁准备的。",
    "她说这话的时候语气很平，平到听不出是在陈述还是在试探，"
    "而他知道自己无论怎么答都会落在她预设的格子里。",
    "雪落在檐下化成了水，水顺着瓦沟流下去，在台阶上结了一层薄冰，"
    "谁踩上去都会滑一下，谁都不会承认自己滑过。",
]


def _prose_for(scene: dict[str, Any], rng: random.Random) -> str:
    """按场景卡拼装正文。刻意制造句长起伏。

    注意：句池是**无放回**抽样的。有放回会让同一段里出现
    「她把碗推到他面前，没有看他。她把碗推到他面前，没有看他。」
    这种重复 —— 那不是「朴素」，那是机器味，会污染反 slop 模块的对比基准。
    """
    paras: list[str] = []

    openers = {
        "+": ["天亮了。", "他把信收进袖中。", "她先开的口。"],
        "-": ["天没亮他就醒了。", "雨还没停。", "话说到一半就断了。"],
    }
    paras.append(rng.choice(openers.get(scene.get("value_charge_start", "+"), openers["+"])))

    body: list[str] = []
    n = rng.randint(4, 6)
    pool = list(_SENT_SHORT) + list(_SENT_MID) + list(_SENT_LONG)
    for _ in range(n):
        roll = rng.random()
        if roll < 0.35:
            bucket = list(_SENT_SHORT)
        elif roll < 0.8:
            bucket = list(_SENT_MID)
        else:
            bucket = list(_SENT_LONG)
        # 优先取没用过的；用完了再从全池里取
        cand = [s for s in bucket if s not in body] or [
            s for s in pool if s not in body
        ] or bucket
        body.append(rng.choice(cand))
    paras.append("".join(body))

    goal = scene.get("goal", "")
    conflict = scene.get("conflict", "")
    if conflict:
        paras.append(f"他要的是{_strip(goal)}。挡在前面的，是{_strip(conflict)}。")

    tail_cand = [s for s in _SENT_MID if s not in body] or _SENT_MID
    paras.append(rng.choice(tail_cand))

    return "\n".join(paras)


def _strip(text: str) -> str:
    """去掉提示词式的开头，让句子读起来像正文。

    这一步存在的理由：场景卡的 goal 字段是给机器看的自然语言
    （「主角想要在这一场拿到信任的确认」），直接塞进正文会露馅。
    真实模型不需要这个，但保留它能让离线基准也产出像样的文本，
    从而让反 slop 模块的对比有意义。

    前缀按长度降序匹配 —— 否则「主角想」会先把「主角想要」切一半，
    留下一个孤零零的「要」。
    """
    s = str(text or "")
    prefixes = (
        "主角想要", "主角想", "主角要",
        "同伴想要", "同伴想", "同伴要",
        "他想要", "他想", "她想要", "她想",
    )
    for prefix in sorted(prefixes, key=len, reverse=True):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    # 「在这一场」这类结构性措辞也去掉
    s = s.replace("在这一场", "").strip("。，")
    # 去掉切剩下的孤立「要」
    if s.startswith("要") and not s.startswith("要么"):
        s = s[1:]
    return s.strip("。，")


# ---------------------------------------------------------------------------
# 媒介形态：桩件也必须产出**形态正确**的正文
# ---------------------------------------------------------------------------
#
# 为什么桩件要分媒介：桩件是「无 key 也能跑」的基线，也是回归测试的基准。
# 如果它对「剧本」同样产出小说散文，那么离线永远验证不出
# 「选了剧本却产出小说」这一类缺陷 —— 而这类缺陷恰恰只能靠**形态**发现，
# 靠读一遍正文看不出来（散文读起来也通顺，它只是不是剧本）。
#
# 形态规格的权威定义在 `ir/medium_craft.py`，这里只做转写。
# 两处若不一致，说明转写漏了，不是定义该改。

#: 带内外景标记的地点。剧本的场景标题只有这一个来源。
_LOCATIONS = [
    "内景·书房",
    "外景·码头",
    "内景·客栈大堂",
    "外景·巷口",
    "内景·柴房",
    "外景·河滩",
]

#: 时间标记。与 `location` 同样是剧本场景标题的唯一来源。
_TIMES = ["夜", "日", "黄昏", "清晨", "三日后", "夜"]

#: 地点名（不带内外景标记）。结构层输出带标记，圣经里登记**不带标记**的名字 ——
#: 这样 `entity_reference` 走别名索引能查到，也顺带证明了「内景·书房」与
#: 「书房」应当指向同一处。
_PLACES = ["书房", "码头", "客栈大堂", "巷口", "柴房", "河滩"]

_DIALOGUE = [
    "你昨夜去哪了。",
    "出门。",
    "门闩是从外面插的。",
    "这话你留着跟她讲。",
    "我数到三，你再说一遍。",
    "桌上那把刀不是我的。",
    "你认错人了。",
    "这一次我不拦你。",
]

_CHOICES = [
    "推门进去",
    "先绕到窗边看一眼",
    "收回手，转身下楼",
    "把刀留在桌上",
    "把话问完再走",
]

_PANEL_SHOTS = [
    "一只手按在门框上，指节发白。",
    "桌面的裂缝，刀压在缝上。",
    "两个人的侧脸，中间隔着一张空椅。",
    "地上的耳环，反着一点光。",
    "雨从檐口连成一条线落下来。",
]

_TRANSITIONS = [
    "动作到动作", "瞬间到瞬间", "主体到主体",
    "场景到场景", "视角到视角", "无关联",
]


def _cast_of(payload: dict[str, Any], scene: dict[str, Any]) -> list[str]:
    """出场者**显示名**。

    提示词里传的是显示名（`cast`），不是 IR 内部 id。桩件必须用同一份来源，
    否则它验证的就不是真实链路 —— 而正文里冒出 `protagonist` 这种内部标识，
    正是「架构泄漏到产品」的典型症状，基线里绝不能出现。
    """
    cast = [str(c) for c in (payload.get("cast") or []) if c]
    if cast:
        return cast
    return [str(c) for c in (scene.get("entities") or []) if c] or ["甲", "乙"]


def _topic_of(scene: dict[str, Any]) -> str:
    """这一场在争的那个词（`value`，如「信任」「代价」）。

    为什么每种形态都要带上它：`prose_structure_fidelity` 判的是
    「正文有没有兑现这一场声明的转折点/冲突」。原先用固定语料写剧本，
    正文与该场声明**零词汇交集**，门禁于是正确地报了「疑似跑题」——
    那是桩件的缺陷，不是门禁的误报：一份跟场景卡无关的正文，
    不管排版成什么样，它都是跑题的。
    """
    return str(scene.get("value") or "").strip() or "这件事"


def _screenplay_for(
    scene: dict[str, Any], rng: random.Random, cast: list[str], *, micro: bool = False
) -> str:
    """主场景剧本格式：动作线 + 人物提示行 + 对白。

    刻意**不写场景标题** —— 标题由 `render_fountain` 按 location 生成，
    桩件写了会重复，那就不是在模拟守规矩的模型。
    """
    a = cast[0]
    b = cast[1] if len(cast) > 1 else cast[0]
    topic = _topic_of(scene)
    dlg = rng.sample(_DIALOGUE, 3)
    act = rng.sample(_SENT_MID, 2)
    beat = rng.sample(_SENT_SHORT, 2)
    if micro:
        # 微短剧：开场即冲突，动作线更短，收在悬念而不是转场上
        return "\n\n".join([
            beat[0] + beat[1],
            f"{a}\n{dlg[0]}",
            beat[0],
            f"{b}\n{dlg[1]}",
            f"{a}\n{topic}？这两个字你说得倒轻巧。",
        ])
    return "\n\n".join([
        act[0],
        f"{a}\n{dlg[0]}",
        beat[0],
        f"{b}\n{dlg[1]}",
        act[1],
        f"{a}\n{topic}？这两个字你说得倒轻巧。",
        "CUT TO:",
    ])


def _comic_for(scene: dict[str, Any], rng: random.Random, cast: list[str]) -> str:
    a = cast[0]
    b = cast[1] if len(cast) > 1 else cast[0]
    topic = _topic_of(scene)
    shots = rng.sample(_PANEL_SHOTS, 3)
    trans = rng.sample(_TRANSITIONS, 3)
    dlg = rng.sample(_DIALOGUE, 2)
    panels: list[str] = []
    for i in range(3):
        block = f"格 {i + 1}｜画面：{shots[i]}\n"
        if i == 1:
            block += f"     ｜对白：{a}「{dlg[0]}」\n"
        elif i == 2:
            block += f"     ｜对白：{b}「{topic}？这两个字你说得倒轻巧。」\n"
            block += "     ｜音效：嗒。\n"
        block += f"     ｜转场：{trans[i]}"
        panels.append(block)
    return "\n\n".join(panels)


def _if_for(scene: dict[str, Any], rng: random.Random) -> str:
    topic = _topic_of(scene)
    act = rng.sample(_SENT_MID, 1)[0]
    beat = rng.sample(_SENT_SHORT, 1)[0]
    choices = rng.sample(_CHOICES, 3)
    return (
        act + "\n" + beat + f"\n所有人都在等一个说法：{topic}。\n\n"
        + "\n".join(f"* {c}" for c in choices)
    )


def _vn_for(scene: dict[str, Any], rng: random.Random, cast: list[str]) -> str:
    a = cast[0]
    b = cast[1] if len(cast) > 1 else cast[0]
    topic = _topic_of(scene)
    dlg = rng.sample(_DIALOGUE, 3)
    return "\n".join([
        "【背景：客栈大堂 - 夜】",
        f"【立绘：{a}-平静】",
        f"{a}「{dlg[0]}」",
        f"{b}「{dlg[1]}」",
        f"【立绘：{b}-冷】",
        f"{b}「{topic}？这两个字你说得倒轻巧。」",
        "旁白：" + rng.sample(_SENT_MID, 1)[0],
    ])


def _mm_for(scene: dict[str, Any], rng: random.Random, cast: list[str]) -> str:
    a = cast[0]
    topic = _topic_of(scene)
    pub, priv = rng.sample(_SENT_MID, 2)
    return "\n".join([
        "【第一幕 · 公开信息】",
        pub,
        f"所有人都在等一个说法：{topic}。",
        "",
        f"【私人线索 · {a}】",
        priv,
        "",
        "【本幕任务】",
        "搜证：可搜 3 处。讨论：各自说明子时所在。",
        "",
        "【可问问题】",
        "- 门闩是谁插的？",
        "- 灯为什么灭了？",
    ])


def _prose_for_medium(
    payload: dict[str, Any], scene: dict[str, Any], rng: random.Random
) -> str:
    """按媒介分派。未知/缺失一律退化为小说散文（与 `craft_for` 同一策略）。"""
    medium = str(payload.get("medium") or "novel")
    cast = _cast_of(payload, scene)
    if medium == "screenplay":
        return _screenplay_for(scene, rng, cast)
    if medium == "micro_drama":
        return _screenplay_for(scene, rng, cast, micro=True)
    if medium == "comic":
        return _comic_for(scene, rng, cast)
    if medium == "interactive_fiction":
        return _if_for(scene, rng)
    if medium == "visual_novel":
        return _vn_for(scene, rng, cast)
    if medium == "murder_mystery":
        return _mm_for(scene, rng, cast)
    return _prose_for(scene, rng)


# ---------------------------------------------------------------------------
# 各任务的确定性实现
# ---------------------------------------------------------------------------


def _gen_premise(payload: dict[str, Any]) -> dict[str, Any]:
    idea = payload.get("idea", "一个故事").strip()
    medium = payload.get("medium", "novel")
    arc = payload.get("arc_shape", ArcShape.MAN_IN_A_HOLE.value)

    core = idea.rstrip("。.!！")
    return {
        "logline": f"{core}——而他必须在失去一切之前，先承认自己一直错在哪。",
        "premise": f"越是紧抓不放，越会把想留住的人推远；{core}。",
        "controlling_idea": "真正的背叛不是被出卖，而是从未允许别人靠近。",
        "ending_anchor": "他把最要紧的东西交到对方手里，然后独自转身离开。",
        "theme_statement": "信任不是一种判断，而是一种交付。",
        "moral_argument": "一端是「独自承担才安全」，另一端是「交付才可能被接住」；"
                          "故事必须让两端都付出代价。",
        "required_turns": [
            "主角获得一个必须依赖他人的处境",
            "最信任的人被证明与追捕者有关",
            "主角主动放弃一次独自解决的机会",
            "交付与不交付的代价被同时呈现",
        ],
        "arc_shape": arc,
        "medium": medium,
    }


def _gen_structure(payload: dict[str, Any]) -> dict[str, Any]:
    rng = _rng(payload)
    # beat_list 是结构化节拍（给机器用），beats 是节拍说明文本（给提示词用）
    beats: list[dict[str, Any]] = payload.get("beat_list") or []
    n = int(payload.get("scene_count", 5))
    arc = _arc_of(payload)
    chars: list[str] = payload.get("character_ids") or ["protagonist", "counterpart"]
    # id -> 显示名：场景卡是要给人读的，必须用名字
    names: dict[str, str] = payload.get("character_names") or {}

    def nm(x: str) -> str:
        return names.get(x, x)

    values = payload.get("values") or ["信任", "代价", "真相"]
    outcomes = [
        SceneOutcome.NO_AND,
        SceneOutcome.YES_BUT,
        SceneOutcome.NO,
        SceneOutcome.YES_BUT,
        SceneOutcome.YES_BUT,
        SceneOutcome.YES,
    ]

    scenes: list[dict[str, Any]] = []
    charge = "+"
    for i in range(n):
        # 节拍对齐：场景 i 覆盖节拍表上按比例分摊的一段，
        # 取该段中点的节拍作为这一场的「主节拍」（与 template_coverage 同一语义）
        if beats:
            k = min(len(beats) - 1, int((i + 0.5) / max(1, n) * len(beats)))
            beat = beats[k]
        else:
            beat = {}
        value = values[i % len(values)]
        # 保证每个场景都发生价值翻转（McKee 硬约束）
        new_charge = "-" if charge == "+" else "+"
        outcome = outcomes[i % len(outcomes)]
        focalizer = chars[i % len(chars)]

        scenes.append(
            {
                "id": f"sc{i + 1}",
                "title": f"{beat.get('name', '场景')}·{value}",
                # 带内外景标记 —— 剧本的场景标题只有这一个来源。
                # 按 index 取而不是 rng.choice：结构层的结果必须是
                # 完全确定的（rng 流留给正文层用），否则离线基线不可复现。
                "location": _LOCATIONS[i % len(_LOCATIONS)],
                "time_label": _TIMES[i % len(_TIMES)],
                "beat_id": beat.get("id"),
                "focalizer": focalizer,
                "value": value,
                "value_charge_start": charge,
                "value_charge_end": new_charge,
                "goal": f"{nm(focalizer)}想要在这一场拿到{value}的确认",
                "conflict": f"{value}必须交换掉另一样东西",
                "turning_point": f"{value}的代价第一次被摆到台面上",
                "outcome": outcome.value,
                # 情感值沿**声明的弧线**塑形，而不是写死一条上升直线。
                # 原实现写死 -0.8 → +0.8，与 arc_shape 完全无关，于是
                # man_in_a_hole 的故事拿到一条单调上升的情感曲线，
                # 而 emotion_curve_match 会（正确地）认为它不合规 ——
                # 桩件自己不满足自己声明的东西，是桩件缺陷，不是创作缺陷。
                "emotion": round(arc_curve(arc, i / max(1, n - 1)), 2),
                "fabula_day": i,
                "state_delta": {
                    "entity_id": focalizer,
                    "attribute": f"knows_{value}",
                    "before": False,
                    "after": True,
                },
                "is_branch_point": i == n - 2,
                "is_paywall_gate": i == max(0, n // 2),
            }
        )
        charge = new_charge

    return {"scenes": scenes}


def _gen_characters(payload: dict[str, Any]) -> dict[str, Any]:
    """角色层。

    `wound` / `lie` 不是装饰字段：`lie_arc_closure` 与 `TensionSeeder` 都
    以它们为输入。桩件必须自己产出锚，不能指望 fixture 事后补 ——
    **锚是生成阶段的产物，派生品不能反过来充当锚。**
    lie 的措辞刻意包含一个后半程场景的 `value`（信任 / 代价 / 真相），
    于是「lie 在高潮被正面处理」在字面重叠上成立，基线才是真的干净，
    而不是靠放宽 `lie_arc_closure` 的判据。
    """
    return {
        "characters": [
            {
                "id": "protagonist",
                "name": "主角",
                "want": "查清那件事的真相",
                # need 与 lie 用**同一条约定**：措辞里含一个后半程场景的 value
                # （信任 / 代价 / 真相），于是「需求在高潮被兑现」在字面重叠上成立。
                # 理由见本函数 docstring —— 基线要真的干净，而不是靠放宽判据。
                # 同时必须与 want **零**二元组重叠，否则 desire_need_conflict 会报。
                "need": "学会不再独自扛住代价",
                "flaw": "偏执，宁可独自承担",
                "wound": "他曾把全部信任交给一个人，那个人在关键时刻没有出现",
                "lie": "只要我不再信任任何人，就不会再被抛下",
                "arc_from": "孤僻独行者",
                "arc_to": "愿意托付一次",
                "voice": "短句，少修饰，多用反问",
                "goals": [
                    {"id": "g1", "description": "找到真相"},
                    {"id": "g2", "description": "活着离开"},
                    {"id": "g3", "description": "不再信任任何人", "is_conscious": False},
                ],
            },
            {
                "id": "counterpart",
                "name": "同伴",
                "want": "完成自己被交付的任务",
                # 同上：含后半程 value（真相），且与自身 want 零二元组重叠。
                "need": "学会把真相说出来",
                "flaw": "用忠诚掩盖愧疚",
                "wound": "他曾在最需要开口的那一刻选择了沉默",
                "lie": "只要把代价一个人扛住，就不算背叛",
                "arc_from": "沉默的同行者",
                "arc_to": "坦白的罪人",
                "voice": "敬语，句式完整，情绪藏在礼节后",
                "goals": [
                    {"id": "g4", "description": "找到真相"},  # 与主角目标相撞
                    {"id": "g5", "description": "把话说完"},
                ],
            },
        ],
        "actants": [
            {"role": "subject", "entity_id": "protagonist"},
            {"role": "object", "entity_id": "the_truth"},
            {"role": "sender", "entity_id": "protagonist", "note": "亡者的遗愿"},
            {"role": "receiver", "entity_id": "protagonist"},
            {"role": "opponent", "entity_id": "pursuers"},
            {
                "role": "opponent",
                "entity_id": "counterpart",
                "note": "反转：同行者即追兵",
            },
            {"role": "helper", "entity_id": "counterpart"},
        ],
        "entities": [
            {"id": "the_truth", "name": "那件事的真相", "kind": "concept",
             "description": "主角追查的核心目标"},
            {"id": "pursuers", "name": "追捕者", "kind": "organization",
             "description": "代表旧秩序的压力来源"},
            {"id": "loc_main", "name": "主场景", "kind": "location",
             "description": "故事主要发生地"},
            # 结构层引用的地点必须真的登记 —— 否则 `entity_reference`
            # 在基线上要么永远跳过、要么永远误报，两种都是「没测到」。
            *[
                {"id": f"loc_{i + 1}", "name": place, "kind": "location",
                 "description": "结构层登记的场景地点"}
                for i, place in enumerate(_PLACES)
            ],
        ],
    }


def _declaration_for(scene: dict[str, Any]) -> dict[str, Any]:
    """按场景卡的 `state_deltas` 生成自申报 —— 桩件模拟「守规矩的模型」。

    **为什么桩件要自申报**：① CHANGES 协议的价值在于「声明 vs 正文」双通道比对。
    如果桩件不自申报，`declaration_consistency` 在基线上永远 SKIPPED，
    它的「没问题」就只是「没跑过」—— 这正是本项目反复踩的那个坑。

    这里让声明与场景卡**一致**，因此基线上该门禁应当零发现。
    反例 fixture 会故意篡改声明内容，制造「说一套写一套」。
    """
    deltas = scene.get("state_deltas") or []
    if not deltas:
        return {}
    return {
        "character_state": [
            {
                "entity": d.get("entity_id"),
                "attribute": d.get("attribute"),
                "before": d.get("before"),
                "after": d.get("after"),
            }
            for d in deltas
        ]
    }


def _render_declaration(decl: dict[str, Any]) -> str:
    """把声明渲染成**带标记的文本**，让解析器真的走一遍格式探测。

    刻意不直接返回 dict —— 那样就绕过了 `split()`，
    而 `split()` 才是这条链路上最容易出错的一环。
    """
    if not decl:
        return ""
    body = json.dumps(decl, ensure_ascii=False)
    return f"\n---CHANGES---\n{body}"


def _gen_prose(payload: dict[str, Any]) -> dict[str, Any]:
    rng = _rng(payload)
    scene = payload.get("scene", {})
    prose = (
        _prose_for_medium(payload, scene, rng)
        + _render_declaration(_declaration_for(scene))
    )
    return {"prose": prose}


def _gen_changes(payload: dict[str, Any]) -> dict[str, Any]:
    """补声明通道：给一段已有正文，申报它实际发生的变化。

    桩件用 `scene` 的 state_deltas 当答案（若调用方传了）；
    没传就返回空声明 —— **空声明是合法结果**（降级），不是错误。
    """
    scene = payload.get("scene", {})
    return {"changes": _declaration_for(scene)}


def _gen_revise(payload: dict[str, Any]) -> dict[str, Any]:
    """确定性修订：只做「去陈词滥调」与句长调整两类安全操作。"""
    prose = payload.get("prose", "")
    findings = payload.get("findings", "")

    replacements = {
        "空气仿佛凝固": "谁都没有动",
        "时间仿佛静止": "更漏声停了一下",
        "死一般的寂静": "屋里只剩呼吸声",
        "嘴角勾起一抹": "他笑了一下，",
        "不由自主地": "",
        "他感到无比疲惫": "他的手指在抖",
        "心中涌起一股暖流": "他忽然想说点什么",
    }
    out = prose
    for bad, good in replacements.items():
        if bad in findings or bad in out:
            out = out.replace(bad, good)
    return {"prose": out, "changed": out != prose}


def _gen_audience(payload: dict[str, Any]) -> dict[str, Any]:
    """确定性观众定性判断。

    注意分工：**数值留存曲线不在这里算**（那是 audience/simulator 的 hazard
    模型的职责，必须确定性、可回归）。这里只做一件事 —— 把结构信号翻译成
    观众会说的「人话」，并给出一个独立的第二意见 drop_at_scene。
    两者一致 → 可信；两者分歧 → 标记该场待人工复核。
    """
    signals = payload.get("signals", {})
    persona = payload.get("persona", {})
    sens = persona.get("sensitivity", {})

    twist = float(sens.get("twist_appetite", 0.5))
    payoff = float(sens.get("payoff_need", 0.5))
    pacing = float(sens.get("pacing_standard", 0.5))
    prose_std = float(sens.get("prose_standard", 0.5))
    curiosity = float(sens.get("curiosity", 0.5))

    flip = float(signals.get("value_flip_ratio", 0.5))
    hook = float(signals.get("hook_ratio", 0.5))
    outv = float(signals.get("outcome_variety", 0.5))
    openr = float(signals.get("open_enigma_ratio", 0.5))
    mid_open = float(signals.get("mid_open_ratio", 0.5))
    slop = float(signals.get("slop_score", 70.0))
    density = float(signals.get("avg_info_density", 1.0))
    n = int(signals.get("scene_count", 5))
    capacity = float(sens.get("max_info_density", 3))

    # 供给与需求的缺口：正 = 想要但没给够
    twist_gap = max(0.0, twist - flip)
    hook_gap = max(0.0, pacing - hook)
    prose_gap = max(0.0, (prose_std * 100.0 - slop) / 100.0)
    # 悬念张力：看**中段**是否持续悬着。
    # 不用全局未解比例 —— 收干净的结局是完成度，不是缺陷。
    tension = mid_open
    overload = max(0.0, density - capacity)

    clamp = lambda x: int(max(0, min(100, x)))  # noqa: E731

    engagement = clamp(45 + 60 * flip * (0.4 + twist) + 25 * tension - 20 * twist_gap)
    predictability = clamp(35 + 70 * prose_gap + 35 * (1 - outv) - 25 * tension)
    payoff_density = clamp(40 + 50 * hook + 30 * (1 - openr) * payoff)
    pacing_score = clamp(60 + 40 * hook - 45 * hook_gap - 20 * overload)
    prose_pull = clamp(30 + 70 * (slop / 100.0) - 45 * prose_std)

    drop_at = None
    reason = ""
    if predictability > 70:
        drop_at = max(1, int(n * 0.4))
        reason = "看了几场就知道后面怎么走，套路感太强"
    elif pacing_score < 45:
        drop_at = max(1, int(n * 0.5))
        reason = "有几场几乎什么都没推进，等不下去了"
    elif prose_pull < 40:
        drop_at = 2
        reason = "文字读起来不像人写的，出戏"
    elif engagement < 45:
        drop_at = max(1, int(n * 0.6))
        reason = "一直没有被抓住，情绪上不去"
    elif curiosity > 0.7 and openr > 0.75:
        drop_at = max(1, int(n * 0.8))
        reason = "埋了一堆线头一个都不收，感觉作者自己也没想好"

    # 抱怨必须因人格而异 —— 同一部作品让四个人不满意的地方本来就不同。
    # 按「这个人最在意什么」排序，取第一个没被满足的。
    complaints: list[tuple[float, str]] = [
        (pacing * (1.0 - hook), "有几场几乎什么都没推进，等不下去"),
        (twist * (1.0 - flip), "说好的反转一直没来，剧情太顺了"),
        (pacing * min(1.0, overload), "信息塞得太满，来不及消化"),
        (prose_std * (1.0 - slop / 100.0), "文笔撑不住，读两页就出戏"),
        # 只有「悬得太多」才算问题；收干净不算
        (curiosity * max(0.0, openr - 0.6) / 0.4, "埋了一堆线头，收得太少"),
    ]
    best = max(complaints, key=lambda kv: kv[0])
    if best[0] < 0.08:
        # 硬指标上挑不出毛病时，每个观众的「余下的那点不满」依然不同 ——
        # 这本身就是有用的信息：同一个没有硬伤的稿子，
        # 挑剔节奏的人说「可以再压」，挑剔文笔的人说「可以再收」。
        residual = {
            "pacing_standard": "结构没问题，就是有几场还能再压一压",
            "twist_appetite": "结构很稳，但缺一个真正意料之外的转弯",
            "prose_standard": "整体没问题，语言还可以再往回收一点",
            "curiosity": "线都收住了，就是中段悬念还能再吊一会儿",
            "payoff_need": "该给的都给了，只是最后一下可以再重一点",
        }
        keys = {
            "pacing_standard": pacing,
            "twist_appetite": twist,
            "prose_standard": prose_std,
            "curiosity": curiosity,
            "payoff_need": payoff,
        }
        complaint = residual[max(keys, key=lambda k: keys[k])]
    else:
        complaint = best[1]

    return {
        "engagement": engagement,
        "predictability": predictability,
        "payoff_density": payoff_density,
        "pacing": pacing_score,
        "prose_pull": prose_pull,
        "drop_at_scene": drop_at,
        "drop_reason": reason,
        "would_recommend": drop_at is None and engagement > 55,
        "highlight": (
            "价值翻转最密集的那一场"
            if flip >= 0.8
            else "收线最集中的那一场"
        ),
        "complaint": complaint,
    }


# ---------------------------------------------------------------------------


def _gen_next_scene(payload: dict[str, Any]) -> dict[str, Any]:
    """自动驾驶模式的「下一场」—— 一次只产出**一场**。

    为什么桩件也要有：铁律 6 要求无 key 也能端到端跑通。自动驾驶是新的主路径，
    它若只能在真模型下跑，就又变成一条「离线不可验证」的分支 ——
    而离线不可验证正是历史上假门禁的温床（桩件不渲染提示词 → verify 第 3 节假绿）。

    与 `_gen_structure` 的区别：那个一次产出全篇，这个消费「已经写了什么」
    与「还欠什么」。若桩件的下一场与前一场无关，自动驾驶就会原地打转 ——
    而原地打转正是 `drift_guard` 要抓的 padding。桩件自己不能示范这个缺陷。
    """
    index = int(payload.get("index", 1))
    i = max(0, index - 1)
    target = max(1, int(payload.get("target", 6)))
    chars: list[str] = payload.get("character_ids") or ["protagonist"]
    names: dict[str, str] = payload.get("character_names") or {}
    values = payload.get("values") or ["信任", "代价", "真相"]

    def nm(x: str) -> str:
        return names.get(x, x)

    value = values[i % len(values)]
    focalizer = chars[i % len(chars)]
    opens = payload.get("open_commitments") or []
    anchor = str(payload.get("ending_anchor") or "")

    # 最后一场兑现结局锚点，其余推进未兑现的承诺 ——
    # 两者都不写，产出就是「一场接一场的无关事件」，即铁律 2 的失败模式。
    if i >= target - 1 and anchor:
        turning = f"结局锚点兑现：{anchor[:24]}"
    elif opens:
        # 按场次**轮换**承诺，而不是每场都重复第一条 ——
        # 桩件若原地打转，drift_guard 会（正确地）判为 padding 并暂停整条流水线。
        # 桩件自己不能示范它该被抓的那个缺陷。
        turning = f"承诺推进：{str(opens[i % len(opens)])[:24]}"
    else:
        turning = f"{value}的代价第{index}次被摆到台面上"

    outcome = "yes" if i >= target - 1 else ["no_and", "yes_but", "no"][i % 3]

    return {
        "id": f"sc{index}",
        "title": f"第{index}场·{value}",
        # 按 index 取而不是 rng.choice：结构层结果必须完全确定
        # （rng 流留给正文层用），否则离线基线不可复现。
        "location": _LOCATIONS[i % len(_LOCATIONS)],
        "time_label": _TIMES[i % len(_TIMES)],
        "focalizer": focalizer,
        "value": value,
        "value_charge_start": "+" if i % 2 == 0 else "-",
        "value_charge_end": "-" if i % 2 == 0 else "+",
        "goal": f"{nm(focalizer)}要在这一场推进{value}",
        "conflict": f"{value}必须交换掉另一样东西",
        "turning_point": turning,
        "outcome": outcome,
        "emotion": round(-0.6 + 1.2 * (i / max(1, target - 1)), 2),
        "fabula_day": i,
        # 数组：一场常有多人同时改变。只申报一个会让其余变化变成
        # 「正文改了、卡片没写」—— 正是 declaration_consistency 要抓的漏报。
        "state_deltas": [
            {
                "entity_id": focalizer,
                "attribute": f"knows_{value}",
                "before": False,
                "after": True,
            }
        ],
    }


class MockGenerator:
    """确定性参考生成器。"""

    model_id = "mock-deterministic-v1"

    _DISPATCH = {
        "premise": _gen_premise,
        "structure": _gen_structure,
        "characters": _gen_characters,
        "prose": _gen_prose,
        "changes": _gen_changes,
        "revise": _gen_revise,
        "audience": _gen_audience,
        "next_scene": _gen_next_scene,
    }

    def __init__(self, ledger=None) -> None:
        self.ledger = ledger

    def generate(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        fn = self._DISPATCH.get(task)
        if fn is None:
            raise KeyError(
                f"MockGenerator 不支持任务 {task!r}；"
                f"支持：{sorted(self._DISPATCH)}"
            )
        out = fn(payload)
        if self.ledger:
            # 粗估 token：CJK 约 1 token / 1.5 字符
            pt = max(1, len(repr(payload)) // 3)
            ct = max(1, len(repr(out)) // 3)
            self.ledger.record(task, pt, ct)
        return out
