"""提示词注册表。

每条提示词都是版本化的。关键约定：

1. **输出必须是结构化 JSON** —— 不是自由文本。这样才可校验、可缓存、可回放，
   也才能落进 IR。自由文本进不了 IR，这是本系统与「AI 写作工具」的根本区别。
2. **方法论不进提示词前缀**，而是以「结构模板的节拍定义 + 校验器判据」注入。
   把 Save the Cat 的 15 个节拍写成一段 prompt 让模型顺着填，是常见的死法。
3. 提示词版本号写进 Provenance，便于定位退化与做 A/B。
"""

from __future__ import annotations

from .base import REGISTRY, Prompt

# ---------------------------------------------------------------------------
# 1. 内核层：想法 -> L3 作者承诺
# ---------------------------------------------------------------------------

PREMISE = REGISTRY.register(
    Prompt(
        id="premise",
        version="premise.v2",
        system=(
            "你是故事内核设计者。你的任务是**倒着设计**：先确定结局锚点与关键转折，"
            "再反推主题。绝大多数结构崩坏都源于开写时结局还没定。\n"
            "原则：\n"
            "- 前提（premise）必须是一句因果断言，不是主题词。"
            "反例：「关于信任」。正例：「偏执地独自承担一切，会把最该信任的人推成敌人。」\n"
            "- 控制理念（controlling_idea）回答「这个故事在证明什么」。\n"
            "- 结局锚点必须具体到动作或画面，不是情绪描述。\n"
            "- 承诺层要包含至少一条 theme 和一条 ending，它们是硬约束。\n"
            "只输出 JSON，不要任何解释文字。"
        ),
        template=(
            "想法：{idea}\n"
            "媒介：{medium}\n"
            "目标长度：{target_length}\n"
            "情感弧线形状：{arc_shape}\n"
            "结构模板：{template_name}（节拍：{beat_names}）\n\n"
            "输出 JSON，字段：\n"
            "  logline       一句话故事（谁 + 想要什么 + 什么阻碍）\n"
            "  premise       因果断言式前提\n"
            "  controlling_idea  控制理念\n"
            "  ending_anchor 结局锚点（具体动作/画面）\n"
            "  theme_statement   主题陈述\n"
            "  moral_argument    道德论证（两难的两端）\n"
            "  required_turns    数组，必须发生的关键转折（3-5 条）"
        ),
        output_schema={
            "type": "object",
            "required": [
                "logline", "premise", "controlling_idea",
                "ending_anchor", "theme_statement", "moral_argument",
            ],
        },
    )
)

# ---------------------------------------------------------------------------
# 2. 结构层：承诺 -> 场景骨架
# ---------------------------------------------------------------------------

STRUCTURE = REGISTRY.register(
    Prompt(
        id="structure",
        version="structure.v4",
        system=(
            "你是结构设计师。给你一个节拍模板和作者承诺，产出场景骨架。\n"
            "硬性要求：\n"
            "- 每个场景必须有**价值转折**（value_charge_start != value_charge_end）。"
            "这是 McKee 的核心断言：每个场景都是一次价值状态的翻转。\n"
            "- 每个场景必须有**至少一个状态增量**（state_deltas），零增量场景不成立。\n"
            "- 场景结果只能是 yes / yes_but / no / no_and 四者之一。"
            "全部用 yes 的故事没有张力。\n"
            "- 至少一个场景使用 no_and（未达成且更糟），用来抬高赌注。\n"
            "- 并发价值线不超过 3 条（减头绪）。\n"
            "- **emotion 必须沿声明的情感弧线塑形**（见下方「情感弧线」）。"
            "这不是装饰：弧线的转折点位置会被校验，单调曲线通过不了谷型/峰型弧线。\n"
            "只输出 JSON。"
        ),
        template=(
            "结构模板：{template_name}\n"
            "节拍定义：\n{beats}\n\n"
            "前提：{premise}\n"
            "结局锚点：{ending_anchor}\n"
            "必须发生的转折：{required_turns}\n"
            "角色：{characters}\n"
            "场景数量：{scene_count}\n"
            "情感弧线：{arc_shape} —— {arc_description}\n"
            "  （按场景在故事中的相对进度，把 emotion 值放在这条形状上；\n"
            "   进度 0% 是第一场，100% 是最后一场）\n\n"
            "输出 JSON 数组，每个元素字段：\n"
            "  id, title, location, beat_id, focalizer, value,\n"
            "  value_charge_start, value_charge_end,\n"
            "  goal, conflict, turning_point, outcome, emotion(-1..1), fabula_day,\n"
            "  time_label, state_delta (object: entity_id, attribute, before, after)\n"
            "按话语顺序排列。\n\n"
            "location 必须写**带内外景标记的地点**，如「内景·书房」「外景·码头」。\n"
            "  剧本渲染器要靠它生成场景标题 —— 场景标题没有第二处来源。\n"
            "  只写地点名而不写内外景，标题会被标成「内/外景」：\n"
            "  那是「未定」的显式标记，比替作者猜一个要诚实。\n\n"
            "time_label 写这一场的时间标记，如「夜」「三日后」「闪回」。\n"
            "  没有特别标记就留空字符串 —— 剧本渲染器不会替你猜钟点，\n"
            "  留空的场景标题会省略时间，而不是给整部戏盖上一层假的夜色。"
        ),
    )
)

# ---------------------------------------------------------------------------
# 3. 角色层
# ---------------------------------------------------------------------------

CHARACTERS = REGISTRY.register(
    Prompt(
        id="characters",
        version="characters.v3",
        system=(
            "你是角色设计师。核心要求：\n"
            "- want（外部欲望）与 need（内在需求）必须不同 —— 这个落差就是人物弧光的引擎。\n"
            "- **wound（旧伤）与 lie（角色信以为真的错误命题）必须具体到可验证**。\n"
            "  「傲慢」不可验证；「只要我不在乎就不会再受伤」可以 —— 后者才能在\n"
            "  高潮被正面处理或正面放弃。lie 要写成一句角色会对自己说的话。\n"
            "- 每个角色必须有独立的**目标图**。冲突 = 两条目标链相撞，"
            "而不是「坏人挡路」。\n"
            "- 至少两个角色的目标要真正相撞（同一个人/物）。\n"
            "- 行动元（actant）是「角色位」而非「人物」。"
            "同一个人物占据 subject 与 opponent 是反转结构，如果你这样设计，"
            "必须在备注里说明。\n"
            "- 复调原则：任何角色不得只做作者论点的传声筒。\n"
            "只输出 JSON。"
        ),
        template=(
            "前提：{premise}\n"
            "控制理念：{controlling_idea}\n"
            "道德论证：{moral_argument}\n"
            "已有场景：{scenes}\n\n"
            "输出 JSON，字段：\n"
            "  characters 数组，每项：id, name, want, need, flaw,\n"
            "                       wound（旧伤：什么经历造成了他的防御）,\n"
            "                       lie（他因此信以为真的错误命题，写成一句自我说服的话）,\n"
            "                       arc_from, arc_to,\n"
            "                       voice（语言风格）, goals（数组，含 description）\n"
            "  actants 数组，每项：role(subject/object/sender/receiver/helper/opponent),"
            " entity_id, note\n"
            "  entities 数组（地点/物品/组织），每项：id, name, kind, description"
        ),
    )
)

# ---------------------------------------------------------------------------
# 4. 场景卡 -> 正文
# ---------------------------------------------------------------------------

PROSE = REGISTRY.register(
    Prompt(
        id="prose",
        version="prose.v5",
        system=(
            "你是写作者。严格按【写作形态】一节指定的媒介规格写一个场景的正文。\n"
            "**媒介规格优先于你的默认习惯** —— 不管被要求写什么媒介，"
            "默认写成小说散文，是这条链路上最常见也最致命的失败："
            "下游渲染器解析的是该媒介的格式（对白行 / 画格 / 选项），"
            "散文形态会让整份产物变成「排版成剧本的小说」。\n"
            "必须遵守的硬约束：\n"
            "- **视角纪律**：严格限定在 focalizer 的感知范围内。"
            "他不能知道他不该知道的事。\n"
            "- **呈现而非告知**：不要写「他感到无比愤怒」，写让读者感到愤怒的东西。\n"
            "- **节奏**：句长必须有起伏。连续等长的句子是最典型的 AI 味。\n"
            "- 禁止：否定式煽情（「这不仅是X，而是Y」）、虚假范围（「从X到Y」）、"
            "最高级堆叠、总结式升华收尾、陈词滥调（「空气仿佛凝固」）。\n"
            "- 比喻密度不超过每 3 句 1 个。\n"
            "- **自申报**：正文写完后，另起一行输出 `---CHANGES---`，"
            "然后输出一个 JSON 对象，声明这段正文里**真的发生了**的变化。\n"
            "只输出正文与声明，不要标题、不要解释、不要 markdown 代码围栏。"
        ),
        template=(
            "{medium_craft}\n\n"
            "【场景】{title}\n"
            "视角：{focalizer}（聚焦模式：{focalization}）\n"
            "场景目标：{goal}\n"
            "冲突：{conflict}\n"
            "转折：{turning_point}\n"
            "价值：{value} {value_charge_start} → {value_charge_end}\n"
            "结果：{outcome}\n"
            "情绪强度：{emotion}\n"
            "出场：{entities}\n\n"
            "【相关设定】（只使用这些，不要发明新设定）\n{lore}\n\n"
            "【角色当前状态】\n{character_state}\n\n"
            "【上一场结尾】\n{prev_tail}\n\n"
            "【本场场景卡声称的变化】\n{state_deltas}\n\n"
            "长度：{length_hint}直接写正文。\n\n"
            "正文之后另起一行写 `---CHANGES---`，再写一个 JSON 对象，"
            "键取自：character_state / relationship / event / foreshadowing / "
            "location_state / item_transfer / secret / time_progression / "
            "belief_change / new_character。\n"
            "**只声明正文里真的写了的变化，宁可少报也不要虚报** —— "
            "声明与正文矛盾时以正文为准，虚报会被门禁抓住。"
        ),
    )
)

# ---------------------------------------------------------------------------
# 4b. 补声明（① CHANGES 自申报协议）
# ---------------------------------------------------------------------------

CHANGES = REGISTRY.register(
    Prompt(
        id="changes",
        version="changes.v1",
        system=(
            "你在做**结构化变更申报**，不是写作，也不是评论。\n"
            "给你一段已经写好的正文，你的唯一任务是：如实列出这段正文里"
            "**实际发生**的变化。\n"
            "硬约束：\n"
            "- 只申报正文里**写出来了**的变化。正文没写的，一律不要申报。\n"
            "- 宁可少报，也不要虚报 —— 虚报会被下游门禁抓住，"
            "而漏报只是让某个检查跳过。\n"
            "- 只输出一个 JSON 对象，不要解释、不要 markdown 围栏。"
        ),
        template=(
            "【正文】\n{prose}\n\n"
            "【已知实体】（主体/客体只能用这些 id 或名字）\n{entities}\n\n"
            "输出一个 JSON 对象，键取自：character_state / relationship / event / "
            "foreshadowing / location_state / item_transfer / secret / "
            "time_progression / belief_change / new_character。\n"
            "没有变化的类别可以省略。"
        ),
    )
)

# ---------------------------------------------------------------------------
# 5. 修订
# ---------------------------------------------------------------------------

REVISE = REGISTRY.register(
    Prompt(
        id="revise",
        version="revise.v2",
        system=(
            "你是修订者。给你一段正文和具体的体检结论，只修被指出的问题。\n"
            "不要重写全文，不要改动未被指出的部分。只输出修订后的正文。"
        ),
        template=(
            "【原文】\n{prose}\n\n"
            "【需要修的问题】\n{findings}\n\n"
            "直接输出修订后的正文。"
        ),
    )
)

# ---------------------------------------------------------------------------
# 6. 观众模拟
# ---------------------------------------------------------------------------

AUDIENCE = REGISTRY.register(
    Prompt(
        id="audience",
        version="audience.v3",
        system=(
            "你现在**不是**编辑，也不是作者。你是观众。\n"
            "你的任务不是评价「写得好不好」，而是预测「我会不会看下去」。\n"
            "请以给定人格的偏好作答，允许你给出不专业的、情绪化的判断。\n"
            "诚实比礼貌重要：如果你会弃剧，直接说在第几场弃、为什么。\n"
            "只输出 JSON。"
        ),
        template=(
            # 这里的字段名必须与 `AudienceSimulator._qualitative` 的 payload 对齐。
            # 之前写的是 {persona}/{genre}/{logline}/{scenes}，而调用方只给了
            # signals 与 persona —— 于是渲染每次都走降级分支，模型拿到一份
            # 没填的模板加 JSON 附录。**桩件看不见这件事**（它不渲染提示词），
            # 所以它在 Mock 下一直是绿的，在真模型下一直接收坏提示词。
            "【你的人格】\n{persona_brief}\n\n"
            "【作品信息】\n媒介：{medium}\nLogline：{logline}\n\n"
            "【逐场内容】\n{scenes}\n\n"
            "【结构性信号】（参考即可，不要在回答里复述）\n{signals_text}\n\n"
            "输出 JSON，字段：\n"
            "  engagement     0-100，情感投入度\n"
            "  predictability 0-100，可预测性（越高越套路）\n"
            "  payoff_density 0-100，爽点/回报密度\n"
            "  pacing         0-100，节奏满意度\n"
            "  character_pull 0-100，角色代入感\n"
            "  drop_at_scene  如果会弃，弃在第几场（null 表示看完）\n"
            "  drop_reason    弃剧原因\n"
            "  would_recommend true/false\n"
            "  highlight      最打动你的一场\n"
            "  complaint      最想吐槽的一点"
        ),
    )
)


def describe_beats(template) -> str:
    """把结构模板的节拍定义渲染成提示词片段。

    注意：这里传的是「节拍定义」，不是「按这 15 步填空」。区别在于
    模型仍需自己决定因果如何驱动，节拍只是位置约束。
    """
    lines = []
    for b in template.beats:
        lo, hi = b.position
        lines.append(
            f"  - {b.id}（{b.name}）位置 {lo:.0%}-{hi:.0%}：{b.purpose}"
        )
    return "\n".join(lines)


NEXT_SCENE = REGISTRY.register(
    Prompt(
        id="next_scene",
        version="next_scene.v1",
        system=(
            "你是结构设计师，正在**一场一场地**推进一个已经在跑的故事。\n"
            "你的任务不是重排全篇，而是产出**紧接着的下一场**。\n"
            "硬性要求：\n"
            "- 这一场必须有**价值转折**（value_charge_start != value_charge_end）。"
            "McKee：每个场景都是一次价值状态的翻转，平铺直叙的一场不成立。\n"
            "- 这一场必须有**至少一个状态增量**（state_deltas）。零增量 = 什么都没发生，"
            "而自动驾驶最容易犯的错恰恰是「写了很多，什么都没变」。\n"
            "- outcome 只能是 yes / yes_but / no / no_and。\n"
            "- **必须推进还没兑现的承诺**，或**逼近结局锚点**。"
            "若这一场与它们无关，你就是在注水 —— 注水会被漂移检测抓住并暂停整条流水线。\n"
            "- 不要重复上一场刚用过的转折句式。\n"
            "只输出一个 JSON 对象（不是数组）。"
        ),
        template=(
            "前提：{premise}\n"
            "控制理念：{controlling_idea}\n"
            "结局锚点：{ending_anchor}\n\n"
            "已经写了 {done_count} 场：\n{prior}\n\n"
            "尚未兑现的承诺：\n{open_commitments}\n\n"
            "角色：{characters}\n"
            "这是第 {index} 场（全篇目标 {target} 场）。\n\n"
            "输出一个 JSON 对象，字段：\n"
            "  id, title, location, focalizer, value,\n"
            "  value_charge_start, value_charge_end,\n"
            "  goal, conflict, turning_point, outcome, emotion(-1..1), fabula_day,\n"
            "  time_label, state_deltas (数组，每项: entity_id, attribute, before, after)\n\n"
            "location 必须写**带内外景标记的地点**，如「内景·书房」「外景·码头」。\n"
            "  剧本渲染器要靠它生成场景标题 —— 场景标题没有第二处来源。\n"
            "time_label 没有特别标记就留空字符串 —— 渲染器不会替你猜钟点。\n"
            "state_deltas 用**数组**：一场戏里常有多个人或物同时改变，\n"
            "  只申报一个会让其余的变化变成「正文改了、卡片没写」。"
        ),
    )
)


__all__ = [
    "REGISTRY",
    "PREMISE",
    "STRUCTURE",
    "CHARACTERS",
    "PROSE",
    "CHANGES",
    "REVISE",
    "AUDIENCE",
    "NEXT_SCENE",
    "describe_beats",
]
