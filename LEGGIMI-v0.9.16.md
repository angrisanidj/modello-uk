# modello-UK v0.9.16 — local-strength refinement sweep

La v0.9.16 è l’ultimo affinamento controllato del primo layer post-v0.9.10 che ha migliorato davvero il benchmark 2024.

## Riferimento verificato
La v0.9.15, selezionando sul solo 2019 `local_strength=0.25` e `byelection_strength=0`, ha prodotto **585/632, errore 42** nel 2019 e **501/632, errore 166** nel 2024.

## Griglia fissa
- `local_strength`: 0.00, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50
- `confidence_floor`: 0.00, 0.35, 0.55
- `margin_cap`: nessun limite, 15 p.p., 25 p.p.
- `byelection_strength`: fissato a 0

Sono **81 configurazioni**. `confidence_floor` usa soltanto copertura/recency/numero di ward; `margin_cap` usa il margine della previsione canonica pre-elettorale. Il 2024 non entra nella selezione.

## Guard
- baseline canonica invariata: 583/42 nel 2019, 494/176 nel 2024;
- riferimento v0.9.15 obbligatorio: 585/42 nel 2019, 501/166 nel 2024;
- copertura locale >=300 collegi;
- 81 candidati esatti;
- selezione solo sul 2019.

## Gate
Il candidato selezionato sul 2019 deve raggiungere nel 2024 **>=506/632** con **seat_abs_error_sum <=166**. La versione resta shadow anche se passa. Se nessuna configurazione fissa passa, si interrompe il tuning locale e si passa all’audit degli errori residui.

## Output
- `data/local-strength-refinement-v0916.json`
- `data/backtest-v0916-local-refinement.json`
- `data/error-structure-v0916.json`
- `data/bes-integrity-v0916.json`
- `data/mrp-lite-model.json`
- `data/mrp-lite-live.json`
