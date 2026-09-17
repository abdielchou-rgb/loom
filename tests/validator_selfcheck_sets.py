"""门禁校验器自检样本集（P4 · 校验器自检）。

对每个**门禁** code（即 `REQUIRES` 中、且不在 `REPORTS` 名单里的门禁项），提供：

    positive : 该 code 应当命中的最小输入（≥1 条）
    negative : 该 code 不应命中的最小输入（≥1 条）

## 诚实声明（铁律 22）

本集合是**合成 / 构造**出来的，不是真实故事分布的采样。
它的用途是**校验器之间的相对比较**（谁的 precision/recall 更可信），
**不构成绝对准确率**。外部证据（ConStory-Checker 等）显示自动一致性
检查器约 ~68% 准确；Loom 此前只报「结构分 89」而从不报 precision/recall，
这一节把可信度读数补上。

## 构造方式

复用 `tests.fixtures` 的两样东西，以保证样本可复现且「会命中」已被独立证明：

  * `clean_copy()` —— 离线流水线（mock 生成器）产出的「结构上无缺陷」IR。
    作为 **negative**：在健康基线上，门禁校验器应当 0 ERROR + 0 WARN
    （INFO 通报允许）。`scripts/verify.py` 第 5 节已断言这点。
  * `MUTATIONS[code]` —— 该 code 对应的反例变异（就地修改 IR）。
    作为 **positive**：在基线深拷贝上注入缺陷。这套反例已被 `verify.py`
    第 7 节（净命中率）证明能让对应校验器**严重度升级**，因此 positive
    必然产出 ≥1 条 Finding。

> 注：基线虽由流水线产出，但用的是确定性 mock 生成器、无任何真实模型调用，
> 本质仍是构造样本，符合「合成」的口径。
"""

from __future__ import annotations

from loom.ir.enums import Medium
from loom.validators.base import REPORTS, REQUIRES
from tests.fixtures import MUTATIONS, clean_copy

#: 门禁 code = REQUIRES 中、且不在 REPORTS 里的 code（数量从 registry_stats 派生）。
GATING_CODES: list[str] = sorted(set(REQUIRES) - set(REPORTS))


def make_positive(code: str):
    """在干净基线深拷贝上注入该 code 对应的缺陷 → 应当命中。

    返回一份**全新的** NarrativeIR（每次调用都深拷贝，保证样本互不污染）。
    """
    ir = clean_copy(Medium.NOVEL)
    fn, _expected = MUTATIONS[code]
    fn(ir)
    return ir


def make_negative(code: str):
    """结构上无缺陷的干净基线 → 不应命中（允许 INFO 通报）。"""
    return clean_copy(Medium.NOVEL)


#: 无法让校验器真正命中的 code -> 原因（用于报告里诚实标注）。
#: 当前 33 个门禁 code 的反例变异都能让对应校验器升级，故此处为空。
NOT_FIRING: dict[str, str] = {}


SELFCHECK: dict[str, dict] = {}
for _code in GATING_CODES:
    SELFCHECK[_code] = {
        "positive": [make_positive(_code)],
        "negative": [make_negative(_code)],
    }
