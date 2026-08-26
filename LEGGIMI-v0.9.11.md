# Modello UK v0.9.11 — diagnostica Reform (shadow)

Questa versione non cambia il modello di produzione. Conserva integralmente il candidato v0.9.10, compresi `route_strength = 0.0` e `unwind_strength = 0.0`, e usa il risultato 2024 soltanto per descrivere la struttura locale degli errori Reform.

Il sito deve continuare a mostrare e usare il fallback prudente. La v0.9.11 non può diventare live anche se il gate del candidato sottostante dovesse cambiare: `approved`, `publication_ready`, `used_for_parameter_selection` e `changes_production_model` sono bloccati in modalità diagnostica.

## File da caricare

Sovrascrivere nel repository i file mantenendo esattamente questi percorsi:

- `.github/workflows/update-data.yml`
- `tools/build_mrp_lite.py`
- `scripts/app.js`
- `index.html`
- `requirements.txt`

Il pacchetto contiene anche questo documento. Il workflow completo è fornito inoltre come file separato `update-data-v0.9.11.yml`.

## Esecuzione

1. Caricare tutti i file e fare commit su `main`.
2. Aprire **Actions → Update and deploy UK model**.
3. Eseguire **Run workflow** oppure attendere l'avvio automatico.
4. Verificare che lo step `Validate BES integrity and v0.9.11 diagnostic safeguards` termini con successo.
5. Verificare il deploy GitHub Pages e la dicitura `Versione 0.9.11 · diagnostica Reform (shadow)`.

## Output generati

- `data/mrp-lite-model.json`: candidato v0.9.10 conservato, marcato diagnostic-only.
- `data/mrp-lite-live.json`: payload shadow con `approved: false`; il browser non lo attiva.
- `data/backtest-v0911-reform-diagnostics.json`: risultati 2017, validazione 2019 e benchmark di sviluppo 2024.
- `data/reform-diagnostics-v0911.json`: report completo sugli errori Reform.
- `data/bes-integrity-v0911.json`: controlli di integrità BES.

## Contenuto del report Reform

Il report classifica tutti i 632 collegi GB in veri positivi, falsi positivi, falsi negativi e veri negativi rispetto a una vittoria Reform. Per ogni caso rilevante include:

- vincitore previsto, reale e della baseline;
- quote previste e reali;
- quota Reform della baseline, margine e turnout;
- quota, margine e posizione Reform previsti;
- contestabilità Reform congelata dalla v0.9.10;
- indicatori demografici BES/Census disponibili;
- quota Reform reale ed errore della quota, ma soltanto come **outcome 2024**;
- riepiloghi per coorte, regione e vincitore reale dei falsi positivi.

Le comparazioni ordinate in `feature_comparisons` usano esclusivamente caratteristiche disponibili ex ante o prodotte dal candidato prima di osservare il risultato 2024. `actual_ref_share` e `ref_share_error` sono esplicitamente separati in `outcome_diagnostics_2024` e non possono entrare nella graduatoria dei predittori.

Le 39 vittorie Reform previste e le 5 reali non implicano automaticamente 34 falsi positivi: il numero esatto dipende dall'intersezione fra i due insiemi ed è calcolato dalla matrice di confusione.

## Salvaguardie

- Nessuna soglia o coefficiente viene stimato sul 2024.
- `parameter_updates` deve essere vuoto.
- Le variabili osservate nel 2024 (`actual_ref_share`, `ref_share_error`) sono escluse dalla graduatoria dei predittori.
- Il workflow verifica che il report copra 632 collegi e sia coerente con il backtest.
- Il workflow verifica che le due intensità di routing restino zero.
- Un **regression guard v0.9.10** richiede esattamente: 583 vincitori corretti e 42 seggi di errore nel 2019; 494 vincitori corretti, 176 seggi di errore e 39 seggi Reform previsti contro 5 reali nel benchmark 2024.
- Con routing a zero, le metriche pre-routing e post-routing devono coincidere nel 2019 e nel 2024.
- Se modello shadow, backtest o diagnostica falliscono, il workflow fallisce e la v0.9.11 non viene distribuita; il sito di produzione resta comunque sul fallback.
- Il 2019 resta la validazione temporale; il 2024 è dichiarato benchmark di sviluppo, non holdout incontaminato.
- Una futura correzione richiederà una versione separata e una nuova validazione fuori dal campione usato per formulare la regola.

## Messaggio commit suggerito

`feat: add v0.9.11 Reform false-positive diagnostics`
