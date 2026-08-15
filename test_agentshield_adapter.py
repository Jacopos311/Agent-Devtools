"""Tests for the AgentShield adapter (agent_devtools.adapters.agentshield).

Covers the robustness contract from the cross-stack E2E verification:
  1. dict and JSON-string events parse into the store
  2. missing trace_id falls back to "unattributed" instead of raising
  3. the run row is auto-created so events are visible in list_runs
  4. the callback plugs directly into SpendEvaluationEmitter.emit(on_event=...)
  5. NDJSON ingestion skips malformed lines instead of aborting
"""
import json
import os
import tempfile
import unittest

from agent_devtools import TraceStore
from agent_devtools.adapters.agentshield import (
    ingest_ndjson_file,
    make_agentshield_callback,
    parse_agentshield_event,
)


def _event(trace_id="trace_42", **kw):
    ev = {
        "schema_version": "1.0",
        "event_type": "agentshield.spend.evaluation",
        "event_id": "evt-1",
        "timestamp": "2026-08-13T15:00:00+00:00",
        "trace_id": trace_id,
        "agent_id": "agent-A",
        "session_id": "sess-1",
        "transaction": {"amount": "500.00", "merchant": "openai-api",
                        "category": "llm_inference"},
        "decision": {"decision": "BLOCKED", "reason": "limit exceeded",
                     "rule_triggered": "r1", "severity": "high"},
        "evaluation": [{"rule_id": "r1", "type": "transaction_limit",
                        "priority": 1, "outcome": "triggered",
                        "detail": {"actual": "500.00", "limit": "250.00"}}],
    }
    ev.update(kw)
    return ev


class TestAgentShieldAdapter(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = TraceStore(db_path=os.path.join(self.tmp, "trace.db"))

    def test_parse_dict_event_logs_and_autocreates_run(self):
        run_id = parse_agentshield_event(self.store, _event())
        self.assertEqual(run_id, "trace_42")
        self.assertIsNotNone(self.store.get_run("trace_42"))
        evs = self.store.get_events("trace_42", "agentshield.spend.evaluation")
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0].payload["decision"]["decision"], "BLOCKED")
        self.assertEqual(evs[0].payload["evaluation"][0]["outcome"], "triggered")

    def test_parse_json_string_event(self):
        parse_agentshield_event(self.store, json.dumps(_event()))
        self.assertEqual(len(self.store.get_events("trace_42")), 1)

    def test_missing_trace_id_falls_back_instead_of_raising(self):
        run_id = parse_agentshield_event(self.store, _event(trace_id=None))
        self.assertEqual(run_id, "unattributed")
        self.assertIsNotNone(self.store.get_run("unattributed"))
        self.assertEqual(len(self.store.get_events("unattributed")), 1)

    def test_second_event_keeps_seq_order_after_autocreate(self):
        parse_agentshield_event(self.store, _event(event_id="evt-1"))
        parse_agentshield_event(self.store, _event(event_id="evt-2"))
        seqs = [e.seq for e in self.store.get_events("trace_42")]
        self.assertEqual(seqs, [0, 1])

    def test_callback_plugs_into_emitter(self):
        try:
            from agentshield import SpendControlEngine, SpendEvaluationEmitter
        except ImportError:
            self.skipTest("agentshield not installed")
        cb = make_agentshield_callback(self.store)
        emitter = SpendEvaluationEmitter(SpendControlEngine())
        rules = [{"id": "r1", "type": "transaction_limit", "priority": 1,
                  "params": {"max_amount": "250.00"}, "action": "BLOCK"}]
        emitter.emit({"amount": "500.00", "merchant": "openai-api",
                      "category": "llm_inference"}, rules,
                     trace_id="cb_run", on_event=cb)
        evs = self.store.get_events("cb_run", "agentshield.spend.evaluation")
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0].payload["decision"]["decision"], "BLOCKED")

    def test_ingest_skips_malformed_lines_and_continues(self):
        path = os.path.join(self.tmp, "ev.ndjson")
        with open(path, "w") as f:
            f.write(json.dumps(_event(trace_id="t1")) + "\n")
            f.write("{broken json\n")
            f.write("\n")  # blank line tolerance
            f.write(json.dumps(_event(trace_id="t2")) + "\n")
        n = ingest_ndjson_file(self.store, path)
        self.assertEqual(n, 2)
        self.assertEqual(len(self.store.get_events("t1")), 1)
        self.assertEqual(len(self.store.get_events("t2")), 1)

    def test_ingest_null_trace_id_line_does_not_abort(self):
        path = os.path.join(self.tmp, "nulltrace.ndjson")
        with open(path, "w") as f:
            f.write(json.dumps(_event(trace_id=None)) + "\n")
            f.write(json.dumps(_event(trace_id="t9")) + "\n")
        n = ingest_ndjson_file(self.store, path)
        self.assertEqual(n, 2)
        self.assertEqual(len(self.store.get_events("unattributed")), 1)
        self.assertEqual(len(self.store.get_events("t9")), 1)

    def test_ingest_empty_file_returns_zero(self):
        path = os.path.join(self.tmp, "empty.ndjson")
        open(path, "w").close()
        self.assertEqual(ingest_ndjson_file(self.store, path), 0)


if __name__ == "__main__":
    unittest.main()
