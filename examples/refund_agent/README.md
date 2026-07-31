# Refund Agent Demo

Questo esempio dimostra il valore di Agent DevTools: debug di un agente che usa memoria stale.

## Scenario
- L'agente gestisce richieste di rimborso.
- La policy corretta è "rimborso entro 30 giorni".
- La memoria dell'agente contiene una policy vecchia ("14 giorni").
- Il retrieval recupera la policy corretta, ma la memoria vecchia prevale.

## Generare le run
```bash
python generate_runs.py