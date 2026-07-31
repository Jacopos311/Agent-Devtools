"""Esempio di integrazione con LangGraph."""

import sys
sys.path.insert(0, "packages/python-sdk")

from typing import TypedDict, Literal
from langgraph.graph import StateGraph, END
from agent_devtools import run
from agent_devtools.integrations.langgraph import trace_langgraph


class AgentState(TypedDict):
    messages: list
    next: str


def node_agent(state: AgentState):
    """Nodo agente che decide il prossimo passo."""
    return {
        "messages": state["messages"] + ["Agent processing..."],
        "next": "tools" if len(state["messages"]) < 3 else "end"
    }


def node_tools(state: AgentState):
    """Nodo tools che esegue operazioni."""
    return {
        "messages": state["messages"] + ["Tool called: refund_check"],
        "next": "agent"
    }


def router(state: AgentState) -> Literal["tools", "end"]:
    """Router per decidere il prossimo nodo."""
    return state["next"]


def main():
    # Crea il grafo
    graph = StateGraph(AgentState)
    graph.add_node("agent", node_agent)
    graph.add_node("tools", node_tools)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", router, {"tools": "tools", "end": END})
    graph.add_edge("tools", "agent")
    
    compiled = graph.compile()

    # Esegui con tracing
    with run(project_name="LangGraph Demo"):
        initial_state = {
            "messages": ["User: Can I get a refund?"],
            "next": "agent"
        }
        result = trace_langgraph(compiled, initial_state)
        print("✅ LangGraph eseguito con successo!")
        print(f"Risultato: {result}")

if __name__ == "__main__":
    main()