"""真实 LLM 提供方（可选依赖）。

设计要点：
  - **模型版本固定**：同一部长篇中途换模型会导致风格断裂。每次调用都把
    model_id 与 prompt_version 写进 Provenance，可追溯、可 A/B。
  - **强制结构化输出**：优先用 JSON mode / response_format；不支持时退化为
    「抽取第一个 JSON 块」，并对失败做一次修复重试。
  - **成本硬上限**：超过预算立即抛错，不静默超支。

未安装 litellm 时本模块可导入但不实例化，保证离线环境不受影响。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .base import Prompt, TokenLedger

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class BudgetExceeded(RuntimeError):
    pass


def _extract_json(text: str) -> dict[str, Any]:
    """从模型输出里抽取 JSON。容忍 markdown 代码块与前后废话。"""
    text = text.strip()
    m = _JSON_BLOCK.search(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 退化为「第一个 { 到最后一个 }」
    lo, hi = text.find("{"), text.rfind("}")
    if lo != -1 and hi > lo:
        try:
            return json.loads(text[lo : hi + 1])
        except json.JSONDecodeError:
            pass
    lo, hi = text.find("["), text.rfind("]")
    if lo != -1 and hi > lo:
        try:
            return {"items": json.loads(text[lo : hi + 1])}
        except json.JSONDecodeError:
            pass
    raise ValueError(f"模型输出无法解析为 JSON：{text[:200]!r}")


class ModelCallError(RuntimeError):
    """真模型调用失败，且属于「配置 / 网络 / 额度」这类用户能自己修的问题。

    为什么单独建这个类：litellm 失败时抛的是它自己的异常，直接冒泡到 CLI
    就是**一段 Python traceback**。对非技术用户，traceback 与「软件坏了」
    无法区分 —— 而真相往往只是没设 API key。这里把可自修的失败翻译成人话。
    """


def _friendly_error(exc: Exception, model: str) -> str:
    """把 litellm 的异常翻译成「下一步该做什么」。"""
    name = type(exc).__name__
    low = str(exc).lower()
    # 注意：OpenAI 缺 key 时 litellm 报的是 InternalServerError，不是 AuthenticationError，
    # 只按异常名判断会给不出「去设 OPENAI_API_KEY」这条最有用的指引。
    # 所以**同时看消息正文**（api_key / credential / unauthorized / 401）。
    auth_hint = (
        "authentication" in name.lower()
        or "api key" in low
        or "api_key" in low
        or "apikey" in low
        or "credential" in low
        or "unauthorized" in low
        or "401" in low
    )
    if auth_hint:
        return (
            f"模型 {model} 认证失败 —— 没读到可用的 API key。\n"
            f"    设好对应的环境变量再跑，例如：set OPENAI_API_KEY=sk-...\n"
            f"    或去掉 --model，回到离线确定性参考实现。"
        )
    if "connection" in name.lower() or "timeout" in name.lower():
        return (
            f"连不上模型服务 {model}：{exc}\n"
            f"    检查网络；若设了代理，本机请求要绕过代理。"
        )
    if "ratelimit" in name.lower():
        return f"触发限流：{exc}\n    稍后重试，或换一个模型。"
    if "notfound" in name.lower():
        return f"模型名 {model} 不被 provider 识别：{exc}"
    return f"模型调用失败（{name}）：{exc}"


class LiteLLMGenerator:
    """基于 litellm 的多 provider 生成器。"""

    def __init__(
        self,
        model: str,
        *,
        ledger: TokenLedger | None = None,
        temperature: float = 0.85,
        max_tokens: int = 4096,
        token_budget: int | None = None,
        api_key_env: str | None = None,
    ) -> None:
        try:
            import litellm  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "未安装 litellm。请执行 pip install litellm，"
                "或改用 MockGenerator 做离线验证。"
            ) from exc

        self.model_id = model
        self.ledger = ledger
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.token_budget = token_budget
        if api_key_env and os.environ.get(api_key_env):
            os.environ.setdefault("OPENAI_API_KEY", os.environ[api_key_env])

    def _check_budget(self) -> None:
        if (
            self.token_budget is not None
            and self.ledger is not None
            and self.ledger.total_tokens >= self.token_budget
        ):
            raise BudgetExceeded(
                f"已超出 token 预算 {self.token_budget:,}"
                f"（当前 {self.ledger.total_tokens:,}）"
            )

    def generate(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        from .prompts import REGISTRY

        prompt: Prompt = REGISTRY.get(task)
        self._check_budget()

        import litellm

        # litellm 默认会往控制台刷 "Give Feedback / Get Help" 与调试提示，
        # 盖住我们真正想说的话。用户要的是 Keel 的指引，不是 litellm 的自述。
        litellm.suppress_debug_info = True

        user = prompt.render(payload)
        kwargs: dict[str, Any] = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if prompt.output_schema:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            resp = litellm.completion(**kwargs)
        except Exception as exc:  # 配置/网络/额度类失败 → 人话，不是 traceback
            raise ModelCallError(_friendly_error(exc, self.model_id)) from exc
        text = resp.choices[0].message.content or ""

        usage = getattr(resp, "usage", None)
        pt = getattr(usage, "prompt_tokens", 0) if usage else 0
        ct = getattr(usage, "completion_tokens", 0) if usage else 0
        if self.ledger:
            self.ledger.record(task, pt, ct)

        try:
            return _extract_json(text)
        except ValueError:
            # 一次修复重试：明确要求只输出 JSON
            fix = litellm.completion(
                model=self.model_id,
                messages=[
                    {"role": "system", "content": "只输出合法 JSON，不要任何其他文字。"},
                    {"role": "user", "content": f"把下面内容转成 JSON：\n\n{text}"},
                ],
                temperature=0.0,
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"},
            )
            if self.ledger:
                u2 = getattr(fix, "usage", None)
                self.ledger.record(
                    task,
                    getattr(u2, "prompt_tokens", 0) if u2 else 0,
                    getattr(u2, "completion_tokens", 0) if u2 else 0,
                )
            return _extract_json(fix.choices[0].message.content or "")


def build_generator(
    model: str | None = None,
    *,
    ledger: TokenLedger | None = None,
    token_budget: int | None = None,
    offline: bool = False,
    queue_dir: str | None = None,
):
    """工厂：默认走离线 Mock，显式给 model 才走真实调用。

    这样 CI 与本地开发不需要 API key，也保证测试确定性。
    """
    from .mock import MockGenerator

    if offline or not model:
        return MockGenerator(ledger=ledger)
    # 「workbuddy」不是模型名，是一种**驱动方式**：不发请求，发问题。
    if model == "workbuddy":
        from .workbuddy_provider import WorkBuddyGenerator

        return WorkBuddyGenerator(queue_dir or ".wb_queue", ledger=ledger)
    return LiteLLMGenerator(
        model, ledger=ledger, token_budget=token_budget
    )
