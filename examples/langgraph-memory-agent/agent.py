"""
Atlas -- a LangGraph billing-support agent (production-style, with a bug).

This is the "production" code you would be debugging. It is a real
``StateGraph`` with:

  - multiple nodes        (classify, retrieve, amend_memory, generate, verify)
  - conditional routing   (classify and generate both route conditionally)
  - state updates         (LangGraph ``add_messages`` reducer + node returns)
  - a retriever           (source documents + user memories)
  - a tool                (get_current_plan_price / lookup_order)
  - a memory store        (persists across sessions, like a user-profile cache)

There is ONE intentional bug, and it is a classic one: *stale memory*.

  1. The retriever boosts memory candidates above source documents
     (a "frequency" heuristic that over-trusts user memory).
  2. The ``amend_memory`` node "refreshes" whatever price it already holds
     back into memory without validating it against the source doc.

So when a stale price (``$19/mo``, cached before July 1st) already exists in
memory, the agent retrieves it first, re-commits it, and confidently quotes it
-- even though the pricing doc (and the verification tool) say ``$29/mo``.

Run it with ``run_session.py``; the graph is fully deterministic (no API key),
so every run is a reproducible event timeline in Agent DevTools.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Annotated, Any, Optional, TypedDict

# Make the SDK importable when running from the examples dir.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "packages", "python-sdk"))

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from agent_devtools.trace import Run

# ---------------------------------------------------------------------------
# Knowledge base -- the source of truth documents.
# ---------------------------------------------------------------------------

DOCS: dict[str, Document] = {
    "july_pricing_update": Document(
        page_content="Effective July 1st, the Pro plan price changed to $29/mo.",
        metadata={
            "source": "pricing_doc",
            "id": "july_pricing_update",
            "updated": "2026-07-01",
        },
    ),
    "refund_policy": Document(
        page_content="Customers may request one refund per year within 30 days of purchase.",
        metadata={"source": "policy_doc", "id": "refund_policy"},
    ),
    "order_help": Document(
        page_content="You can track an order by its order ID; statuses include 'shipped' and 'processing'.",
        metadata={"source": "help_doc", "id": "order_help"},
    ),
}

# ---------------------------------------------------------------------------
# Persistent memory store -- normally a vector DB of user memories.
# ---------------------------------------------------------------------------

# A long-lived per-user profile. NOTE: `plan_price` is STALE -- it was cached
# before the July 1st price change and never invalidated.
SAVED_MEMORY: dict[str, str] = {
    "user_plan": "Pro",
    "plan_price": "$19/mo",
}

# ---------------------------------------------------------------------------
# Tools -- the authoritative systems the agent can call.
# ---------------------------------------------------------------------------


@tool
def get_current_plan_price(plan: str) -> str:
    """Authoritative current price for a plan. Source of truth."""
    prices = {"Pro": "$29/mo", "Starter": "$9/mo", "Enterprise": "$99/mo"}
    return prices.get(plan, "unknown")


@tool
def lookup_order(order_id: str) -> str:
    """Look up the status of an order by its ID."""
    statuses = {"A-123": "shipped", "B-456": "processing"}
    return f"Order {order_id} is {statuses.get(order_id, 'unknown')}."


# ---------------------------------------------------------------------------
# Retriever -- combines source docs with user memories, then ranks them.
# ---------------------------------------------------------------------------


class MemoryRetriever:
    """Deterministic retriever over a small knowledge base + a memory store.

    THE BUG lives here (and in ``amend_memory``): the retriever boosts memory
    candidates with a frequency heuristic and, when a memory match exists,
    depresses the source-document scores. A frequently-accessed stale memory
    therefore outranks a fresher, more authoritative document.
    """

    THRESHOLD = 0.80
    RERANK_THRESHOLD = 0.50

    # Memory candidates get a flat boost; docs get depressed when a memory
    # match exists. These are the "embedding + reranker" numbers.
    MEMORY_SCORE = 0.88
    MEMORY_RERANK = 0.78
    DOC_SCORE = 0.91
    DOC_RERANK = 0.85
    DOC_DEPRESSED_SCORE = 0.60
    DOC_DEPRESSED_RERANK = 0.45

    def __init__(self, memory: dict[str, str]):
        self._memory = memory

    def _memory_candidates(self, intent: str) -> list[dict]:
        """User memories relevant to this intent."""
        keys_by_intent = {
            "pricing": [("plan_price", self._memory.get("plan_price"))],
            "refund": [],
            "order": [],
            "general": [],
        }
        out = []
        for key, value in keys_by_intent.get(intent, []):
            if value is None:
                continue
            label = key.replace("_", " ")
            out.append({
                "id": f"memory:{key}",
                "content": f"The user's {label} is {value}.",
                "source": "memory",
                "base_score": self.MEMORY_SCORE,
                "base_rerank": self.MEMORY_RERANK,
            })
        return out

    def _doc_candidates(self, intent: str) -> list[dict]:
        """Source documents relevant to this intent."""
        doc_ids_by_intent = {
            "pricing": ["july_pricing_update"],
            "refund": ["refund_policy"],
            "order": ["order_help"],
            "general": [],
        }
        out = []
        for doc_id in doc_ids_by_intent.get(intent, []):
            doc = DOCS[doc_id]
            out.append({
                "id": doc_id,
                "content": doc.page_content,
                "source": "doc",
                "base_score": self.DOC_SCORE,
                "base_rerank": self.DOC_RERANK,
            })
        return out

    def retrieve(self, query: str, intent: str) -> list[dict]:
        memory_cands = self._memory_candidates(intent)
        doc_cands = self._doc_candidates(intent)

        # THE BUG: when a memory candidate exists, boost it AND depress the
        # source docs. In production this is a hybrid ranking that over-trusts
        # frequently-accessed user memory.
        for c in memory_cands:
            c["score"] = c["base_score"]
            c["rerank_score"] = c["base_rerank"]
        for c in doc_cands:
            if memory_cands:
                c["score"] = self.DOC_DEPRESSED_SCORE
                c["rerank_score"] = self.DOC_DEPRESSED_RERANK
            else:
                c["score"] = c["base_score"]
                c["rerank_score"] = c["base_rerank"]

        candidates = memory_cands + doc_cands
        candidates.sort(key=lambda c: c["score"], reverse=True)
        for i, c in enumerate(candidates, start=1):
            c["rank"] = i
            c["selected"] = (
                c["score"] >= self.THRESHOLD and c["rerank_score"] >= self.RERANK_THRESHOLD
            )
        return candidates


# ---------------------------------------------------------------------------
# Deterministic "model" -- stands in for a real LLM so the run is replayable
# without an API key. It reflects the context it is given, the way a
# well-grounded agent should.
# ---------------------------------------------------------------------------


def generate_answer(context_text: str, query: str) -> str:
    if "$29/mo" in context_text:
        return "Your Pro plan costs $29/mo as of July 1st."
    if "$19/mo" in context_text:
        return "Your Pro plan costs $19/mo."
    return "I've noted your request and will help you with that."


def extract_price(text: str) -> str:
    m = re.search(r"\$\d[\d,]*/mo", text)
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# Graph state (LangGraph) -- demonstrates state updates via reducers.
# ---------------------------------------------------------------------------


class AgentState(TypedDict):
    """The shared graph state. ``messages`` uses LangGraph's ``add_messages``
    reducer, so every node that returns messages appends to the conversation."""

    query: str
    messages: Annotated[list, add_messages]
    intent: str
    retrieved: list
    memory_keys: list
    answer: str


# ---------------------------------------------------------------------------
# Graph builder.
# ---------------------------------------------------------------------------


def build_atlas_graph(run: Optional[Run] = None, memory: Optional[dict] = None):
    """Build (and compile) the Atlas graph.

    ``run`` is an open agent-devtools ``Run`` handle; every node logs rich
    events (retrieval, memory, context, prompt, tool, state) into it so the
    run shows up in Agent DevTools. ``memory`` seeds the persistent store.
    """
    memory = dict(memory or {})
    retriever = MemoryRetriever(memory)

    # -- node: classify ---------------------------------------------------
    def classify(state: AgentState) -> dict:
        q = state["query"].lower()
        if any(w in q for w in ("price", "cost", "how much", "plan")):
            intent = "pricing"
        elif any(w in q for w in ("refund", "return", "chargeback")):
            intent = "refund"
        elif any(w in q for w in ("order", "ship", "track", "status")):
            intent = "order"
        else:
            intent = "general"
        if run:
            run.state_snapshot({"node": "classify", "query": state["query"], "intent": intent})
        return {"intent": intent}

    # -- node: retrieve ---------------------------------------------------
    def retrieve_node(state: AgentState) -> dict:
        query = state["query"]
        intent = state["intent"]
        results = retriever.retrieve(query, intent)
        if run:
            # Rich payload so the Retrieval Explanation tab can explain WHY
            # each candidate was selected or rejected.
            run.retrieval(
                query=query,
                results=results,
                rewritten_query=f"{intent} | {query}",
                filters={"source": ["memory", "doc"]},
                embedding_model="text-embedding-3-small",
                threshold=MemoryRetriever.THRESHOLD,
                rerank_threshold=MemoryRetriever.RERANK_THRESHOLD,
                intent=intent,
            )
            run.state_snapshot({"node": "retrieve", "candidates": len(results)})
        return {"retrieved": results}

    # -- node: amend_memory ------------------------------------------------
    def amend_memory(state: AgentState) -> dict:
        results = state["retrieved"]
        selected = [r for r in results if r["selected"]]
        if run:
            for r in selected:
                if r["source"] == "memory":
                    run.memory_read(key=r["id"], value=r["content"])
            run.state_snapshot({"node": "amend_memory", "selected": [r["id"] for r in selected]})

        # If we don't hold a price yet, learn it from the freshest source doc
        # we retrieved. Otherwise THE BUG: refresh whatever we already hold
        # back into memory without validating against the source.
        if "plan_price" not in memory:
            for r in results:
                if r["source"] == "doc" and r["selected"]:
                    learned = extract_price(r["content"])
                    if learned:
                        memory["plan_price"] = learned
                        if run:
                            run.memory_write("plan_price", learned, source="doc")
                        break
        else:
            if run:
                run.memory_write(
                    "plan_price", memory["plan_price"], source="memory_refresh"
                )
        return {"memory_keys": list(memory.keys())}

    # -- node: generate ----------------------------------------------------
    def generate_node(state: AgentState) -> dict:
        query = state["query"]
        results = state["retrieved"]
        selected = [r for r in results if r["selected"]]
        context_text = "\n\n".join(r["content"] for r in selected)

        system = "You are Atlas, a precise billing support agent. Answer using only the provided context."
        messages = [{"role": "user", "content": query}]

        if run:
            run.context_block(source="system_policy", key="system", content=system, order=0)
            for r in selected:
                run.context_block(
                    source=r["source"], key=r["id"], content=r["content"], order=r["rank"]
                )
            run.prompt(
                system=system,
                messages=messages,
                context=["system"] + [r["id"] for r in selected],
            )

        answer = generate_answer(context_text, query)
        if run:
            run.output(answer)
            run.state_snapshot({"node": "generate", "answer": answer})

        # LangGraph state update: append the exchange to the conversation.
        return {
            "answer": answer,
            "messages": [HumanMessage(content=query), AIMessage(content=answer)],
        }

    # -- node: verify ------------------------------------------------------
    def verify_node(state: AgentState) -> dict:
        intent = state["intent"]
        if run:
            run.state_snapshot({"node": "verify", "intent": intent})
        if intent == "pricing":
            name, args = "get_current_plan_price", {"plan": "Pro"}
            result = get_current_plan_price.invoke(args)
        elif intent == "order":
            name, args = "lookup_order", {"order_id": "A-123"}
            result = lookup_order.invoke(args)
        else:
            return {}
        if run:
            # The verification tool returns the authoritative $29/mo, but the
            # graph never cross-checks it against the generated answer -- the
            # stale $19/mo answer is returned anyway. (See README.)
            run.tool_call(name=name, args=args, result=result)
        return {}

    # -- conditional routers ----------------------------------------------
    def route_after_classify(state: AgentState) -> str:
        return "retrieve" if state["intent"] in ("pricing", "refund", "order") else "generate"

    def route_after_generate(state: AgentState) -> str:
        return "verify" if state["intent"] in ("pricing", "order") else END

    # -- assemble the graph ------------------------------------------------
    g = StateGraph(AgentState)
    g.add_node("classify", classify)
    g.add_node("retrieve", retrieve_node)
    g.add_node("amend_memory", amend_memory)
    g.add_node("generate", generate_node)
    g.add_node("verify", verify_node)

    g.add_edge(START, "classify")
    g.add_conditional_edges(
        "classify",
        route_after_classify,
        {"retrieve": "retrieve", "generate": "generate"},
    )
    g.add_edge("retrieve", "amend_memory")
    g.add_edge("amend_memory", "generate")
    g.add_conditional_edges(
        "generate",
        route_after_generate,
        {"verify": "verify", END: END},
    )
    g.add_edge("verify", END)

    return g.compile()