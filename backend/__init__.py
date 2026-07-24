"""Devil's Committee — AI Investment Debate Coach (backend package).

Same engine, two faces:
  - Track 18 (PandaAI): an A2A Remote Agent that runs an adversarial multi-agent
    debate and an INDEPENDENT audit — real collaboration, not a chain.
  - Track 15 (Duxiaoman): a financial-literacy *coach* that shows disagreement and
    never gives buy/sell answers.

Everything here runs today with a MockLLM + stub skills. Swapping in the real
DeepSeek key and the real QuantSkills CLIs is a config change, not a rewrite.
"""

__all__ = ["config", "models", "llm", "agents", "orchestration", "compliance"]
