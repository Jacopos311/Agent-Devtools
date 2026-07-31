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

def simulate_agent(use_stale_memory=False):
    # Simulate an agent that may use stale memory
    with run(project_name="refund_agent"):
        # User input
        emit("user.input", {"text": "Can I get a refund for my order?"})
        
        # Retrieval
        emit("retrieval.started", {"query": "refund policy 2026"})
        current_policy = "Refund policy: 30 days from purchase"
        emit("retrieval.result", {
            "documents": [{"id": "policy_2026", "content": current_policy}],
            "scores": [0.98]
        })
        
        # Memory read - simulate stale memory bug
        if use_stale_memory:
            memory_content = "Refund policy: 14 days from purchase"
        else:
            memory_content = current_policy
        
        emit("memory.read", {
            "key": "refund_policy",
            "value": memory_content
        })
        
        # Context injection (may contain stale content)
        emit("context.injected", {
            "blocks": [
                {"name": "Policy", "content": memory_content},
                {"name": "User", "content": "Order #12345"}
            ]
        })
        
        # Prompt assembly
        prompt_text = f"Based on the policy, the user is asking about a refund."
        if "14 days" in memory_content:
            prompt_text += " The policy states 14 days. (STALE)"
        else:
            prompt_text += " The policy states 30 days. (CURRENT)"
        
        emit("prompt.assembled", {"text": prompt_text})
        
        # Model response
        if use_stale_memory:
            response = "Based on our policy (14 days), I'm sorry but you are not eligible for a refund."
        else:
            response = "Based on our policy (30 days), you are eligible for a refund."
        
        emit("model.response", {"text": response})
        
        # Tool call
        eligibility = "not eligible" if use_stale_memory else "eligible"
        emit("tool.called", {"name": "refund_approval", "arguments": {"order": "12345"}})
        emit("tool.result", {"output": eligibility})