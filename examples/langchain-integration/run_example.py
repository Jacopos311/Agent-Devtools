"""
LangChain integration example.

Builds a small LangChain chain (retriever -> prompt -> fake chat model ->
tool) and runs it with the ``LangChainTraceHandler`` attached, so every
LangChain callback event is recorded into the agent-devtools SQLite store.

Run from this directory:

    python run_example.py

Then start the debug server:

    agent-devtools serve

and open http://127.0.0.1:4173 to see the run in the Replay / Prompt /
Retrieval / Tools tabs.
"""

from __future__ import annotations

import os
import sys

# Make sure the SDK is importable when running from the examples dir.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "packages", "python-sdk"))

from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from langchain_core.tools import tool

from agent_devtools import trace
from agent_devtools.adapters import LangChainTraceHandler

# ---------------------------------------------------------------------------
# A tiny in-memory "knowledge base" so the example is self-contained.
# ---------------------------------------------------------------------------

DOCS = [
    Document(
        page_content="The Pro plan costs $29/mo as of July 1st.",
        metadata={"source": "pricing_doc", "id": "july_pricing_update"},
    ),
    Document(
        page_content="The Pro plan includes unlimited API calls.",
        metadata={"source": "pricing_doc", "id": "pro_features"},
    ),
]


class SimpleRetriever(BaseRetriever):
    """A toy retriever that returns docs matching the query."""

    def _get_relevant_documents(self, query: str, *, run_manager=None) -> list[Document]:
        return [d for d in DOCS if any(w in d.page_content.lower() for w in query.lower().split())]


@tool
def lookup_order(order_id: str) -> str:
    """Look up the status of an order by its ID."""
    return f"Order {order_id} is shipped."


# ---------------------------------------------------------------------------
# Build the chain.
# ---------------------------------------------------------------------------

retriever = SimpleRetriever()

# A fake chat model that returns canned responses (no API key needed).
model = FakeListChatModel(responses=["The Pro plan costs $29/mo as of July 1st."])

# Format retrieved docs into a prompt.
def format_docs(docs: list[Document]) -> str:
    return "\n\n".join(d.page_content for d in docs)


def build_chain():
    """Return a LangChain runnable that exercises retriever, prompt, model,
    and tool callbacks."""
    # Step 1: assemble a prompt from the retrieved docs
    def make_messages(inputs: dict) -> list:
        docs = inputs["docs"]
        return [
            SystemMessage(content="You are a helpful billing assistant."),
            HumanMessage(content=f"Context:\n{format_docs(docs)}\n\nQuestion: {inputs['question']}"),
        ]

    # Step 2: call the model
    def call_model(messages: list) -> str:
        return model.invoke(messages).content

    # Step 3: call a tool
    def use_tool(answer: str) -> str:
        order = lookup_order.invoke({"order_id": "A-123"})
        return f"{answer}\n{order}"

    chain = (
        RunnablePassthrough.assign(docs=lambda x: retriever.invoke(x["question"]))
        | RunnableLambda(make_messages)
        | RunnableLambda(call_model)
        | RunnableLambda(use_tool)
    )
    return chain


# ---------------------------------------------------------------------------
# Run it with the trace handler attached.
# ---------------------------------------------------------------------------

def main() -> None:
    chain = build_chain()
    question = "What does the Pro plan cost?"

    # Option A: attach to an existing trace.run(...) block.
    with trace.run("langchain-agent", run_id="langchain-example-1") as run:
        handler = LangChainTraceHandler(run=run)
        result = chain.invoke(
            {"question": question},
            config={"callbacks": [handler]},
        )
        print(f"Result: {result}")

    # Option B: let the handler create and finish its own run.
    handler = LangChainTraceHandler(agent_name="langchain-agent", run_id="langchain-example-2")
    result = chain.invoke(
        {"question": question},
        config={"callbacks": [handler]},
    )
    print(f"Result (standalone): {result}")

    print("\nDone. Start the debugger with:  agent-devtools serve")


if __name__ == "__main__":
    main()