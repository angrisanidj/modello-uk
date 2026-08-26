# Modello UK v0.9.7 — FPTP contestability calibration

La v0.9.6 ha prodotto il primo holdout affidabile:
- baseline 2024 ~68%;
- MRP-lite share model ~73%;
- Reform sovrastimato in seggi;
- Labour e Liberal Democrats sottostimati.

La v0.9.7 NON usa il 2024 per correggere questi errori.

## Stage 1 — share model
Resta il modello MRP-lite/residuale già validato:
- baseline locale;
- national swing;
- Census;
- Leave;
- paese/regione;
- winner/runner-up/margini;
- raking ai target nazionali.

## Stage 2 — FPTP contestability
Nuovo classificatore binario party-seat:
“con queste condizioni, questo partito è davvero competitivo per vincere?”

Feature solo baseline/pre-elezione:
- quote e rank locali;
- incumbent-party proxy;
- runner-up;
- margine e frammentazione;
- target nazionale e variazione;
- Conservative collapse;
- targeting Labour/LibDem;
- Leave, densità, età, tenure;
- interazioni Reform/UKIP.

Il 2015 UKIP è quindi un precedente naturale per distinguere un forte voto
nazionale da un voto territorialmente efficiente.

Il classificatore NON decide direttamente il vincitore:
produce un prior di contestabilità che redistribuisce moderatamente le quote
locali; poi il modello viene nuovamente raked ai target nazionali.
Quindi il layer cambia la geografia, non il totale nazionale.

## Anti-leakage
- share model: selezione sul 2017;
- contestability strength/classifier: selezione sul 2017;
- 2019 = validation unseen;
- 2024 = holdout unseen;
- solo dopo il punteggio 2024, il live refit include 2024.

## Gate
Invariato:
- holdout >=80%;
- +5 p.p. sul baseline;
- seat abs error <=200;
- 2019 non può peggiorare materialmente.

Publication-ready:
- >=85%;
- seat abs error <=140.

## Output diagnostici
`mrp-lite-model.json` contiene:
- `selected_spec`;
- `selected_contest_spec`;
- `validation_2019.share_only_candidate`;
- `validation_2019.candidate`;
- `holdout_2024.share_only_candidate`;
- `holdout_2024.candidate`;
- `contestability_selection_2017`.

Così possiamo misurare separatamente quanto aggiunge davvero il layer FPTP.
