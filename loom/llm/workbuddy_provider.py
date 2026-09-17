"""WorkBuddy 驱动的生成器：**Loom 不生成，Loom 发问。**

为什么需要它
------------

铁律 6 要求「无 API key 也能端到端跑通」。`MockGenerator` 满足了这一点，
但它产出的是**固定语料** —— 用它演示，等于演示一个背稿的演员：形态对，
内容假。而 `LiteLLMGenerator` 能产出真内容，却需要 key。

第三条路是：把「模型」这一步**外包出去**。

    LoomPipeline ──渲染提示词──> .wb_queue/answers.json（待填）
                                        │
              WorkBuddy / 人 / 任意 LLM 界面   填 `output`
                                        │
    LoomPipeline <──解析 + 校验─────────┘

这不是权宜之计，它有两个真实价值：

1. **零依赖产出真内容**。没有 key、没有网络、没有 SDK，也能让流水线
   跑出**有内容的**剧本 —— 只要有人（或有 agent）愿意填那份 JSON。
2. **可审计**。API 调用是不可复现的黑盒；这里每一次「模型调用」都落成
   一个**人能读的文件**：提示词、版本号、payload 哈希、答案全在。
   对「AI 参与度计量」这件事来说，这份落盘本身就是证据 ——
   它是可回放的，而 `litellm.completion()` 不是。

为什么按 `任务#序号` 而不是按 payload 哈希寻址
--------------------------------------------

按哈希寻址更严谨（改了输入必然要求新答案），但它有个致命的操作后果：
**你必须一个一个填** —— 因为下一个请求的 payload 取决于上一个答案，
它的哈希在你填完之前根本不存在。7 个请求 = 7 轮往返。

按 `prose#2` 这种序号寻址，则可以在**看到第一个提示词之后就把后面
所有答案一次写好**，一轮跑完。代价是「改了想法却沿用旧答案」的风险，
这里用 `_hash` 字段 + 命令行告警来兜，不靠自觉。

用法
----

    loom write "想法" --generator workbuddy --out out/x
    # ✗ 待填 7 个请求 → out/x/.wb_queue/answers.json
    #   填好后**重跑同一条命令**，流水线接着走（已填的不会丢）。

答案文件的形状（`output` 之外都是下划线开头的元信息，供人读）：

    {
      "premise#1": {
        "_task": "premise", "_index": 1, "_prompt_version": "premise.v2",
        "_hash": "a1b2c3...", "_system": "你是故事内核设计者…",
        "_prompt": "想法：…",
        "output": { ... }
      }
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import REGISTRY, TokenLedger, payload_hash

QUEUE_DIRNAME = ".wb_queue"
ANSWERS_NAME = "answers.json"
PARAMS_NAME = "params.json"


def queue_dir_for(idea: str, base: str | Path = "out") -> Path:
    """队列目录：**单一实现**，CLI 与网页都必须来这里取。

    为什么从**想法哈希**派生而不是放在输出目录里：输出目录名来自标题，
    而标题要等前提层跑完才有 —— 队列却必须在第一行代码之前就绪。
    换想法 = 换队列，于是不会误用上一个故事的 `prose#1`。
    """
    import hashlib

    return (
        Path(base) / QUEUE_DIRNAME / hashlib.sha1(idea.encode("utf-8")).hexdigest()[:8]
    )


class PendingGeneration(RuntimeError):
    """有待填请求。这不是崩溃，是**在等人** —— 退出码要能区分。"""

    def __init__(self, missing: list[str], path: Path) -> None:
        self.missing = missing
        self.path = path
        super().__init__(
            f"待填 {len(missing)} 个请求：{', '.join(missing)}\n"
            f"  答案文件：{path}"
        )


class WorkBuddyAnswerError(RuntimeError):
    """答案存在但形状不对。**明确报错，不静默回退到 Mock。**

    回退到 Mock 意味着产物里混进了桩件语料，而溯源台账会把它记成
    「WorkBuddy 生成的」—— 那是在伪造来源。宁可停下来。
    """


def _est_tokens(text: str) -> int:
    """token 粗估。只用于记账量级，**不是计费依据** —— 别拿它算钱。"""
    return max(1, len(str(text)) // 2)


class WorkBuddyGenerator:
    """把生成外包给 WorkBuddy（或人）的 Generator。

    满足 `Generator` 协议，因此下游零改动 —— 这正是协议存在的意义。
    """

    #: 溯源台账会记录这个值。它必须**诚实**：内容确实是 AI 产的，
    #: 不因为「经过了人一道手」就变成 HUMAN。
    model_id = "workbuddy"

    def __init__(
        self,
        queue_dir: str | Path,
        *,
        ledger: TokenLedger | None = None,
    ) -> None:
        self.queue_dir = Path(queue_dir)
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = ledger
        self._counter: dict[str, int] = {}
        self._answers: dict[str, Any] = self._load()
        self._asks: dict[str, dict[str, Any]] = {}
        self.stale: list[str] = []

    # -- 落盘 ------------------------------------------------------------

    @property
    def answers_path(self) -> Path:
        return self.queue_dir / ANSWERS_NAME

    def _load(self) -> dict[str, Any]:
        if not self.answers_path.exists():
            return {}
        try:
            data = json.loads(self.answers_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # 文件坏了就当没有 —— 但**不静默**：让调用方看见。
            return {"_broken": True}
        return data if isinstance(data, dict) else {}

    def flush(self) -> None:
        """把「问了什么」写回答案文件，**保留已填的 output**。

        合并而不是覆盖：覆盖会抹掉那些**还没被问到、但已经提前写好**的
        答案 —— 而提前写正是本生成器能一轮跑完的前提。
        """
        merged: dict[str, Any] = {}
        for key, ask in self._asks.items():
            old = self._answers.get(key)
            entry = dict(ask)
            if isinstance(old, dict) and old.get("output") is not None:
                entry["output"] = old["output"]
            else:
                entry["output"] = None
            merged[key] = entry
        # 保留文件里已有、但本次运行没问到的键（提前写好的答案）
        for key, val in self._answers.items():
            if key.startswith("_"):
                continue
            if key not in merged and isinstance(val, dict):
                merged[key] = val
        self.answers_path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._answers = merged

    # -- 协议 ------------------------------------------------------------

    def generate(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        idx = self._counter.get(task, 0) + 1
        self._counter[task] = idx
        key = f"{task}#{idx}"

        try:
            p = REGISTRY.get(task)
            system, version = p.system, p.version
            rendered = p.render(payload)
        except KeyError:
            # 任务没有注册提示词：这不是致命错误，但**要留痕** ——
            # 填答案的人得知道该产出什么形状。
            system = f"（任务 {task} 没有注册提示词，按以下输入自行判断输出形状）"
            version = "-"
            rendered = json.dumps(payload, ensure_ascii=False, indent=2)

        h = payload_hash(task, payload, self.model_id)
        self._asks[key] = {
            "_task": task,
            "_index": idx,
            "_prompt_version": version,
            "_hash": h,
            "_system": system,
            "_prompt": rendered,
        }

        entry = self._answers.get(key)
        out = entry.get("output") if isinstance(entry, dict) else None

        if out is not None and isinstance(entry, dict):
            old_h = entry.get("_hash")
            if old_h and old_h != h:
                # 换了输入却沿用旧答案。**报警，但仍然用** ——
                # 停下来问一次是更好的体验还是更差的，取决于场景；
                # 这里选择「用，但喊出来」，因为静默沿用才是真的危险。
                self.stale.append(key)

        self.flush()

        if out is None:
            raise PendingGeneration(self._missing(), self.answers_path)
        if not isinstance(out, (dict, list)):
            raise WorkBuddyAnswerError(
                f"{key} 的 output 必须是 JSON 对象或数组，实际是 "
                f"{type(out).__name__}。"
                f"\n  提示词要求的输出形状见 {self.answers_path} 里的 _prompt。"
            )
        if self.ledger:
            self.ledger.record(task, _est_tokens(rendered), _est_tokens(json.dumps(out)))
        return out  # type: ignore[return-value]

    def _missing(self) -> list[str]:
        """本次运行问过、但还没有答案的键。

        注意查的是 `flush()` **之后**的 `_answers`（里面已被补上 `output: None`），
        不是 `_asks` —— `_asks` 只记「问了什么」，不记「答了没」。
        查错地方会让每一个请求都被当成待填，报错信息就成了噪音。
        """
        return [
            k for k in sorted(self._asks)
            if not (isinstance(self._answers.get(k), dict)
                    and self._answers[k].get("output") is not None)
        ]

    # -- 供 CLI 用 -------------------------------------------------------

    def pending_keys(self) -> list[str]:
        return [
            k for k in self._asks
            if not (isinstance(self._answers.get(k), dict)
                    and self._answers[k].get("output") is not None)
        ]

    def reused_keys(self) -> list[str]:
        return [
            k for k in self._asks
            if isinstance(self._answers.get(k), dict)
            and self._answers[k].get("output") is not None
        ]
