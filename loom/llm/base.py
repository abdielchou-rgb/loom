"""LLM 抽象层。

设计目标：让整条流水线在**没有 API key 的情况下也能端到端跑通**。

    Generator 协议      统一接口
    MockGenerator       确定性参考实现（离线可跑，验证数据流）
    LiteLLMGenerator    真实调用（多 provider + 版本固定）
    TokenLedger         成本记账
    PromptRegistry      提示词版本化（同一部长篇换模型会导致风格断裂，必须可追溯）

为什么要版本化：换模型会让风格突变，必须能追溯「这一段是哪个模型 + 哪个提示词版本
产出的」，否则无法做 A/B 也无法定位退化。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# 协议
# ---------------------------------------------------------------------------


@runtime_checkable
class Generator(Protocol):
    """所有生成器的统一接口。

    task      任务标识，如 "premise" / "scene_card" / "prose" / "audience"
    payload   结构化输入
    返回      结构化输出（dict），不是自由文本 —— 这样才可校验、可缓存、可回放
    """

    model_id: str

    def generate(self, task: str, payload: dict[str, Any]) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# 记账
# ---------------------------------------------------------------------------


@dataclass
class TokenLedger:
    """成本记账。按任务聚合，便于定位成本热点。"""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_hits: int = 0
    by_task: dict[str, int] = field(default_factory=dict)

    def record(
        self, task: str, prompt_tokens: int, completion_tokens: int, cached: bool = False
    ) -> None:
        self.calls += 1
        self.by_task[task] = self.by_task.get(task, 0) + 1
        if cached:
            self.cache_hits += 1
        else:
            self.prompt_tokens += prompt_tokens
            self.completion_tokens += completion_tokens

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def estimate_cost_usd(self, in_price: float = 3.0, out_price: float = 15.0) -> float:
        """按每百万 token 计价估算。默认值仅供量级参考，请按实际模型改。"""
        return (
            self.prompt_tokens / 1_000_000 * in_price
            + self.completion_tokens / 1_000_000 * out_price
        )

    def render(self) -> str:
        lines = [
            "── Token 记账 " + "─" * 42,
            f"  调用次数      {self.calls}（缓存命中 {self.cache_hits}）",
            f"  输入 tokens   {self.prompt_tokens:,}",
            f"  输出 tokens   {self.completion_tokens:,}",
            f"  合计          {self.total_tokens:,}",
            f"  估算成本      ${self.estimate_cost_usd():.4f}",
        ]
        if self.by_task:
            lines.append("  按任务：")
            for k, v in sorted(self.by_task.items(), key=lambda x: -x[1]):
                lines.append(f"    {k:<20} {v} 次")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 缓存
# ---------------------------------------------------------------------------


def payload_hash(task: str, payload: dict[str, Any], model_id: str) -> str:
    raw = json.dumps(
        {"task": task, "payload": payload, "model": model_id},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


class CachedGenerator:
    """内容寻址缓存。IR 的硬约束部分高度可复用，缓存命中率通常很高。"""

    def __init__(self, inner: Generator, ledger: TokenLedger | None = None) -> None:
        self.inner = inner
        self.model_id = inner.model_id
        self._cache: dict[str, dict[str, Any]] = {}
        self.ledger = ledger

    def generate(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        key = payload_hash(task, payload, self.model_id)
        if key in self._cache:
            if self.ledger:
                self.ledger.record(task, 0, 0, cached=True)
            return self._cache[key]
        out = self.inner.generate(task, payload)
        self._cache[key] = out
        return out

    @property
    def hit_rate(self) -> float:
        return 0.0  # 由 ledger 统计


# ---------------------------------------------------------------------------
# 提示词注册表（版本化）
# ---------------------------------------------------------------------------


@dataclass
class Prompt:
    id: str
    version: str
    system: str
    template: str
    output_schema: dict[str, Any] = field(default_factory=dict)
    #: 渲染时缺失的模板字段。**不抛异常，但要留痕。**
    #: 静默退化与「永不静默改写」是同一个原则：出问题可以，别不吭声。
    #: 提示词少一个字段，模型就少一条约束，而校验器随后会因「模型没照做」
    #: 报警 —— 根因在提示词层，症状却出现在校验层，没有留痕就查不出来。
    render_misses: list[str] = field(default_factory=list)

    def render(self, payload: dict[str, Any]) -> str:
        try:
            return self.template.format(**payload)
        except (KeyError, IndexError) as exc:
            # 缺字段时退化为原样 + JSON 附录，避免整条流水线因一个字段挂掉。
            # 但把缺失的字段名记下来 —— 否则这是一次静默降级。
            missing = re.findall(r"\{(\w+)\}", self.template)
            absent = [k for k in missing if k not in payload]
            self.render_misses.append(
                f"{self.id}: {absent or [str(exc)]}"
            )
            return self.template + "\n\n输入：\n" + json.dumps(
                payload, ensure_ascii=False, indent=2
            )


class PromptRegistry:
    def __init__(self) -> None:
        self._prompts: dict[str, Prompt] = {}

    def register(self, p: Prompt) -> Prompt:
        self._prompts[p.id] = p
        return p

    def get(self, prompt_id: str) -> Prompt:
        if prompt_id not in self._prompts:
            raise KeyError(f"未注册的提示词: {prompt_id!r}")
        return self._prompts[prompt_id]

    def versions(self) -> dict[str, str]:
        return {k: v.version for k, v in self._prompts.items()}

    def all(self) -> list[Prompt]:
        return list(self._prompts.values())


REGISTRY = PromptRegistry()
