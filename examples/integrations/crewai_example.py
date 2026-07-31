"""Esempio di integrazione con CrewAI."""

import sys
sys.path.insert(0, "packages/python-sdk")

from crewai import Agent, Task, Crew
from agent_devtools import run
from agent_devtools.integrations.crewai import trace_crew


def main():
    # Crea agenti e task
    refund_agent = Agent(
        role="Refund Specialist",
        goal="Process refund requests accurately",
        backstory="You are an expert in processing refunds."
    )

    refund_task = Task(
        description="Process refund for order #12345",
        expected_output="Refund approval status",
        agent=refund_agent
    )

    crew = Crew(
        agents=[refund_agent],
        tasks=[refund_task],
        verbose=True
    )

    # Esegui con tracing
    with run(project_name="CrewAI Demo"):
        result = trace_crew(crew, inputs={"order": "12345"})
        print("✅ CrewAI eseguito con successo!")
        print(f"Risultato: {result}")

if __name__ == "__main__":
    main()