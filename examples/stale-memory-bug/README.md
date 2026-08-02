# Example: the stale-memory bug

This is the "debug this in 60 seconds" example. Same agent, same user
question, run twice. One run answers correctly; the other quotes a
stale price -- because retrieval ranked an old memory entry above a
newer source document.

## Run it

```bash
cd examples/stale-memory-bug
python good_run.py
python bad_run.py
agent-devtools serve
```

Open the URL it prints (defaults to `http://127.0.0.1:4173`), select
**Diff** in the tab strip, and compare `good-run-1` vs `bad-run-1`.

You should see:

- a rank flip in **Retrieval**: the stale memory jumps from #2 to #1;
- a swap in **Context**: the July pricing doc is no longer injected,
  the stale memory summary is injected instead;
- a **likely cause** callout pointing out that the bad run's answer
  repeats the stale $19/mo value.

That's the whole pitch: instrument two runs, get a plain-language
explanation of why they diverged, instead of diffing two JSON blobs by
hand.
