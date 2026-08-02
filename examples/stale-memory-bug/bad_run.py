"""
See good_run.py for the full scenario. This is the same agent, same
question -- but the retriever ranks a stale memory entry above the
current pricing document, so the agent quotes an out-of-date price.
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
    """Toy retriever. Here the stale memory entry -- accessed often,
    scored on frequency rather than freshness -- outranks the current doc.
    This is the bug: same question, worse retrieval."""
    return [
        {"id": "pricing_summary", "content": MEMORY["pricing_summary"],
         "source": "memory", "score": 0.88, "rank": 1, "selected": True},
        {"id": "july_pricing_update", "content": DOCS["july_pricing_update"],
         "source": "doc", "score": 0.60, "rank": 2, "selected": False},
    ]


def fake_model_call(context_text):
    if "$29/mo" in context_text:
        return "The Pro plan currently costs $29/mo."
    return "The Pro plan currently costs $19/mo."


def run_agent(run_id):
    with trace.run("refund-agent", run_id=run_id) as run:
        run.input(USER_QUESTION)

        results = retrieve(USER_QUESTION)
        run.retrieval(query=USER_QUESTION, results=results)

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
    answer = run_agent("bad-run-1")
    print(f"[bad-run-1] {answer}")
