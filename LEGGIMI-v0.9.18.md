# modello-uk v0.9.18 — Liberal Democrat target-seat concentration sweep

Versione sperimentale **shadow-only**. Non modifica né promuove automaticamente il modello live/canonico.

## Obiettivo

La v0.9.17 ha mostrato che, dopo il miglioramento v0.9.15, una delle maggiori famiglie di errore residue nel benchmark 2024 è `Conservative → Liberal Democrat`. La v0.9.18 verifica una sola ipotesi: il modello può distribuire il voto nazionale LD in modo troppo uniforme e sottostimare la concentrazione nei collegi realmente contendibili.

La regola non contiene alcun hard-code regionale. Il target score LD usa esclusivamente informazioni conoscibili prima dell'elezione:

- LD vincitore/runner-up nell'elezione precedente;
- quota LD nell'elezione precedente;
- rank e deficit LD nella previsione pre-elettorale;
- vantaggio LD nelle elezioni locali e relativa confidence.

Il voto LD viene concentrato nei collegi con score elevato e poi il raking ripristina l'esatto target nazionale dei partiti. Quindi il layer cambia **la geografia**, non la quota nazionale.

## Disciplina temporale

La base shadow resta la v0.9.15 (`local_strength=0.25`, by-election=0), che deve essere riprodotta esattamente:

- 2019: **585/632**, seat absolute error **42**;
- 2024: **501/632**, seat absolute error **166**.

La v0.9.18 testa una griglia fissata nel codice prima del benchmark:

- `strength`: 0.00, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.65, 0.80;
- `score_floor`: 0.35, 0.50, 0.65;
- totale: **30 configurazioni**.

La configurazione viene selezionata **solo sul 2019** usando corretti, seat error e share MAE. Il 2024 viene aperto soltanto dopo la selezione.

Poiché l'ipotesi LD-target nasce dall'audit del 2024, anche un eventuale successo sul benchmark non è sufficiente a promuoverla: la versione resta `shadow_only` e richiede un analogo storico indipendente o una nuova validazione esterna prima di entrare nel modello pubblicato.

## Gate di ricerca

Il candidato scelto sul 2019 deve ottenere sul 2024:

- almeno **506/632** collegi corretti (>=80%);
- `seat_abs_error_sum <= 166`.

Il report mostra anche la migliore configurazione 2024 ex post, ma soltanto come diagnostica e mai per la selezione.

## Output nuovi

- `data/bes-integrity-v0918.json`
- `data/backtest-v0918-ld-target.json`
- `data/ld-target-sweep-v0918.json`
- `data/v0915-reference-v0918.json`

`data/mrp-lite-model.json` e `data/mrp-lite-live.json` espongono la versione v0.9.18 ma il layer LD non viene applicato al live (`applied_to_live=false`).

## Safeguard

Il workflow fallisce se:

- i 632 collegi GB non passano l'integrity gate;
- il candidato canonico non resta 583/42 nel 2019 e 494/176 nel 2024;
- il riferimento v0.9.15 non resta 585/42 e 501/166;
- routing rifiutato viene riattivato;
- la griglia non contiene esattamente 30 configurazioni;
- il selected candidate non è il primo della classifica 2019;
- il 2024 risulta usato per selezionare i parametri;
- il layer LD viene applicato al live.

## Se il test funziona

Solo dopo una validazione indipendente si potrà valutare la promozione del layer. In quella fase il segnale di forza locale del live dovrà essere aggiornato con risultati delle elezioni locali e delle by-election 2025/2026, senza ritoccare i coefficienti usando il risultato live.
