# Modello Regno Unito — v0.1

Prima base tecnica del modello per le prossime elezioni generali del Regno Unito, costruita sul linguaggio visuale e sulle funzioni del progetto `modello-germania`, ma con un motore territoriale adatto al First Past the Post britannico.

## Cosa funziona già

- polling average automatico con half-life di 7 giorni;
- feed principale via snapshot GitHub Actions + tentativo MediaWiki live + fallback locale;
- 650 seggi totali: 632 GB modellati a livello di constituency + 18 Northern Ireland separati;
- baseline 2024 a livello di candidato/collegio dalla House of Commons Library;
- geometrie ufficiali ONS luglio 2024, versione BGC generalizzata a 20 m;
- proiezione centrale constituency-by-constituency;
- Monte Carlo deterministico da 50.000 simulazioni, a blocchi asincroni da 1.000;
- cache legata al fingerprint dei sondaggi e della baseline;
- intervallo 10°–90° percentile per i seggi;
- probabilità di maggioranza e hung parliament;
- probabilità di vittoria per singolo collegio;
- mappa cliccabile e modalità “proiezione / probabilità”;
- costruttore di maggioranze;
- tabella dei sondaggi;
- pipeline fail-soft: una fonte non valida non sovrascrive l’ultimo snapshot valido.

## Importante: stato metodologico

Questa è una **v0.1 beta**, non ancora una previsione pubblicabile come modello definitivo. Il polling layer e l’infrastruttura Monte Carlo sono già utilizzabili; i parametri che trasformano il voto nazionale in voto di collegio sono iniziali e devono essere calibrati con il backtest 2010–2024.

In particolare mancano ancora:

1. modello esplicito England / Scotland / Wales e nove regioni inglesi;
2. uso strutturato dei sondaggi subnazionali;
3. regressori demografici e territoriali con shrinkage;
4. gestione degli effetti di incumbency, by-election e defections dopo il 2024;
5. calibrazione separata di Reform, Lib Dem, Green, SNP, Plaid e Restore Britain;
6. modulo probabilistico Northern Ireland;
7. backtest completo con Brier score e calibrazione delle probabilità.

## Prima installazione su GitHub

Caricare **l’intero contenuto della cartella**, non soltanto `index.html`, perché questa versione usa file separati e una GitHub Action.

Dopo il primo push:

1. aprire **Actions → Update UK election data → Run workflow**;
2. verificare che vengano popolati `data/polls.json`, `data/constituencies-2024.json` e `data/constituencies-2024.geojson`;
3. abilitare GitHub Pages dal branch `main` / root;
4. aprire la pagina: il Monte Carlo parte solo quando trova la baseline dei 650 collegi.

La Action è inoltre programmata ogni giorno alle 05:17 UTC. Se i dati non cambiano, non crea alcun commit.

## Fonti

- Sondaggi: https://en.wikipedia.org/wiki/Opinion_polling_for_the_next_United_Kingdom_general_election
- MediaWiki API: https://en.wikipedia.org/w/api.php
- Risultati 2024: https://commonslibrary.parliament.uk/research-briefings/cbp-10009/
- CSV candidati 2024: https://researchbriefings.files.parliament.uk/documents/CBP-10009/HoC-GE2024-results-by-candidate.csv
- UK Parliament election results: https://electionresults.parliament.uk/
- Data dictionary: https://electionresults.parliament.uk/meta/data-dictionary
- ONS Westminster constituencies July 2024 BGC: https://geoportal.statistics.gov.uk/

## Scelte iniziali del modello

Baseline nazionale GB 2024 usata per trasformare lo swing:

- Labour 34,6%
- Conservative 24,4%
- Reform UK 14,7%
- Liberal Democrats 12,6%
- Green 6,6%
- SNP 2,6%
- Plaid Cymru 0,7%

Restore Britain non esisteva come lista nazionale nel 2024: viene quindi introdotto con una base minima e shrinkage più forte. È una soluzione temporanea da sostituire con un modello di trasferimento/localizzazione calibrato.

## Struttura

```text
modello-regno-unito/
├── index.html
├── styles.css
├── scripts/
│   └── app.js
├── data/
│   ├── polls-fallback.json
│   ├── constituencies-2024.json
│   ├── constituencies-2024.geojson
│   └── ni-2024.json
├── tools/
│   └── build_data.py
├── .github/workflows/
│   └── update-data.yml
└── requirements.txt
```

## Principio di cache

La simulazione usa un seed derivato dal fingerprint dei sondaggi e della baseline territoriale. Il browser conserva l’output delle 50.000 simulazioni in `localStorage`; un semplice refresh della pagina non ricalcola tutto se l’input non è cambiato.
