"""Keel 插件契约（Plugin API）—— 薄客户端**唯一**被允许依赖的接口。

## 为什么需要这一层

P5 的插件通道（VS Code / Cursor / Obsidian）只做**薄客户端**，逻辑全部留在
本地引擎。这条纪律的反面是：插件**不能**去解析 CLI 的人类可读输出。

    人类可读输出是写给眼睛的，它随时可以被改得更好读 —— 这是它的本职。
    一旦插件依赖它，每次改文案都会**静默**弄坏插件，
    而且没有任何测试会红（因为插件不在 Python 测试里）。

所以插件需要一个**稳定的、机器可读的**接口。本模块就是那个接口：

    python -m keel api handshake
    python -m keel api audit     --ir out/ir.json
    python -m keel api proposals --ir out/ir.json
    python -m keel api decide    --ir out/ir.json --all --accept
    python -m keel api render    --ir out/ir.json --format fountain

## 三条硬约束

1. **本模块不实现任何叙事逻辑。** 每个方法都只是把**已有函数**的结果序列化。
   在这里写判断（「这个分数算不算好」「这条提案该不该采纳」）就是把逻辑
   搬进了插件层 —— 那正是「插件只做薄客户端」要防的事。
   判据：删掉本模块，引擎应当一切照旧。

2. **失败必须是结构化数据，不能是 traceback。**
   插件解析不了 traceback，也解析不了中文文案。见 `ApiError` 与 `call()`。

3. **`API_VERSION` 是契约版本，不是产品版本。** 只有在**破坏性**改动
   （删方法、改参数名、改字段语义）时才 +1；**加**方法不必 +1。
   插件在 `handshake` 里比对它，对不上就**明说版本不匹配**，而不是猜着用 ——
   猜出来的兼容性就是下一处静默漂移。

## 内部错误与「故事有问题」的区别（铁律 21 的延伸）

`kind == "internal"` 表示**Keel 自己出错了**（bug），不是「这份稿子有缺陷」。
两者必须分开，理由与 `Report.crashes` 完全相同：

    一个被吞掉的崩溃，读起来和一条普通结果一模一样。

所以内部错误**不产出 `data`**、只产出 `error`，并且 CLI 会以**非零退出码**
返回（见 `keel/cli.py::cmd_api`）。插件看到 `ok=false` 必须把它当**工具故障**
报给用户，而不是当成一条创作结论。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .clock import wall_iso
from .ir.enums import Medium
from .ir.loading import IRLoadError, load_ir
from .ir.models import NarrativeIR
from .ir.proposal import Diff
from .ir.templates import BeatTemplate, list_templates
from .llm import build_generator
from .pipeline import KeelPipeline
from .render import (
    render_fountain,
    render_html,
    render_ink,
    render_renpy,
    render_storyboard,
    render_text,
)
from .render.text import render_outline
from .validators import Finding, registry_stats, run_all

#: 契约版本。**破坏性**改动才 +1（删方法 / 改参数名 / 改字段语义）。
#: 加方法不加版本 —— 插件按名字调用，多出来的方法它用不到。
API_VERSION = "1"

#: IR 路径参数名。多处引用，抽出来避免「有的方法叫 ir、有的叫 path」。
PARAM_IR = "ir"


class ApiError(Exception):
    """插件可读的失败。

    `kind` 是**给程序分支**用的，`message` 是**给人看**的原文。
    不要只留一个字符串消息然后让调用方 `if "缺少" in msg` —— 那是把判据
    建在文案上，文案一改就静默走错分支（同 `IRLoadError` 的理由）。
    """

    #: 方法名不存在。通常是插件与引擎版本不匹配。
    BAD_METHOD = "bad_method"
    #: 缺少必需参数。
    BAD_PARAMS = "bad_params"
    #: 参数值不合法（未知媒介 / 未知渲染格式）。
    BAD_VALUE = "bad_value"
    #: IR 文件不存在 —— 通常意味着「还没生成过」。
    MISSING_IR = "missing_ir"
    #: IR 文件在，但读不出来（JSON 截断 / 字段非法 / 版本不对）。
    UNREADABLE_IR = "unreadable_ir"
    #: **Keel 自己出错了。** 与上面所有 kind 都不同：这不是用户的问题，
    #: 是引擎的 bug。插件必须当工具故障上报，不能当成创作结论。
    INTERNAL = "internal"

    def __init__(self, kind: str, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.detail = detail


@dataclass(frozen=True)
class Method:
    """一个可被插件调用的方法。

    `params` / `optional` 是**声明的**参数表，`call()` 按它做前置检查。
    声明在这里而不是靠 handler 自己 `p["x"]` 报 KeyError，
    是为了让 `handshake` 能把签名**发出去** —— 插件据此决定要不要调，
    而不是先调坏一次再猜哪里错了。
    """

    name: str
    summary: str
    handler: Callable[[dict[str, Any]], dict[str, Any]]
    params: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# 序列化助手：把已有对象变成**纯数据**。这里不产生任何新判断。
# ---------------------------------------------------------------------------


def _finding(f: Finding) -> dict[str, Any]:
    return {
        "code": f.code,
        "severity": f.severity.value,
        "message": f.message,
        "scene_id": f.scene_id,
        "entity_id": f.entity_id,
        "suggestion": f.suggestion,
        "evidence": dict(f.evidence),
    }


def _proposal(d: Diff) -> dict[str, Any]:
    return {
        "id": d.id,
        "status": d.status.value,
        "target_card": d.target_card,
        "field": d.field,
        "before": d.before,
        "after": d.after,
        "rationale": d.rationale,
        "source_card": d.source_card,
        "proposed_at": d.proposed_at,
        "decided_at": d.decided_at,
        "decided_by": d.decided_by,
    }


def _template(t: BeatTemplate) -> dict[str, Any]:
    return {
        "id": t.id,
        "name": t.name,
        "origin": t.origin,
        "media": [m.value for m in t.media],
        "beat_count": len(t.beats),
        "validators": list(t.validators),
        "notes": t.notes,
    }


def _require_ir(p: dict[str, Any]) -> NarrativeIR:
    """取 `ir` 参数并加载。错误归一成 `MISSING_IR` / `UNREADABLE_IR`。

    加载本身只有一份实现（`keel/ir/loading.py`）；这里只负责把它翻译成
    **面向插件**的表达。面向人的表达在 `keel/cli.py::_load`（说人话的 SystemExit）。
    两者故意不同 —— 插件读不懂中文提示，人也读不懂 JSON 错误码。
    """
    raw = p.get(PARAM_IR)
    try:
        return load_ir(str(raw))
    except IRLoadError as exc:
        kind = (
            ApiError.MISSING_IR
            if exc.kind == IRLoadError.MISSING
            else ApiError.UNREADABLE_IR
        )
        raise ApiError(
            kind, f"读不出 IR：{exc.path}", path=str(exc.path), reason=exc.reason
        ) from exc


# ---------------------------------------------------------------------------
# handlers —— 每个都只是「调已有函数 + 序列化」
# ---------------------------------------------------------------------------


def _h_handshake(p: dict[str, Any]) -> dict[str, Any]:
    return describe()


def _h_registry(p: dict[str, Any]) -> dict[str, Any]:
    return registry_stats()


def _h_templates(p: dict[str, Any]) -> dict[str, Any]:
    raw = p.get("medium")
    medium: Medium | None = None
    if raw:
        try:
            medium = Medium(raw)
        except ValueError as exc:
            raise ApiError(
                ApiError.BAD_VALUE,
                f"未知媒介：{raw}",
                allowed=[m.value for m in Medium],
            ) from exc
    return {"templates": [_template(t) for t in list_templates(medium)]}


def _h_audit(p: dict[str, Any]) -> dict[str, Any]:
    ir = _require_ir(p)
    rep = run_all(ir)
    return {
        "title": ir.title,
        "health": rep.score(),
        "passed": rep.passed(),
        # 覆盖率必须与健康分**一起**给出：只报分数等于隐瞒「有多少项没测」。
        "coverage": round(rep.coverage(), 4),
        "evaluated_count": len(rep.evaluated),
        "counts": {
            "error": len(rep.errors),
            "warn": len(rep.warnings),
            "info": len(rep.infos),
            "advisory": len(rep.advisory),
        },
        "findings": [_finding(f) for f in rep.findings],
        "advisory": [_finding(f) for f in rep.advisory],
        "skipped": {k: list(v) for k, v in rep.skipped.items()},
        "crashes": dict(rep.crashes),
    }


def _h_proposals(p: dict[str, Any]) -> dict[str, Any]:
    ir = _require_ir(p)
    pending = ir.pending_proposals()
    shown = ir.proposals if p.get("all") else pending
    counts: dict[str, int] = {}
    for d in ir.proposals:
        counts[d.status.value] = counts.get(d.status.value, 0) + 1
    return {
        "title": ir.title,
        "pending_count": len(pending),
        "total_count": len(ir.proposals),
        "counts": counts,
        "proposals": [_proposal(d) for d in shown],
    }


def _h_decide(p: dict[str, Any]) -> dict[str, Any]:
    """裁决结构提案。**会写回 IR 文件**（除非 `no_save`）。

    语义与 `keel/cli.py::cmd_decide` 完全一致，因为两者调用的是同一个
    `KeelPipeline.decide` —— 盖章（墙钟 + 主体）与落盘都不在这里重写。
    """
    ir = _require_ir(p)
    accept = bool(p.get("accept", False))
    if p.get("all"):
        targets = [d.id for d in ir.pending_proposals()]
    else:
        targets = [str(x) for x in (p.get("ids") or [])]
    if not targets:
        raise ApiError(
            ApiError.BAD_PARAMS, "没有指定要裁决的提案（用 all=true 或给出 ids）"
        )

    pipe = KeelPipeline(build_generator(offline=True))
    # 同一次调用 = 同一次操作 = 同一个时刻。
    wall = wall_iso()
    who = p.get("by") or "human"

    done: list[str] = []
    failed: list[dict[str, str]] = []
    for did in targets:
        try:
            pipe.decide(
                ir,
                did,
                accept=accept,
                decided_at=wall,
                decided_by=who,
                story_at=p.get("at"),
            )
            done.append(did)
        except KeyError as exc:
            failed.append({"id": did, "reason": str(exc)})

    saved_to: str | None = None
    if done and not p.get("no_save"):
        # 默认写回原文件：不落盘的裁决不是裁决（同 cmd_decide 的理由）。
        dest = Path(str(p["out"])) if p.get("out") else Path(str(p[PARAM_IR]))
        dest.write_text(ir.to_json(), encoding="utf-8")
        saved_to = str(dest)

    return {
        "verdict": "accepted" if accept else "rejected",
        "decided": done,
        "failed": failed,
        "saved_to": saved_to,
        "decided_at": wall,
        "decided_by": who,
        "telemetry": {
            "accept_rate": pipe.telemetry.accept_rate,
            "accepted": pipe.telemetry.accepted,
            "decisions": pipe.telemetry.decisions,
        },
    }


#: 渲染格式 -> 调用方式。**与 `cmd_render` 用同一批渲染器**。
#: 键名即插件 `--format` 的合法取值（`handshake` 不发这个表，
#: 但 `render` 的 `bad_value` 错误里会把 `allowed` 带出去）。
_RENDERERS: dict[str, Callable[[NarrativeIR, dict[str, Any]], str]] = {
    "text": lambda ir, p: render_text(
        ir,
        show_meta=bool(p.get("meta", False)),
        chronological=bool(p.get("chrono", False)),
        force_prose=bool(p.get("force_prose", False)),
    ),
    "fountain": lambda ir, p: render_fountain(ir),
    "storyboard": lambda ir, p: render_storyboard(ir),
    "ink": lambda ir, p: render_ink(ir),
    "renpy": lambda ir, p: render_renpy(ir),
    "outline": lambda ir, p: render_outline(ir),
    "html": lambda ir, p: render_html(ir),
}


def _h_render(p: dict[str, Any]) -> dict[str, Any]:
    ir = _require_ir(p)
    fmt = str(p.get("format") or "text")
    fn = _RENDERERS.get(fmt)
    if fn is None:
        raise ApiError(
            ApiError.BAD_VALUE, f"未知渲染格式：{fmt}", allowed=sorted(_RENDERERS)
        )
    text = fn(ir, p)
    return {"format": fmt, "chars": len(text), "text": text}


#: 方法表。**唯一的真相来源** —— `handshake` 与 `call()` 都读它。
METHODS: dict[str, Method] = {
    m.name: m
    for m in (
        Method(
            name="handshake",
            summary="握手：返回 API 版本、引擎版本与全部方法签名。插件启动时先调它。",
            handler=_h_handshake,
        ),
        Method(
            name="registry",
            summary="校验器 registry 的统计（门禁/报表数量、按模块分布）。",
            handler=_h_registry,
        ),
        Method(
            name="templates",
            summary="列出结构模板（可按媒介过滤）。",
            handler=_h_templates,
            optional=("medium",),
        ),
        Method(
            name="audit",
            summary="对一份 IR 跑故事体检（健康分 + 覆盖率 + 全部发现）。",
            handler=_h_audit,
            params=(PARAM_IR,),
        ),
        Method(
            name="proposals",
            summary="列出结构提案（默认只列待裁决的）。",
            handler=_h_proposals,
            params=(PARAM_IR,),
            optional=("all",),
        ),
        Method(
            name="decide",
            summary="裁决结构提案。**会写回 IR 文件**（除非 no_save）。",
            handler=_h_decide,
            params=(PARAM_IR,),
            optional=("ids", "all", "accept", "by", "at", "out", "no_save"),
        ),
        Method(
            name="render",
            summary="把 IR 渲染成某个媒介的文本。",
            handler=_h_render,
            params=(PARAM_IR,),
            optional=("format", "meta", "chrono", "force_prose"),
        ),
    )
}


def describe() -> dict[str, Any]:
    """机器可读的能力清单。`handshake` 的返回体，也是反漂移门禁的比对对象。"""
    return {
        "api_version": API_VERSION,
        "keel_version": __version__,
        "methods": [
            {
                "name": m.name,
                "summary": m.summary,
                "params": list(m.params),
                "optional": list(m.optional),
            }
            for m in sorted(METHODS.values(), key=lambda m: m.name)
        ],
    }


def _ok(method: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "api_version": API_VERSION,
        "keel_version": __version__,
        "method": method,
        "data": data,
    }


def _error(method: str, exc: ApiError) -> dict[str, Any]:
    return {
        "ok": False,
        "api_version": API_VERSION,
        "keel_version": __version__,
        "method": method,
        "error": {"kind": exc.kind, "message": exc.message, "detail": exc.detail},
    }


def is_internal(payload: dict[str, Any]) -> bool:
    """这份信封是不是「Keel 自己崩了」。

    CLI 用它决定退出码：`internal` 必须**非零退出**。
    一个以 0 退出的崩溃，在脚本与 CI 里读起来和一次成功一模一样。
    """
    if payload.get("ok"):
        return False
    return (payload.get("error") or {}).get("kind") == ApiError.INTERNAL


def call(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """调用一个方法。**永远返回一个信封，不向调用方抛异常。**

    为什么吞掉异常：插件多半是另一个语言写的（JS/TS），它拿不到 Python 的
    traceback 语义 —— 一个未捕获异常在它那边就是「进程挂了，没有输出」，
    作者看到的是「插件没反应」。结构化错误至少能说清「是版本不匹配，
    还是文件没生成，还是 Keel 有 bug」。
    """
    p = dict(params or {})
    spec = METHODS.get(method)
    if spec is None:
        return _error(
            method,
            ApiError(
                ApiError.BAD_METHOD,
                f"未知方法：{method}",
                allowed=sorted(METHODS),
                api_version=API_VERSION,
            ),
        )

    missing = [k for k in spec.params if p.get(k) in (None, "")]
    if missing:
        return _error(
            method,
            ApiError(ApiError.BAD_PARAMS, f"缺少必需参数：{missing}", missing=missing),
        )

    try:
        data = spec.handler(p)
    except ApiError as exc:
        return _error(method, exc)
    except Exception as exc:  # noqa: BLE001  归一所有内部崩溃，理由见模块 docstring
        return _error(
            method,
            ApiError(
                ApiError.INTERNAL,
                f"{type(exc).__name__}: {exc}",
                type=type(exc).__name__,
            ),
        )
    return _ok(method, data)
