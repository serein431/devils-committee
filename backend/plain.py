"""Plain-language layer — the 15 度小满 命门: a beginner actually understands.

The debate is grounded in real quant metrics (for the 18 judges); this module
adds a jargon-free one-liner / analogy for each claim and each audit verdict, so
a 14-year-old reads the takeaway without knowing what '存活偏差' or 'IC' means.

Deterministic and pedagogical — no LLM call needed; the analogies are the teaching.
"""
from __future__ import annotations

# One plain-language anchor per debate role.
PLAIN_CLAIM = {
    "bull": "一句话：它看好这只票，因为几个关键数字都朝上——但记住，看好不等于该买。",
    "bear": "一句话：它对这只票有顾虑，盯着的是能不能顺利卖出、以及事件风险。",
    "macro": "一句话：它在讲大环境（顺风还是逆风），不对这只票单独下结论。",
    "risk": "一句话：它只提醒风险边界（最坏会怎样），不站多空任何一边。",
}

# Beginner analogy per audit verdict — this is where '教你当裁判' happens.
PLAIN_AUDIT = {
    "pass": "现有审计结果没有指出问题，但这不代表以后不会出现风险。",
    "selection_bias": "小心：这像“只把考了高分的同学拿出来吹，输的都不提”——样本被挑过了，"
                      "看起来的规律可能是假的。",
    "bad_data": "小心：这条用的价格数据本身有问题（好比体重秤没归零就称），"
                "先把数据修对，再谈结论。",
    "suspected_overfit": "小心：这像“把这次的答案背下来考试”，换一套题就不灵——"
                         "不是真规律，是凑出来的。",
    "thin_data": "证据太少：既不能信、也不能一口否掉，先别当真，等更多数据。",
}


def plain_claim(side: str) -> str:
    return PLAIN_CLAIM.get(side, "")


def plain_audit(status: str) -> str:
    return PLAIN_AUDIT.get(status, "")
