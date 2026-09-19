"""① CHANGES 自申报协议的解析器。

**它解决什么问题**：Keel 的 `StructureEngine` 在**场景卡层**产出 `state_deltas`，
然后 `Scripter` 据此写正文 —— 但**没有任何机制检查正文是否真的做了场景卡说的那件事**。
这是架构里最大的一处「说一套写一套」漏洞：结构体检 92 分，正文却可能一场都没兑现。

本模块负责把模型附在正文末尾的结构化声明切出来并解析成 dict。
真正的比对在校验器 `declaration_consistency` 里。

── 三条设计原则（出处：Æsirian `core/changes_protocol.py` 的工程模式）──

1. **不要求模型严格遵守格式 —— 容忍并修复偏差。**
   模型会用中文引号、单引号、中文冒号、尾逗号。四种标记格式都要认。
   要求模型「输出严格 JSON」是提示词层面的乞求，不是工程保证。

2. **声明越详细，门禁越准确 —— 于是模型有动力写细。**
   这是激励机制设计，不是格式洁癖：声明是 AI 的**自证**，
   自证越细，下游双通道比对越准。

3. **声明只是提示通道，真值通道是 IR / 文本提取。**
   声明与正文矛盾时**以 IR 为准** —— 这条是整套协议的安全阀，
   防止模型虚构一份「我改了什么」的漂亮声明来骗过门禁。

── 降级策略 ──

**解析失败不是错误，是降级。** 拿不到声明 → 校验器 SKIPPED，流水线继续。
理由与「永不静默改写」同源：出问题可以，别不吭声 —— 但也不要让一个
可选的自我申报把整条流水线打挂。降级会记进 `Declaration.note`。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

#: 10 类变化。来自 Æsirian 的声明协议分类（**分类名可借鉴，词表/阈值不可**）。
CHANGE_CLASSES: tuple[str, ...] = (
    "character_state",
    "relationship",
    "event",
    "foreshadowing",
    "location_state",
    "item_transfer",
    "secret",
    "time_progression",
    "belief_change",
    "new_character",
)

#: 四种标记格式，按特异性从强到弱探测。
_MARKER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("xml", re.compile(r"<changes>\s*(.*?)\s*</changes>", re.DOTALL | re.IGNORECASE)),
    ("dash", re.compile(r"-{2,}\s*CHANGES\s*-{2,}\s*(.*)", re.DOTALL | re.IGNORECASE)),
    ("header", re.compile(r"#{1,6}\s*CHANGES\s*(.*)", re.DOTALL | re.IGNORECASE)),
    ("fence", re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)),
)

#: 中文标点 → JSON 合法标点。
_PUNCT_MAP: tuple[tuple[str, str], ...] = (
    ("“", '"'),
    ("”", '"'),
    ("「", '"'),
    ("」", '"'),
    ("『", '"'),
    ("』", '"'),
    ("：", ":"),
    ("，", ","),
)

_TRAILING_COMMA = re.compile(r",\s*([}\]])")


@dataclass
class Declaration:
    """一次解析的结果。

    `prose` 永远是**剥掉声明之后**的正文 —— 声明绝不能漏进正文，
    否则它会出现在小说/剧本里。这是「架构泄漏到产品」的又一处防线。
    """

    prose: str
    changes: dict[str, Any] = field(default_factory=dict)
    raw: str | None = None
    note: str | None = None

    @property
    def ok(self) -> bool:
        """是否拿到了可用声明。False 表示降级（校验器应 SKIPPED）。"""
        return bool(self.changes)


def repair_json(text: str) -> str:
    """把「模型写的近似 JSON」修成「json.loads 能吃的东西」。

    只做**保守**替换：中文标点、单引号、尾逗号。不做任何猜测性补全 ——
    猜错会产出**看起来解析成功**的错误数据，比解析失败更危险。
    """
    s = text.strip()
    for src, dst in _PUNCT_MAP:
        s = s.replace(src, dst)
    # 单引号 → 双引号：仅当整段里没有双引号时（否则会把 ' 当成字符串内容）
    if '"' not in s and "'" in s:
        s = s.replace("'", '"')
    s = _TRAILING_COMMA.sub(r"\1", s)
    return s


def _last_balanced_object(text: str) -> str | None:
    """从文本里取出**最后一个**配平的 `{...}`。

    用花括号计数而不是正则 —— 正则匹配不了嵌套对象，
    而 `changes` 里的 `character_state` 天然是嵌套的。
    同时要跳过字符串字面量里的花括号，否则 `{"note": "他写了 { 符号"}` 会算错。
    """
    end = text.rfind("}")
    if end == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(end, -1, -1):
        ch = text[i]
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "}":
            depth += 1
        elif ch == "{":
            depth -= 1
            if depth == 0:
                return text[i : end + 1]
    return None


def _try_load(raw: str) -> dict[str, Any] | None:
    """尝试解析成 dict。失败返回 None（不抛）。"""
    for candidate in (raw.strip(), repair_json(raw)):
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _normalise(obj: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """规整成 10 类结构。返回 (规整后的 dict, 异常说明列表)。

    未知键**保留但记账** —— 静默丢弃会让「模型发明了一类变化」这件事
    永远不被发现，而那正是我们想知道的。
    """
    notes: list[str] = []
    unknown = sorted(k for k in obj if k not in CHANGE_CLASSES)
    if unknown:
        notes.append(f"未知声明类别（已保留）：{unknown}")
    return obj, notes


def split(text: str) -> Declaration:
    """把「正文 + 声明」切成两者。**永不抛异常。**

    探测顺序：XML 块 → `---CHANGES---` → `### CHANGES` → 围栏 JSON → 尾部裸 JSON。
    前四种命中后，标记之前的全部内容就是正文；尾部裸 JSON 则以其起始 `{` 为界。
    """
    if not text or not text.strip():
        return Declaration(prose="", note="空文本")

    for kind, pat in _MARKER_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        obj = _try_load(m.group(1))
        if obj is None:
            # 找到标记但解析不了 —— 保留正文，记账降级
            return Declaration(
                prose=text[: m.start()].rstrip(),
                raw=m.group(1).strip(),
                note=f"找到 {kind} 标记但 JSON 解析失败（已降级）",
            )
        changes, notes = _normalise(obj)
        note = f"格式={kind}" + ("；" + "；".join(notes) if notes else "")
        return Declaration(
            prose=text[: m.start()].rstrip(),
            changes=changes,
            raw=m.group(1).strip(),
            note=note,
        )

    # 兜底：尾部裸 JSON。只有当它确实在**结尾附近**才算，
    # 否则正文里的正常花括号会被误当成声明。
    tail = text.rstrip()
    if tail.endswith("}"):
        candidate = _last_balanced_object(tail)
        if candidate:
            start = tail.rindex(candidate)
            # 声明块之前应当有换行分隔，避免把正文句子里的 {} 吃掉
            if start == 0 or tail[start - 1] in "\n\r ":
                obj = _try_load(candidate)
                if obj is not None and any(k in CHANGE_CLASSES for k in obj):
                    changes, notes = _normalise(obj)
                    return Declaration(
                        prose=tail[:start].rstrip(),
                        changes=changes,
                        raw=candidate,
                        note="格式=裸 JSON" + ("；" + "；".join(notes) if notes else ""),
                    )

    return Declaration(prose=text.rstrip(), note="未找到声明（降级，校验器将 SKIPPED）")


__all__ = ["CHANGE_CLASSES", "Declaration", "repair_json", "split"]
