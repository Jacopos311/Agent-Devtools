"""
Stale-memory-bug example -- the "killer demo" for agent-devtools.

The same user question is asked twice against the same toy refund agent.
`good_run.py` retrieves and trusts the current pricing document.
`bad_run.py` (same agent, same question) retrieves and trusts a stale
pricing memory instead -- a common real-world RAG bug where a
frequently-accessed memory entry outranks a fresher source document.

Run both, then:

    agent-devtools serve

and open the Diff tab to compare `good-run-1` vs `bad-run-1`. You should
see the exact retrieval rank flip, the context block swap, and a
"likely cause" callout pointing at the stale $19/mo value leaking into
the final answer.
"""

from agent_devtools import trace

MEMORY = {
    "pricing_summary": "The Pro plan costs $19/mo.",
}
DOCS = {
    "july_pricing_update": "Effective July 1st, the Pro plan price changed to $29/mo.",
}

USER_QUESTION = "What's the current price of the Pro plan?"


def retrieve(query):
    """Toy retriever. In the good run, the current pricing doc outranks
    the older memory summary, as it should.

    Each result records an explicit ``outcome`` so the Retrieval tab can show
    the selection/rejection decision directly (Phase 3)."""
    return [
        {
            "id": "july_pricing_update",
            "content": DOCS["july_pricing_update"],
            "source": "doc",
            "score": 0.91,
            "rerank_score": 0.85,
            "rank": 1,
            "selected": True,
            "outcome": "selected",
        },
        {
            "id": "pricing_summary",
            "content": MEMORY["pricing_summary"],
            "source": "memory",
            "score": 0.52,
            "rerank_score": 0.30,
            "rank": 2,
            "selected": False,
            "outcome": "rejected_threshold",
        },
    ]


def fake_model_call(context_text):
    """Stand-in for a real LLM call. Just reflects whatever context it was
    given, the way a well-grounded agent would -- this keeps the example
    deterministic and legible without needing an API key."""
    if "$29/mo" in context_text:
        return "The Pro plan currently costs $29/mo."
    return "The Pro plan currently costs $19/mo."


def run_agent(run_id):
    with trace.run("refund-agent", run_id=run_id,
                   metadata={"scope": {"tenant_id": "acme", "user_id": "u-123"}}) as run:
        run.input(USER_QUESTION)

        results = retrieve(USER_QUESTION)
        run.retrieval(
            query=USER_QUESTION,
            results=results,
            rewritten_query="current Pro plan price",
            filters={"source": ["doc", "memory"]},
            embedding_model="text-embedding-3-small",
            threshold=0.80,
            rerank_threshold=0.50,
        )

        selected = next(r for r in results if r["selected"])
        run.context_block(source=selected["source"], key=selected["id"],
                           content=selected["content"], order=0)

        system = "You are a helpful, accurate billing support agent."
        messages = [{"role": "user", "content": USER_QUESTION}]
        run.prompt(system=system, messages=messages, context=[selected["id"]])

        answer = fake_model_call(selected["content"])
        run.output(answer)
        return answer


if __name__ == "__main__":
    answer = run_agent("good-run-1")
    print(f"[good-run-1] {answer}")
