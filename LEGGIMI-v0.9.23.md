# modello-UK v0.9.23 — MRP Geography Bridge (shadow research)

Questa versione **non modifica automaticamente il modello pubblicato**. È un esperimento shadow costruito per verificare se la geografia constituency-level di MRP esterni pre-elettorali può colmare il principale gap del modello interno senza cedere agli MRP esterni il controllo del voto nazionale.

## Architettura

1. Il modello interno produce le proprie quote per collegio e il proprio target nazionale GB.
2. Un MRP esterno viene trasformato in un **fattore geografico relativo**: quota del partito nel collegio / quota nazionale ponderata dello stesso MRP.
3. Il fattore viene applicato alle quote interne con una forza `strength`.
4. Le quote sono normalizzate nel collegio.
5. Un rake finale forza nuovamente il risultato al **target nazionale del modello interno**.

Quindi il topline nazionale dell'MRP esterno non entra nella previsione finale.

## Selezione e anti-overfitting

La `strength` è scelta esclusivamente sul MRP YouGov pre-elettorale del 2019, con griglia fissa:

`0.00, 0.25, 0.50, 0.75, 1.00, 1.25`

Dopo la selezione, il parametro è congelato. Il benchmark 2024 non seleziona né il parametro né il provider.

Il benchmark primario 2024 è predefinito come **YouGov 3 luglio 2024**. More in Common 3 luglio 2024 e l'ensemble geometrico YouGov+MiC sono solo diagnostici.

## Gate

- Validazione 2019: almeno **585/632**, errore seggi ≤ **42**.
- Research gate 85%: almeno **538/632**, errore seggi ≤ **166**, più gate 2019.
- Breakthrough 87%: almeno **550/632**, errore seggi ≤ **150**, più gate 2019.
- Stretch 90%: almeno **569/632**, errore seggi ≤ **130**, più gate 2019.

Un gate scientifico negativo **non manda in errore la GitHub Action**: l'esperimento viene comunque salvato, così possiamo leggere il risultato. Solo errori tecnici, copertura insufficiente, regressioni della baseline o leakage fanno fallire il workflow.

## Live 2026

Lo shadow live usa, quando disponibile:

`YouGov 2024 geography × (MiC 2026 relative geography / MiC 2024 relative geography)`

poi applica la forza scelta nel 2019 e fa il rake al target polling interno.

Se il workbook MiC 2026 non è disponibile o cambia schema, il backtest non viene perso: lo shadow live usa temporaneamente la sola geografia YouGov 2024 e lo dichiara esplicitamente come fallback. In ogni caso `applied_to_production=false`.

## File generati

- `data/backtest-v0923-geography-bridge.json`
- `data/mrp-geography-bridge-v0923.json`
- `data/mrp-lite-live-v0923-shadow.json`
- `data/bes-integrity-v0923.json`

## File da caricare

- `tools/build_mrp_geography_bridge.py`
- `tools/build_mrp_lite.py` (core HOTFIX3 già verificato)
- `.github/workflows/update-data.yml`
- `LEGGIMI-v0.9.23.md`

Il frontend resta volutamente quello corrente: questa versione è ricerca shadow e non viene promossa prima del backtest.
