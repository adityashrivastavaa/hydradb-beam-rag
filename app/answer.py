"""Final step: Claude answers from the top-k documents (single call, not an agent).

Needs Anthropic credentials (ANTHROPIC_API_KEY, or an `ant auth login` profile).
"""
from __future__ import annotations

import anthropic

from .config import CLAUDE_MODEL

SYSTEM = (
    "You answer questions about a long-running conversation between a user and an AI "
    "assistant. You are given excerpts from that conversation, ranked by relevance. "
    "Answer only from the excerpts. When they contradict each other, say so and quote both "
    "sides. When the excerpts do not contain the answer, say that the conversation does not "
    "cover it rather than guessing. Cite the excerpts you used by their [n] number."
)


def build_context(chunks: list[dict]) -> str:
    return "\n\n".join(f"<excerpt n=\"{i}\" doc_id=\"{c['doc_id']}\">\n{c['text']}\n</excerpt>"
                       for i, c in enumerate(chunks, 1))


class Answerer:
    def __init__(self, model: str = CLAUDE_MODEL):
        self.model = model
        self.client = anthropic.Anthropic()

    def answer(self, question: str, chunks: list[dict]) -> dict:
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM,
            output_config={"effort": "medium"},
            # On a policy refusal the API re-runs the request on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": f"{build_context(chunks)}\n\nQuestion: {question}"}],
        )
        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            return {"answer": None, "refused": True, "refusal_category": category, "model": response.model}
        text = "".join(b.text for b in response.content if b.type == "text")
        return {"answer": text, "refused": False, "model": response.model,
                "usage": {"input_tokens": response.usage.input_tokens,
                          "output_tokens": response.usage.output_tokens}}
