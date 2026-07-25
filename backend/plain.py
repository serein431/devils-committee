"""Plain-language layer — the 15 度小满 命门: a beginner actually understands.

The debate is grounded in real quant metrics (for the 18 judges); this module
adds a jargon-free one-liner / analogy for each claim and each audit verdict, so
a 14-year-old reads the takeaway without knowing what '存活偏差' or 'IC' means.

Deterministic and pedagogical — no LLM call needed; the analogies are the teaching.
"""
from __future__ import annotations

# One plain-language anchor per debate role.
PLAIN_CLAIM = {
    "bull": "一句话：它在现有证据里寻找上行可能，但因子入选不等于方向或预测已经成立。",
    "bear": "一句话：它在检查流动性和事件假设哪里可能过于乐观，不把压力测试外推成市场结论。",
    "macro": "一句话：它在检查现有证据能否支持风格或环境判断；证据没有覆盖时就应保留判断。",
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
    "thin_data": "验证还不充分：当前结果既不能确认异常，也不能证明已经通过独立检验。",
    "missing_evidence": "资料没有拿全：现在无法完成检查，也不能把它说成已经通过或已经发现问题。",
}


def plain_claim(side: str) -> str:
    return PLAIN_CLAIM.get(side, "")


def plain_audit(status: str) -> str:
    return PLAIN_AUDIT.get(status, "")
