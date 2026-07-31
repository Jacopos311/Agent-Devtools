"""Esempio di integrazione con OpenAI Agents SDK."""

import sys
sys.path.insert(0, "packages/python-sdk")

from agents import Agent, Runner
from agent_devtools import run
from agent_devtools.integrations.openai_agents import trace_openai_agent


def main():
    # Crea un agente OpenAI
    agent = Agent(
        name="Refund Assistant",
        instructions="You help users with refund requests. "
                    "Be helpful and provide clear answers.",
    )

    # Esegui con tracing
    with run(project_name="OpenAI Agent Demo"):
        result = trace_openai_agent(
            agent, 
            "Can I get a refund for my order #12345?"
        )
        print("✅ OpenAI Agent eseguito con successo!")
        print(f"Risultato: {result.final_output}")

if __name__ == "__main__":
    main()