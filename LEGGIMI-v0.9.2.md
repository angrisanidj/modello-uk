# Modello UK v0.9.2 — official winners + Other candidate fix

Questa versione corregge l'ultimo errore concettuale del backtest v0.9.x.

## 1. Vincitori reali
I risultati reali non vengono più dedotti dal massimo delle quote aggregate.
Sono letti direttamente dalle variabili ufficiali BES:
- Winner10 / Second10
- Winner15 / Second15
- Winner17 / Second17
- Winner19 / Second19
- Winner24 / Second24

L'integrity gate confronta questi WinnerXX con i conteggi storici attesi.

## 2. Other non è un super-partito
`Other` resta necessario per modellare la quota aggregata di:
- indipendenti;
- Speaker;
- minori non modellati.

Ma la somma di questi voti NON è un singolo candidato.

Per decidere il vincitore previsto:
- Lab/Con/LD/Green/Reform/SNP/Plaid competono normalmente;
- `Other` può competere soltanto se nella baseline un candidato Other era
  vincitore o secondo.

È informazione solo della baseline: non c'è leakage dal risultato futuro.

La stessa regola vale:
- nel backtest;
- nella proiezione live;
- nelle 50.000 simulazioni Monte Carlo del browser.

## 3. Actions
Il workflow mantiene `push` su `main`, `workflow_dispatch` e schedule.
`cancel-in-progress` passa a `true`: se carichi più file uno dopo l'altro,
le Action dei commit intermedi vengono cancellate e resta quella dell'ultimo
commit, evitando code di run vecchi.

## Gate
Nessun cambiamento:
- holdout 2024 >=80%;
- guadagno >=5 p.p.;
- seat absolute error <=200;
- 2019 non può degradare materialmente.

La soglia publication-ready resta ancora più severa: 85% / errore <=140.

## File
- index.html
- scripts/app.js
- tools/build_mrp_lite.py
- requirements.txt
- .github/workflows/update-data.yml completo
