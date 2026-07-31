import sys
sys.path.insert(0, "packages/python-sdk")

from agent_devtools import run, EventType

def emit(event_type, payload):
    from agent_devtools import get_current_run_id
    from agent_devtools.transport import Transport
    from agent_devtools.events import Event
    run_id = get_current_run_id()
    if run_id:
        event = Event(run_id=run_id, event_type=event_type, payload=payload)
        Transport().write_event(event)

def main():
    with run(project_name="simple_agent"):
        print("Starting agent...")
        # Simulate retrieval
        emit("retrieval.started", {"query": "What is the refund policy?"})
        emit("retrieval.result", {
            "documents": [
                {"id": "doc1", "content": "Refund policy: 30 days"},
                {"id": "doc2", "content": "Return policy: 14 days"}
            ],
            "scores": [0.95, 0.78]
        })
        
        # Simulate context injection
        emit("context.injected", {
            "blocks": [
                {"name": "Policy", "content": "Refund policy: 30 days"},
                {"name": "User", "content": "Can I return this?"}
            ]
        })
        
        # Simulate prompt assembly
        emit("prompt.assembled", {
            "text": "Based on the policy, you can return items within 30 days."
        })
        
        # Simulate model response
        emit("model.response", {
            "text": "You are eligible for a refund."
        })
        
        # Simulate tool call
        emit("tool.called", {"name": "refund_eligibility", "arguments": {"user": "123"}})
        emit("tool.result", {"output": "Eligible"})
        
        print("Agent finished successfully!")

if __name__ == "__main__":
    main()