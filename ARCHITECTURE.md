# ARCHITECTURE — Agent DevTools

> Documento di architettura per il repository `Agent-Devtools` (SDK v0.3.0,
> Python ≥ 3.9). Descrive **quale problema risolve nell'ecosistema degli
> agenti AI** e come lo fa, componendo le quattro aree richieste:
> Interception Layer, Tracing Engine, Replay Engine e Fault Injector
> (interpretato come *mock deterministico*). Tutti i riferimenti sono
> verificabili nel codice sorgente.

---

## 1. High-Level Overview — il problema architetturale

**Il problema.** Un agente AI genera un output inatteso. Le piattaforme di
osservabilità (Langfuse, Phoenix, Datadog) registrano *cosa è successo* in
termini aggregati ("latenza media", "tasso di errore") e producono tracciati
JSON frammentati. Mettere insieme **il prompt finale assemblato**, **la
provenienza di ogni blocco di contesto** (memoria, doc, risultato di tool),
**lo stato della memoria al momento della decisione** e **cosa è cambiato
tra un run "buono" e uno "cattivo"** richiede oggi: unire log, diffare a occhio
blob JSON e indovinare. Ciò è particolarmente vero per gli errori di
**memoria obsoleta**, **fuga di scope/cross-tenant** e **cattiva selezione di
retrieval**, che non si vedono in un'aggregata.

**La risposta architetturale di Agent DevTools.** È **Chrome DevTools per gli
agenti AI**: un debugger locale, *first-party*, che risponde a una domanda
strettamente operativa — *"Perché questo run ha prodotto questo output, e cosa
è diverso in quel run che non l'ha fatto?"*. La chiave esistenziale è un
**log eventi append-only** (`store.py`) in cui ogni evento è tipizzato e
ordinato da `seq`, e da cui **tutte le viste vengono derivate a tempo di
lettura** (`diff.py`, `explain.py`, `memory_view.py`, `scope.py`, `replay.py`).
Niente export, niente trasmissione di dati: il backend è un file SQLite
locale (`.agent_devtools/trace.db`, variabile d'ambiente `AGENT_DEVTOOLS_DB`)
e il server FastAPI (`server/main.py`) legge lo stesso file che l'SDK scrive.

Le due domande centrali che l'intera architettura è incentrata a rispondere:

1. **Qual è stata la catena causale di questo run?** (Replay / Prompt /
   Context / Memory / Tools — viste derivate dal log.)
2. **Qual è la divergenza rispetto a un run di riferimento?** (Behavior Diff
   con catene di evidenza e cause assegnate, in `diff.py`.)

## 2. Core Components

### 2.1 Interception Layer

È il punto di ingresso di tutti gli eventi. Non esiste un unico "interceptor"
centralizzato: l'intercettazione è **manuale ed esplicita** (prima) e
**basata su adapter di framework** (secondaria). L'intersezione comune a
entrambi i percorsi è `Run._log` in `trace.py:95-96`:

```python
def _log(self, event_type: str, payload: dict) -> None:
    self.store.log_event(self.run_id, event_type, redact(payload))
```

Osservazioni chiave:

- **Redazione a ingresso.** `redact(payload)` (`redaction.py`) maschera
  chiavi sensibili per nome (`api_key`, `token`, `password`, …) e forme note
  di token (`sk-…`, `pk-…`) *prima* della persistenza. È un courtesy, non un
  confine di sicurezza (vedi §4). Questo significa che *nessun* adapter o
  consumer di eventi deve pensare alla sanitizzazione: è un'invariante del
  Tracing Engine.
- **Percorso manuale** (`trace.py`, classe `Run`). Un metodo per ogni tipo
  di evento: `input`, `retrieval`, `context_block`, `prompt`, `tool_call`,
  `memory_read/write/update/delete`, `state_snapshot`, `output`,
  `assert_that`, e `log_event` come "escape hatch" per formati porta-
  tabili. È la via primaria perché cattura la cosa più importante che un
  tracciato generico perde: **il prompt finale assemblato con la
  provenienza di ogni blocco di contesto** (provenienza esplicita tramite
  `source` di `context_block`).
- **Adapter LangChain** (`adapters/langchain.py`, `LangChainTraceHandler`).
  È un `BaseCallbackHandler` che mappa i callback di LangChain
  (`on_llm_start→prompt.assembled`, `on_llm_end→model.response`,
  `on_tool_start/end→tool.call/result`, `on_retriever_start/end→
  retrieval.query/result`, `on_chain_start→user.input`) sugli stessi eventi
  tipizzati. Gestisce run autonomi quando non c'è un blocco `trace.run()`
  attivo.
- **Adapter Groq** (`adapters/groq.py`). `TracedGroq` *wrap* un
  `ChatGroq` e registra `invoke/ainvoke/batch/stream` → `prompt.assembled`
  + `model.response`; gestisce il lifecycle del run anche per invocazioni
  "nude" (senza blocco `debugger.run()`), tramite
  `debugger._current_run()` / `_start_run()` (`debugger.py`).
- **Adapter AgentShield** (`adapters/agentshield.py`). Non è un interceptor
  di chiamate LLM, ma un **consumatore di eventi di spesa/guardrail** in NDJSON
  che li registra nel medesimo log come `agentshield.spend.evaluation`,
  mappando `trace_id→run_id`. Rappresenta l'ingresso del concetto di
  "guardrail/fault esterno" nel log.

### 2.2 Tracing Engine

Costruito da tre moduli strettamente accoppiati:

- **`store.py` — `TraceStore`.** Wrapper thread-safe attorno a un'unica
  connessione SQLite. Lo schema (`SCHEMA`) ha tre tabelle: `runs` (metadati,
  status, `finished_at`), `events` (append-only, `seq` monotonico *per run*
  tramite `_seq_counters`, `ts` reale, `type`, `payload` JSON) e `replays`
  (report di replay persistiti). Fornisce `create_run`/`finish_run`
  (la chiusura nel `finally` di `trace.run()` stabilisce `ok`/`error`),
  `log_event`, lettori `get_events`/`get_events_by_types`/`get_run`/
  `list_runs`, `export_fixture`/`import_fixture` (formato portatile
  `agent-devtools/fixture@1`, `schemas/event.schema.json`) e la
  persistenza dei replay. Il path di default è risolto da `default_db_path()`,
  che onora `AGENT_DEVTOOLS_DB` e altrimenti "cammina" l'albero per trovare
  un DB esistente con almeno un run — cruciale perché l'SDK scrive e il
  server legge lo stesso file da directory diverse.
- **`trace.py` — entità di ingestione.** `trace.run()` (context manager)
  apre il `runs` row a `running`, `yield` un `Run`, e nel `finally` chiama
  `finish_run` con `ok` o `error` (se l'eccezione si propaga). `serve()` e
  `open_ui()` sono le entry zero-config verso il debugger.
- **`debugger.py` — `AgentDebugger`.** Orchestratore zero-config: possiede
  il `TraceStore`, avvia il server FastAPI in un thread demone
  (`_ensure_server_started`, riusa se la porta 4173 è già in uso) e apre
  il browser. Contiene una protezione d'usabilità decisamente non banale:
  `_warn_if_db_mismatch()` verifica via `GET /api/health` quale DB serve
  l'eventuale server già attivo e avverte allungamento se differisce da
  quello che l'SDK sta scrivendo (la causa #1 di "i miei run non
  appaiono nella UI").

Il modello di dati è **un log plano di eventi tipizzati**; non esiste uno
schema rigido di "run". Questo è il principio cardine di `docs/vision.md`:
"store raw debug events append-only, and derive all views on read", e
spiega perché nuovi campi (`usage`, `version`, `outcome`, `scope`) si
aggiungono senza migrazioni.

### 2.3 Replay Engine

`replay.py` — classe `ReplayEngine`, metodo pubblico `replay(run_id) ->
ReplayReport` (`replay.py:121`). È l'antidoto alla non-determinismo degli
agenti: **riesegue un run interamente dal log eventi, senza rete, senza LLM,
senza codice utente** (`replay.py:2-7`). Non "richiama nuovamente il grafo"
(come `examples/langgraph-memory-agent/verify_traces.py`); ricalcola da zero
le parti *stabilite* dal log e verifica che il log sia internamente
coerente. Il `ReplayReport` (`replay.py:68`) produce tre esiti:

| status | quando |
|---|---|
| `completed` | nessuna contraddizione: `summary` dice "determinically self-consistent". |
| `diverged` | almeno un evento contraddice (`evidence` con `severity:"divergence"`): `memory.update` con `old_value` diverso dallo stato ricostruito, `memory.read` che legge un valore mai scritto, retrieval con rank non monotone rispetto agli score o candidato rifiutato con score più alto di uno selezionato. |
| `failed` | `assertion.failed` registrata o `run.status=="error"`. |

Il metodo interno `_build_report` (`replay.py:131`) itera gli eventi in
ordine `seq` mantenendo uno stato di memoria fresco (`memory: dict`), una
lista di tool `pending_tools` (ogni `tool.call` deve chiudersi con
`tool.result`/`tool.error`), e accumula `evidence` con `kind`, `seq`,
`severity`, `expected`, `actual`. Il report viene **persisten** via
`store.save_replay` e restituito dall'API
`POST /api/runs/{run_id}/replay`, `GET .../replays`,
`GET .../replay/{replay_id}/report` (`server/main.py:188-215`).
Il motivo per cui è separato da un eventuale "framework replay" è che funziona
**su qualsiasi run registrata**, da UI o HTTP, senza codice utente.

### 2.4 Fault Injector (interpretazione: *mock deterministico*)

> **Nota sul naming.** Il termine "Fault Injector" **non corrisponde a alcun
> modulo/classe nel codice sorgente** (nessun `class FaultInjector`, nessun
> `fault_inject`). È stato cercato con `search_codebase` e non esiste. La
> componente che svolge nella pratica la *funzione* richiesta — "il tracciamento
> fino al mock deterministico" citato nel task — è il **Fault Injection /
> Deterministic Mock layer** composto da:

1. **Deterministic Replay come mock ripetibile** (`replay.py`). Poiché il
   replay riecoSagisce ogni evento *in isolamento*, con input fissi e
   senza toccare rete/LLM/codice, un `ReplayReport` funge da **mock
   deterministico** della run: date le stesse premesse, il comportamento
   osservato (memoria, retrieval, tool call) è riassemblabile
   all'identico. Questo è ciò che rende verificabile un bug ("è riproducibile
   offline?") e permette asserzioni di regressione.
2. **`agent-devtools test`** (`cli.py:_cmd_test`). È l'analogo da CI del
   "fault injection": importa un fixture (`store.import_fixture`),
   riproduce gli eventi e **fallisce (exit code 1) se contiene
   `assertion.failed`**. È l'equivalente "inietto una condizione di fallimento
   controllata" — l'asserzione fallente funge da testato di fault — valutato
   in modo deterministico.
3. **Assertion Engine** (`trace.Run.assert_that` → evento
   `assertion.passed`/`assertion.failed`). È il punto di "iniezione" della
   verifica strutturata: l'agente o l'adapter iniettano un assert
   esplicito nel log; il Replay Engine e il `test` CLI lo rialzano come
   segnale di fault.
4. **Adapter AgentShield** (`adapters/agentshield.py`): ingresso di eventi
   di *guardrail/spesa* (`agentshield.spend.evaluation`) — il lato più
   vicino al concetto di "fault esterno" nel log — che possono poi
   alimentare il Regression Report (`diff.py:detect_regression`).

In sintesi, il "Fault Injector" esiste nella codebase come **un insieme
disperso** (replay engine + CLI test + assertion logging + AgentShield
adapter) che insieme forniscono: (a) un mock deterministico riproducibile,
(b) un punto di iniezione di asserzioni/fault, (c) un runner CI che converte
i fault in exit-code. Non c'è però un componente *unico* e *rinominato*
dedicato — è la principale "lacuna architetturale" da notare (vedi §4).

## 3. Data Flow — da prompt all'eventuale mock determinismo

Il flusso è **write-once / read-many** e lineare fino al log append-only;
ogni fase successiva legge lo stesso SQLite.

```
[agent code / adapter]                         [local disk]              [UI / API / CI]
        │                                           │                          │
  with trace.run(name) ──create_run──> runs: status=running                     │
        │ yield Run                                          │                  │
        │ run.input(prompt) ──_log──> redact() ──log_event──> events: user.input │
        │ run.retrieval(q,results)                              │                │
        │ run.context_block(src="memory",...)                   │                │
        │ run.prompt(system,messages,context)                   │                │
        │ run.tool_call(...) / tool.result                       │                │
        │ run.memory_write/update/delete                         │                │
        │ run.output(response)                                    │                │
        │ run.assert_that(...)                                    │                │
   block end ──finish_run──> runs: status=ok|error                │                │
        │                                                         │                │
   auto_open? ──serve──> AgentDebugger.start()                    │                │
        │                  (uvicorn demone 127.0.0.1:4173)        ▼                ▼
        │                                          FastAPI server  ──get_store()──> TraceStore (stesso file)
        │                                          GET /api/runs/{id}
        │                                          GET .../retrieval/explain  ──explain_retrieval()
        │                                          GET .../memory/view ──memory_view() (temporal)
        │                                          GET /api/diff?a=&b= ──diff_runs() (cause assegnate)
        │                                          GET /api/regression ──detect_regression()
        │                                          POST .../replay ──ReplayEngine.replay() ──> ReplayReport
        │                                                                                   │
        │                                                                                   ▼
   agent-devtools test fixtures/*.json ──import_fixture──> eventi replay ──assertion.failed? ──exit 1
```

**Passo-passo operativo:**

1. **Apertura.** `trace.run(agent_name)` chiama `store.create_run(run_id,
   agent_name, metadata)` → INSERT in `runs` con `status='running'`,
   inizializza `_seq_counters[run_id]=0`. Viene `yield`ato un `Run`.
2. **Tracing live.** Ogni chiamata `run.<event>(...)` costruisce il payload,
   passa `redact()` (sanitizza a fonte) e chiama `store.log_event` →
   `INSERT INTO events (run_id, seq, ts, type, payload)` con `seq`
   incrementale per run (ordine totale garantito) e `ts=time.time()`. I
   metodi `retrieval` e `context_block` sono progettati per *conservvare la
   provenienza*: `context_block(source=...)` e i campi `outcome`/
   `denied`/`reason` di retrieval sono le informazioni che il Behavior
   Diff userà al punto successivo.
3. **Chiusura + servizio.** Nel `finally`, `store.finish_run(run_id,
   status)` aggiorna `finished_at`/`status`. Se `auto_open`,
   `trace.serve()` → `AgentDebugger.start()` → `_ensure_server_started()`
   verifica se 127.0.0.1:4173 è libero; se libero, avvia Uvicorn in un
   thread demone su `agent_devtools.server.main:app`, altrimenti riusa il
   server esistente (e `_warn_if_db_mismatch` controlla che serva lo stesso
   DB). Il server e l'SDK condividono il medesimo file SQLite:
   `agent-devtools serve` e la scrittura SDK risolvono `default_db_path()`
   (o `AGENT_DEVTOOLS_DB`) allo stesso modo — ma non sempre (vedi §4).
4. **Lettura / viste derivate.** La UI (SPA in `server/static/`, con
   `index.html`/`app.js`/`style.css`) chiama le API REST. Ogni endpoint
   chiama `get_store()` (istanza globale condivisa) e legge eventi; le
   viste sono pure derivate a richiesta: `explain_retrieval`
   (`explain.py`) raccoglie `retrieval.query`+`retrieval.result` e genera
   motivazioni umane; `memory_view` (`memory_view.py`) deriva lo stato
   temporale; `diff_runs` (`diff.py`) produce sezioni, narrazione, cause
   assegnate e catene di evidenza; `detect_scope_mismatches`
   (`scope.py`) controlla fuga cross-tenant. Niente è materializzato a
   scrittura: aggiungere una vista non richiede migrazioni.
5. **Mock deterministico / replay.** `POST /api/runs/{run_id}/replay` →
   `ReplayEngine(store).replay(run_id)` → `_build_report` ripercorre gli
   eventi in ordine `seq`, ricostruisce lo stato memoria da zero e verifica
   coerenza → `ReplayReport` (status completed/diverged/failed +
   `evidence`). Il report è salvato in `replays` e mostrato nella scheda
   **Replay**. Separatamente, `agent-devtools test` (`cli.py`) importa un
   fixture JSON, riesegue le asserzioni e converte `assertion.failed` in
   `exit(1)` — questo è il ramo CI del "mock deterministico": un fault
   registrato in un run si propaga in un fail CI ripetibile.

Un dettaglio da non perdere: **la provenienza del contesto** (`source` di
`context_block`, `outcome`/`denied` di retrieval, `scope` metadata) è
l'informazione che `diff.py` usa per *spiegare* la divergenza (es.
"un blocco di memoria obsoleto appare verbatim nella risposta del run
cattivo") e non un campo decorativo. È per questo che l'Interception Layer
è manuale-first anziché un bridge JSON generico.

## 4. Design Trade-offs & Challenges — i punti critici

- **Local-first vs condivisibilità.** Il DB SQLite file-based è la ragione
  della semplicità zero-config ("open your browser, runs appear"), ma è anche
  il #1 problema d'usabilità reale: `AgentDebugger._warn_if_db_mismatch`
  esiste perché l'SDK e il server possono risolvere `default_db_path()`
  diversamente (script lanciati da `examples/`, server da root) e finché non
  c'è un server in ascolto il client non accadge il mismatch. La ricerca di
  `_walk_parents` + sottodirectory (`store.py:58-99`) lo attenua ma non
  elimina l'ampiazza. È un trade-off consapevole: niente Postgres/hosted
  (roadmap), ma un foot-gun latente.
- **Eventi piatti vs schema rigido.** Il principio "append-only + viste a
  lettura" (`docs/vision.md`) è forte per estendibilità (nuovi campi
  `usage`/`version`/`outcome`/`scope` senza migrazioni) e per non perdere
  dettaglio framework-specifico. Il costo: i consumer di eventi devono fare
  *parsing difensivo* (vedi `explain_retrieval` che usa `.get()` su tutto) e
  non c'è vincolo a livello DB — un typo in un tipo di evento
  (`retrieval.result`) passa inosservato fino alla lettura. Il limite
  "`agent-devtools test` has no shipped fixtures" (`README.md:588`) è una
  conseguenza: senza fixture d'esempio, la coerenza del modello eventi si
  mantiene solo per via del codice.
- **Redazione a scopo onesto, non di sicurezza.** `redact()` (`redaction.py`)
  e la sua applicazione in `Run._log` nascondono le chiavi per nome e i
  token a forma nota. Ma non è un DLP: non cattura segreti alfanumerici
  arbitrari incollati in un prompt, e non è crittografato. Il server non ha
  auth (limite noto, `README.md:592`) e legge lo stesso file che tutti i
  tool del processo possono aprire. È coerente con "debug locale", ma va
  detto apertamente.
- **Euristica vs verità.** Due pilastri (Behavior Diff `diff.py` e
  Retrieval Explanation `explain.py`) sono *consapevolmente* euristici. Il
  Diff non dimostra la causa, la *indica* ("intenzionalmente heuristic, not
  a proof", `diff.py:6-12`); l'explain di retrieval *inferisce* motivi quando
  l'informazione non fu registrata. È un trade-off percepito vs reale:
  evita di forzare ogni evento in uno schema rigido (che sparirebbe il
  dettaglio) ma richiede all'utente distringere "ipotesi di debug" da
  "verità". Il Replay Engine invece *è* una verità: `completed` significa
  davvero "internally consistent". La coppia (Replay = verità / Diff =
  indizio) è il cuore del prodotto.
- **Il ruolo nomade del "Fault Injector".** Come spiegato in §2.4, non
  esiste un componente unico. Il "deterministic mock" è un *effetto*
  emergente del Replay Engine più del CLI `test`. Questo porta a un'ambiguità
  operativa: se un team volesse "iniettare" un fault (es. simulare un tool
  fallente, o una retrieval vuota) in un run reale, non può farlo con un
 'unica API — deve registrare manualmente gli eventi nel log (o scrivere un
  adapter). È una **lacuna architetturale esplicita**: il progetto punta al
  debugging *reattivo* (perché un bug è successo) e *regressivo* (CI), non
  alla simulazione *proattiva* di fault. Aggiungere un modulo dedicato
  (`faults.py` con iniezione controllata) sarebbe un'estensione naturale ma
  non prevista.
- **Performance / concorrenza SQLite.** SQLite con un singolo lock
  (`self._lock`) serializza scritture e letture. Per carichi di debug
  interattivi locale è più che sufficiente; non scalerebbe a molti
  writer concorrenti — ma non è il caso d'uso (un agente = uno scrittore).
- **`AgentDebugger.stop()` è un no-op** per il thread Uvicorn (demone),
  quindi il server non si chiude finché non muore il processo
  (`README.md:589`). È un limite noto: il design Assume che il server
  "viva" per tutta la sessione di debug, non venga ciclato.

## 5. Video Talking Points (5 minuti)

Scaletta orale coerente con `ARCHITECTURE.md`. I minuti sono indicativi per un
video di 5′ (ritmo "sprecato" → concentrarsi su 3 idee forti).

| Min | Argomento (cosa dire a voce) | Riferimento slide/file |
|-----|------------------------------|------------------------|
| 0:00–0:30 | **Hook — il problema reale.** "Le piattaforme dicono *quanto è lento* il tuo agente. DevTools chiede *perché* un agente ha detto una cosa sbagliata. Non vogliamo un dashboard; vogliamo le tre righe del trace che spiegano il bug." | README.md:4,22-31 |
| 0:30–1:30 | **Idea centrale: log eventi append-only + viste derivate a lettura.** "Tutto è in un file SQLite. Non esporti nulla. Il server legge lo stesso file. Perché è forte? Aggiungo un campo `outcome` a retrieval e la UI lo mostra senza migrazioni — niente schema rigido che perde dettaglio." | docs/vision.md:48-55, store.py:SCHEMA |
| 1:30–2:30 | **La chiave perdita da tutti: provenienza del contesto.** "Gli agenti sbagliano perché hanno letto memoria obsoleta. Il log distingue `context.block(source='memory')` e registra *l'ordine di iniezione*. Il Behavior Diff incolla il valore sbagliato nella risposta del run cattivo e ti salta all'occhio: 'questo valore obsoleto appare qui'. Questo è ciò che un JSON generico va perduto." | trace.py:144-150 (`context_block`), diff.py:8-11 |
| 2:30–3:45 | **Replay determinismo = mock offline.** "Il Replay Engine riecoSagisce ogni evento *senza rete, senza LLM, senza codice*. Se dice `completed`, il bug è riproducibile offline; se `diverged`, il log è internamente contraddittorio (es. memory.update su un valore mai scritto — lo stesso bug della memoria obsoleta, ma *provato*)." | replay.py:2-7, replay.py:131 (`_build_report`), 68-94 |
| 3:45–4:45 | **Dalla diagnosi alla CI con un solo modello.** "Gli stessi eventi che ti fanno dire 'è colpa di questa memoria' al comando diventano fail CI: `agent-devtools test` importa un fixture, riproduce gli eventi e fallisce (exit 1) su `assertion.failed`. Assertion Engine (`run.assert_that`) è l'iniettore di fault — lo stesso log serve a debugging interattivo e a regressione automatizzata." | cli.py:23-48, trace.py:191-193 |
| 4:45–5:00 | **Chiusura / onesto.** "Limiti: redazione non è sicurezza, Diff è euristico, server senza auth, e non c'è un componente *unico* 'Fault Injector' — è un effetto del Replay+test. Ma risponde a una domanda che nessun altro piazza così direttamente: 'perché questa run, non quella?'." | README.md:588-592, §2.4/§4 |

---

## Mappa dei file (riepilogo operativo)

```
packages/python-sdk/agent_devtools/
├── trace.py          # Interception Layer (manuale) + tracing entry (Run, trace.run, serve/open_ui)
├── store.py          # Tracing Engine persistente (TraceStore, append-only SQLite, fixture I/O)
├── redaction.py      # Interception Layer — sanitizzazione a ingresso (redact)
├── debugger.py       # Tracing Engine — orchestratore zero-config (AgentDebugger, server lifecycle, _warn_if_db_mismatch)
├── replay.py         # Replay Engine + Deterministic Mock (ReplayEngine, ReplayReport)
├── diff.py           # Behavior Diff: cause assegnate + catene di evidenza (diff_runs, detect_regression)
├── explain.py        # Retrieval Explanation (explain_retrieval)
├── memory_view.py    # Vista temporale memoria (memory_view) — visto a lettura
├── scope.py          # Rilevazione fuga cross-tenant (detect_scope_mismatches)
├── cli.py            # Fault/Mock layer CLI: serve + test (fixture replay → exit code)
├── adapters/
│   ├── langchain.py  # Interception Layer — LangChain callback bridge (LangChainTraceHandler)
│   ├── groq.py       # Interception Layer — TracedGroq wrapper
│   └── agentshield.py# Fault layer — ingresso eventi di spesa/guardrail (NDJSON → log)
└── server/           # FastAPI debug server + static UI; API di letttura congiunta al medesimo SQLite
    └── main.py
```







