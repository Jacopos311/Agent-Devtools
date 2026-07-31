"""Assertion engine for testing."""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import json


class AssertionResult(BaseModel):
    name: str
    passed: bool
    message: str
    details: Optional[Dict] = None


class TestResult(BaseModel):
    name: str
    passed: bool
    message: Optional[str] = None
    assertions: List[AssertionResult] = []


class AssertionEngine:
    @staticmethod
    def event_present(events: List[Dict], event_type: str, payload_match: Optional[Dict] = None) -> AssertionResult:
        for event in events:
            if event["event_type"] == event_type:
                if payload_match:
                    payload = json.loads(event["payload"]) if isinstance(event["payload"], str) else event["payload"]
                    matches = all(payload.get(k) == v for k, v in payload_match.items())
                    if matches:
                        return AssertionResult(
                            name=f"Event '{event_type}' present",
                            passed=True,
                            message=f"Found event of type {event_type} with matching payload"
                        )
                else:
                    return AssertionResult(
                        name=f"Event '{event_type}' present",
                        passed=True,
                        message=f"Found event of type {event_type}"
                    )
        return AssertionResult(
            name=f"Event '{event_type}' present",
            passed=False,
            message=f"No event of type {event_type} found"
        )

    @staticmethod
    def event_absent(events: List[Dict], event_type: str, payload_match: Optional[Dict] = None) -> AssertionResult:
        for event in events:
            if event["event_type"] == event_type:
                if payload_match:
                    payload = json.loads(event["payload"]) if isinstance(event["payload"], str) else event["payload"]
                    matches = all(payload.get(k) == v for k, v in payload_match.items())
                    if matches:
                        return AssertionResult(
                            name=f"Event '{event_type}' absent",
                            passed=False,
                            message=f"Found forbidden event of type {event_type} with matching payload"
                        )
                else:
                    return AssertionResult(
                        name=f"Event '{event_type}' absent",
                        passed=False,
                        message=f"Found forbidden event of type {event_type}"
                    )
        return AssertionResult(
            name=f"Event '{event_type}' absent",
            passed=True,
            message=f"No event of type {event_type} found"
        )

    @staticmethod
    def context_block_present(events: List[Dict], block_name: str, contains: Optional[str] = None) -> AssertionResult:
        for event in events:
            if event["event_type"] == "context.injected":
                payload = json.loads(event["payload"]) if isinstance(event["payload"], str) else event["payload"]
                blocks = payload.get("blocks", [])
                for block in blocks:
                    if block.get("name") == block_name:
                        if contains:
                            content = block.get("content", "")
                            if contains in content:
                                return AssertionResult(
                                    name=f"Context block '{block_name}' present",
                                    passed=True,
                                    message=f"Found block with content containing '{contains}'"
                                )
                        else:
                            return AssertionResult(
                                name=f"Context block '{block_name}' present",
                                passed=True,
                                message=f"Found block with name '{block_name}'"
                            )
        return AssertionResult(
            name=f"Context block '{block_name}' present",
            passed=False,
            message=f"Context block '{block_name}' not found"
        )

    @staticmethod
    def prompt_contains(events: List[Dict], text: str) -> AssertionResult:
        for event in events:
            if event["event_type"] == "prompt.assembled":
                payload = json.loads(event["payload"]) if isinstance(event["payload"], str) else event["payload"]
                prompt_text = payload.get("text", "")
                if text in prompt_text:
                    return AssertionResult(
                        name=f"Prompt contains '{text}'",
                        passed=True,
                        message=f"Found '{text}' in prompt"
                    )
        return AssertionResult(
            name=f"Prompt contains '{text}'",
            passed=False,
            message=f"'{text}' not found in any prompt"
        )

    @staticmethod
    def tool_called(events: List[Dict], tool_name: str) -> AssertionResult:
        return AssertionEngine.event_present(
            events, "tool.called", {"name": tool_name}
        )

    @staticmethod
    def tool_not_called(events: List[Dict], tool_name: str) -> AssertionResult:
        return AssertionEngine.event_absent(
            events, "tool.called", {"name": tool_name}
        )


def run_assertions(events: List[Dict], assertions: List[Dict]) -> List[AssertionResult]:
    """Run a list of assertion definitions."""
    results = []
    for assertion in assertions:
        assert_type = assertion.get("type")
        if assert_type == "event_present":
            result = AssertionEngine.event_present(
                events,
                assertion["event_type"],
                assertion.get("payload_match")
            )
        elif assert_type == "event_absent":
            result = AssertionEngine.event_absent(
                events,
                assertion["event_type"],
                assertion.get("payload_match")
            )
        elif assert_type == "context_block_present":
            result = AssertionEngine.context_block_present(
                events,
                assertion["block_name"],
                assertion.get("contains")
            )
        elif assert_type == "prompt_contains":
            result = AssertionEngine.prompt_contains(
                events,
                assertion["text"]
            )
        elif assert_type == "tool_called":
            result = AssertionEngine.tool_called(
                events,
                assertion["tool_name"]
            )
        elif assert_type == "tool_not_called":
            result = AssertionEngine.tool_not_called(
                events,
                assertion["tool_name"]
            )
        else:
            result = AssertionResult(
                name=f"Unknown assertion type: {assert_type}",
                passed=False,
                message=f"Unsupported assertion type '{assert_type}'"
            )
        results.append(result)
    return results