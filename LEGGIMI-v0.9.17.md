# modello-uk v0.9.17 — audit dei 131 errori residui

Questa release **non introduce un nuovo modello**. È una versione diagnostica shadow costruita per capire dove intervenire dopo che la v0.9.15 ha portato il benchmark 2024 da 494/632 a 501/632 collegi corretti e l'errore seggi da 176 a 166.

## Cosa resta congelato

- Candidato canonico: equivalente alla v0.9.10.
- Regression guard 2019 canonico: **583/632**, errore seggi **42**.
- Regression guard 2024 canonico: **494/632**, errore seggi **176**.
- Incumbent routing: `route_strength=0`, `unwind_strength=0`.
- Produzione: nessuna promozione automatica; `approved=false`, `publication_ready=false`, `shadow_only=true`.

## Riferimento shadow v0.9.15

La build ricostruisce senza tuning la configurazione già selezionata prima del 2024:

- `local_strength = 0.25`
- `confidence_floor = 0.0`
- `margin_cap = null`
- by-election strength = `0`

Deve riprodurre obbligatoriamente:

- 2019: **585/632**, errore seggi **42**;
- 2024: **501/632**, errore seggi **166**.

Se questi valori non vengono riprodotti, il workflow fallisce.

## Nuovo output: `data/error-audit-v0917.json`

L'audit riguarda esattamente i **131 collegi** ancora errati nella v0.9.15 e contiene:

- matrice completa `predicted_winner → actual_winner`;
- cluster `predetto → reale × regione`;
- distribuzione degli errori per regione e fascia di margine previsto;
- winner e runner-up della baseline 2019;
- quote previste, quote reali ed errore di quota per partito;
- disponibilità, copertura, confidence ed advantage del segnale delle elezioni locali;
- confronto seggio-per-seggio fra v0.9.10 e v0.9.15;
- elenco dei seggi corretti dal local-strength e di quelli eventualmente rotti;
- famiglie diagnostiche con almeno 5 errori;
- numero minimo di recuperi netti necessari per arrivare all'80%: **5**.

Il workflow impone che l'impatto v0.9.15 rispetto alla v0.9.10 si riconcili esattamente a **+7 collegi netti**.

## Disciplina anti-overfitting

Il risultato 2024 viene ispezionato in questa versione **solo per diagnosi**. L'audit non può:

- scegliere coefficienti;
- scegliere soglie;
- modificare il feature set;
- aggiornare parametri;
- promuovere un modello.

Qualunque ipotesi che nascerà dai cluster 2024 dovrà essere implementata in una versione successiva e sostenuta da un analogo storico o da una validazione esterna/futura prima della promozione.

## File principali

- `tools/build_mrp_lite.py`
- `.github/workflows/update-data.yml`
- `scripts/app.js`
- `index.html`
- `requirements.txt`

Il workflow completo è fornito anche separatamente come `update-data-v0.9.17.yml`.
