"""自主运行（`loom run`）的检查点持久化层。

跑法（自测）：
    .venv/Scripts/python.exe tests/test_checkpoint.py

── 它存在的唯一理由 ────────────────────────────────────────────────

自主运行很长。跑到第 47 场进程死了，就得从第 47 场续上 —— **从头重跑是
不可接受的**。所以这个模块的全部价值集中在两件事上：

  1. **原子写**：先写临时文件，再 `os.replace`。写一半断电/崩溃，
     上一个好检查点必须原封不动地活着。
  2. **损坏 ≠ 不存在**：一个截断的 JSON 文件，既不能让 `load()` 抛异常
     把整个 run 带崩，也不能被静默当成「没有检查点」—— 后者会让程序
     从第 0 场重新开始，还把「丢了 47 场」这件事藏得干干净净。
     这两种状态必须能**被机器区分**，否则就是本项目反复踩的
     「SKIPPED ≠ PASS」：判据从来没判过，和判过且通过了，长得一模一样。

所以损坏时 `load()` 返回 `None`，但**同时**把原因写进模块级 `last_error`。
`None` 只是「没法用」，`last_error` 才回答「为什么」。只读 `None` 不读
`last_error` 的调用方，等于自己选择了失明 —— 这是文档里写明的契约。

`resume()` 更进一步：目录里有**任何**读不出来的检查点时它**抛异常**。
因为「有损坏文件就悄悄开新档」正是最坏的那种静默 —— 它会让一个跑了一半
的故事变成两个互不相干的故事，而台账上只写着一个。

── 边界 / 诚实的局限 ──────────────────────────────────────────────

  * 只做**单文件、单进程**持久化。没有锁：两个进程同时 `save` 同一个
    run_id，后写的赢，先写的不报错也不合并。多进程并发不在本模块的能力内。
  * `ir_json` 是**不透明字符串**。本模块不解析它（不引入 pydantic 依赖，
    也避免每次 load 都付一遍反序列化代价），因此「JSON 合法但 IR 非法」
    在这里**查不出来**。要校验就用 `NarrativeIR.from_json(state.ir_json)`
    自己兜 —— 空串 `""` 是「尚未产出 IR」的哨兵值，不要喂给 `from_json`。
  * 持久化的是**快照**，不是操作日志。每次 `save` 都是整体覆盖，
    没有增量、没有回溯历史。
  * `os.fsync` 只 sync 文件、不 sync 目录。`replace` 本身是原子的，
    但「机器掉电 + 文件系统没记下目录项」这种极端情况不在保证内。
  * 无网络、无 API key、无新依赖：stdlib + JSON。

IR 的存取口径（本模块不代劳，留给调用方）：

    NarrativeIR.from_json(state.ir_json)      # 读
    state.ir_json = ir.to_json()              # 写
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "RunState",
    "CheckpointError",
    "CorruptCheckpointError",
    "FORMAT_VERSION",
    "last_error",
    "save",
    "load",
    "latest",
    "resume",
    "clear",
    "new_run_id",
    "utcnow_iso",
]

#: 落盘格式版本。读到不认识的版本 -> `CheckpointError.kind == "version"`，
#: 而不是猜一个字段布局出来。
FORMAT_VERSION = 1

_PREFIX = "ckpt-"
_SUFFIX = ".json"
_TMP_SUFFIX = ".tmp"

#: 损坏原因的取值。`"missing"`（没有）与 `"malformed"`/`"schema"`/`"version"`
#: （有但读不出来）是**两类不同的事实**，本模块的存在就是为了不把它们混掉。
KINDS = ("missing", "unreadable", "malformed", "schema", "version")


# ---------------------------------------------------------------------------
# 数据形状
# ---------------------------------------------------------------------------


@dataclass
class RunState:
    """一次自主运行的快照。

    `ir_json` 为 `""` 表示「还没产出 IR」—— 新开的 run 就是这个状态。
    `decisions` 是结构决策台账（提案被采纳/驳回 + 时间戳），自主等级 B 下
    结构改动只能以提案形式出现，所以这条链是事后追责的唯一凭据。
    """

    run_id: str
    idea: str
    params: dict
    completed_scenes: int
    ir_json: str
    decisions: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=lambda: {"scenes": 0, "tokens": 0, "cost": 0.0})
    updated_at: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "_format": FORMAT_VERSION,
            "run_id": self.run_id,
            "idea": self.idea,
            "params": self.params,
            "completed_scenes": self.completed_scenes,
            "ir_json": self.ir_json,
            "decisions": self.decisions,
            "usage": self.usage,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> RunState:
        return cls(
            run_id=data["run_id"],
            idea=data["idea"],
            params=data["params"],
            completed_scenes=data["completed_scenes"],
            ir_json=data["ir_json"],
            decisions=list(data["decisions"]),
            usage=data["usage"],
            updated_at=data["updated_at"],
        )


@dataclass(frozen=True)
class CheckpointError:
    """「为什么这次读不出来」的可观测答案。`None` 只能说明读不出来。"""

    path: str
    kind: str  # 见 KINDS
    message: str

    @property
    def is_absent(self) -> bool:
        """真的没有文件（与「有但坏了」相对）。"""
        return self.kind == "missing"

    def __str__(self) -> str:
        return f"[{self.kind}] {self.path}: {self.message}"


class CorruptCheckpointError(RuntimeError):
    """`resume()` 遇到读不出来的检查点时抛出。

    为什么抛而不是「开新档」：开新档会把「丢了 N 场」变成一次静默的重来。
    自主等级 B 的规则是**结构性问题停下来等人**，这条正好落在这个集合里。
    想从零开始：人工看过 `last_error` 之后先 `clear()`。
    """

    def __init__(self, error: CheckpointError) -> None:
        super().__init__(str(error))
        self.error = error


#: 最近一次 `load()` / `latest()` 的结果。成功为 `None`（注意：`latest()`
#: 在「拿到了好检查点、但目录里另有一个坏文件」时也会把它置上 —— 坏消息
#: 从不因为好消息而消失）。
last_error: CheckpointError | None = None


# ---------------------------------------------------------------------------
# 时间
# ---------------------------------------------------------------------------


def utcnow_iso() -> str:
    """当前 UTC 时刻（秒精度，ISO-8601）。所有时间戳都经由此处或 `now` 注入。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_run_id(idea: str, now: str | None = None) -> str:
    """由 (想法, 时刻) 派生 run_id —— 同参数同结果，测试里可以断言相等。"""
    stamp = now or utcnow_iso()
    digest = hashlib.sha256(f"{idea}\x00{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"run-{digest}"


# ---------------------------------------------------------------------------
# 写
# ---------------------------------------------------------------------------


def _serialize(state: RunState) -> str:
    """状态 -> JSON 文本。**故意做成单点**：测试通过替换它来模拟「写一半崩了」。"""
    return json.dumps(state.to_payload(), ensure_ascii=False, indent=2)


def save(state: RunState, directory: Path, *, now: str | None = None) -> Path:
    """原子落盘，返回写到的路径。目录不存在则创建。

    流程：临时文件 -> 写满 -> flush + fsync -> `os.replace(tmp, final)`。
    `os.replace` 在同一文件系统上是原子的，所以任何时刻读 `final`，
    读到的要么是上一版完整内容，要么是这一版完整内容，绝不会是半截。
    中途任何异常都会删掉临时文件再往上抛，不留垃圾。
    """
    global last_error

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    state.updated_at = now or utcnow_iso()

    data = _serialize(state)  # 序列化失败（不可 JSON 化的 params）直接抛，不静默降级
    final = directory / f"{_PREFIX}{state.run_id}{_SUFFIX}"

    fd, tmp = tempfile.mkstemp(
        dir=str(directory), prefix=f"{_PREFIX}{state.run_id}.", suffix=_TMP_SUFFIX
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:  # 某些平台/文件系统不支持 fsync；落盘尽力而为
                pass
        os.replace(tmp, final)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    last_error = None
    return final


# ---------------------------------------------------------------------------
# 读
# ---------------------------------------------------------------------------


def _read(path: Path) -> tuple[RunState | None, CheckpointError | None]:
    """读一个文件。返回 `(状态, 错误)`，二者恰有一个非空。**不抛、不静默。**"""
    path = Path(path)
    if not path.exists():
        return None, CheckpointError(str(path), "missing", "检查点文件不存在")

    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, CheckpointError(str(path), "unreadable", f"读不出来：{exc!r}")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, CheckpointError(
            str(path), "malformed", f"不是合法 JSON（截断/损坏）：{exc.msg} @ 第 {exc.lineno} 行"
        )

    if not isinstance(data, dict):
        return None, CheckpointError(str(path), "schema", f"顶层不是对象：{type(data).__name__}")

    version = data.get("_format")
    if version != FORMAT_VERSION:
        return None, CheckpointError(
            str(path), "version", f"格式版本 {version!r} != 本模块 {FORMAT_VERSION}"
        )

    need = ("run_id", "idea", "params", "completed_scenes", "ir_json", "decisions", "usage")
    missing = [k for k in need if k not in data]
    if missing:
        return None, CheckpointError(str(path), "schema", f"缺字段 {missing}")

    if not isinstance(data["run_id"], str) or not isinstance(data["idea"], str):
        return None, CheckpointError(str(path), "schema", "run_id / idea 必须是字符串")
    if not isinstance(data["params"], dict) or not isinstance(data["usage"], dict):
        return None, CheckpointError(str(path), "schema", "params / usage 必须是对象")
    if not isinstance(data["ir_json"], str):
        return None, CheckpointError(str(path), "schema", "ir_json 必须是字符串")
    if not isinstance(data["completed_scenes"], int) or isinstance(data["completed_scenes"], bool):
        return None, CheckpointError(str(path), "schema", "completed_scenes 必须是整数")
    if not isinstance(data["decisions"], list):
        return None, CheckpointError(str(path), "schema", "decisions 必须是数组")

    state = RunState.from_payload(data)
    return state, None


def load(path: Path) -> RunState | None:
    """读一个检查点。读不出来返回 `None`，并把原因写进 `last_error`。

    `None` 的两种含义**必须**靠 `last_error` 区分：
      * `last_error is None`                -> 没有这个文件，属于「不存在」
      * `last_error.kind == "missing"`      -> 同上（显式写出，便于断言）
      * 其它 `kind`                         -> 文件在，但坏了
    """
    global last_error
    last_error = None
    state, err = _read(path)
    last_error = err
    return state


def latest(directory: Path) -> RunState | None:
    """目录里 `updated_at` 最新的那一个检查点；没有则返回 `None`。

    临时文件（`*.tmp`）不计入 —— 它们是**正在写**的证据，不是写完的证据。
    目录里若有读不出来的文件：仍然返回最新的那个**好**检查点，但把
    `last_error` 置上 —— 坏文件不会因为有一个好的就被当成没发生过。
    若一个能读的都没有，返回 `None` 且 `last_error` 非空。
    """
    global last_error
    last_error = None

    directory = Path(directory)
    files = sorted(directory.glob(f"{_PREFIX}*{_SUFFIX}")) if directory.is_dir() else []
    if not files:
        last_error = CheckpointError(str(directory), "missing", "目录里没有检查点文件")
        return None

    states: list[RunState] = []
    first_error: CheckpointError | None = None
    for f in files:
        state, err = _read(f)
        if state is not None:
            states.append(state)
        elif first_error is None:
            first_error = err

    last_error = first_error
    if not states:
        return None
    # 同 stamp 时用 run_id 兜底，保证顺序确定（不依赖目录遍历顺序）
    return max(states, key=lambda s: (s.updated_at, s.run_id))


# ---------------------------------------------------------------------------
# 续跑 / 清理
# ---------------------------------------------------------------------------


def resume(
    directory: Path,
    idea: str,
    params: dict,
    *,
    now: str | None = None,
) -> RunState:
    """有匹配的检查点就续跑，否则开新档。

    匹配口径是 **idea**（run 的身份）。**不同 idea 一律开新档** ——
    一个故事绝不能继承另一个故事的场景数、IR 或台账，那会产出一篇
    「别人的第 47 场」长在自己身上的故事，而没有任何一处会报错。

    目录里有读不出来的文件时抛 `CorruptCheckpointError`（连累原因是
    `last_error`），**不**悄悄开新档。
    """
    stamp = now or utcnow_iso()
    state = latest(directory)
    # 只有「有文件但读不出来」才停下等人。目录空空如也（kind == "missing"）
    # 是合法的开新档场景 —— 把 missing 也算作损坏，就永远不会有人能开第一个档。
    if last_error is not None and not last_error.is_absent:
        raise CorruptCheckpointError(last_error)
    if state is not None and state.idea == idea:
        return state
    return RunState(
        run_id=new_run_id(idea, stamp),
        idea=idea,
        params=dict(params),
        completed_scenes=0,
        ir_json="",  # 哨兵：尚未产出 IR
        decisions=[],
        usage={"scenes": 0, "tokens": 0, "cost": 0.0},
        updated_at=stamp,
    )


def clear(directory: Path) -> None:
    """删掉目录里所有检查点（含残留临时文件）。目录本身保留；不存在则什么都不做。"""
    directory = Path(directory)
    if not directory.is_dir():
        return
    for f in list(directory.glob(f"{_PREFIX}*{_SUFFIX}")) + list(
        directory.glob(f"{_PREFIX}*{_TMP_SUFFIX}")
    ):
        try:
            f.unlink()
        except OSError:
            pass
