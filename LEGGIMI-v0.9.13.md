# modello-UK v0.9.13 — Reform structural sweep (shadow research)

## Obiettivo

La v0.9.13 non tenta di promuovere un nuovo modello. Mantiene **congelato il candidato v0.9.10** e usa un solo run per confrontare più modi di trattare il problema strutturale emerso nel 2024: nel 2019 il Brexit Party non si presentò in molti collegi conservatori, quindi uno zero storico non equivale necessariamente a zero potenziale locale.

Il vantaggio operativo è che non dobbiamo più creare una release per ogni ipotesi: il workflow produce un report comparabile di tutte le varianti nello stesso benchmark.

## Salvaguardia principale

Il candidato canonico deve rimanere identico alla v0.9.10/v0.9.11:

- 2019: **583/632**, errore seggi **42**;
- benchmark 2024: **494/632**, errore seggi **176**;
- Reform previsto nel candidato canonico 2024: **39 seggi**;
- routing incumbent: **0 / 0**.

Il workflow fallisce se uno di questi valori cambia.

## Nuovo passaggio pre-2024

1. Il prior geografico iniziale è stimato sulla geografia UKIP 2015, come nella v0.9.12.
2. Quel prior viene poi **ricalibrato usando soltanto i collegi in cui il principale veicolo Reform/Brexit si presentò davvero nel 2019**.
3. La calibrazione usa soltanto informazioni disponibili nel 2019: score latente UKIP, quote Con/Lab/LD/Green, Leave e struttura della competizione locale.
4. Nessuna etichetta o quota del 2024 entra nella calibrazione.

Questo evita il difetto della v0.9.12, che trasportava direttamente nel 2019 quote latenti ancora sulla scala molto più alta di UKIP 2015.

## Varianti valutate nello sweep

Il file `data/reform-structural-sweep-v0913.json` confronta undici configurazioni:

- `baseline_v0910`: nessuna imputazione, candidato congelato;
- `raw_latent_v0912`: replica dell'esperimento v0.9.12;
- `calibrated_all_half`;
- `calibrated_all_current`;
- `calibrated_all_strong`;
- `calibrated_con_half`;
- `calibrated_con_current`;
- `calibrated_con_strong`;
- `calibrated_all_norm_current`;
- `calibrated_con_norm_current`;
- `calibrated_con_norm_strong`.

Le varianti `*_norm_*` correggono anche il denominatore nazionale dello swing Reform: invece di usare il 2% osservato nel 2019 — depresso dalla copertura incompleta dei candidati — usano la quota nazionale controfattuale implicita dalla calibrazione a copertura piena. È ancora un input esclusivamente pre-2024.

Le varianti `calibrated_all` imputano tutti i collegi 2019 non contestati. Le varianti `calibrated_con` limitano l'imputazione ai collegi non contestati con baseline vincente Conservative, coerentemente con la strategia di ritiro del Brexit Party.

Le intensità `half/current/strong` modificano soltanto la forza dell'esperimento shadow. **Il 2024 non seleziona nessuna di queste intensità per il live.**

## Output da leggere dopo il run

Il workflow stampa per ogni variante:

- collegi corretti su 632;
- accuracy;
- errore assoluto aggregato dei seggi;
- seggi Reform previsti;
- true positive / false positive / false negative Reform;
- esito del gate numerico.

Il report indica inoltre `best_development_variant` e `passing_variants`, ma sono etichette di ricerca: nessuna variante viene applicata al modello live.

## Gate

Una variante è segnalata come numericamente interessante soltanto se mantiene i criteri già usati:

- accuracy 2024 almeno **80%**;
- miglioramento sufficiente rispetto alla baseline;
- errore seggi non superiore a **200**;
- nessun deterioramento materiale del 2019.

Anche se una variante supera il gate, la v0.9.13 resta `approved:false`, `publication_ready:false`, `shadow_only:true` e `diagnostic_only:true`.

## File

- `tools/build_mrp_lite.py`
- `.github/workflows/update-data.yml`
- `update-data-v0.9.13.yml` — copia separata completa del workflow
- `index.html`
- `scripts/app.js`

## Dopo il caricamento

Eseguire **Update and deploy UK model** e leggere nello step di validazione la sezione `STRUCTURAL SWEEP RESULTS`. Il dato decisivo non sarà soltanto quale variante predice più correttamente Reform, ma se riesce contemporaneamente a superare l'80% complessivo e a non peggiorare l'errore seggi.

## Hotfix di coerenza del pacchetto

Il workflow esegue ora un preflight prima della build e rifiuta repository con file di versioni miste. In particolare verifica che `tools/build_mrp_lite.py`, `scripts/app.js` e `index.html` siano tutti della v0.9.13. Una build shadow che fallisce termina inoltre con exit code 1: il workflow si arresta prima di commit/deploy, lasciando intatta l’ultima versione pubblicata.
