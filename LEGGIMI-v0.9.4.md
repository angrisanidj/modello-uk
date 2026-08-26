# Modello UK v0.9.4 — robust BES party-label parser

Causa esatta del fallimento v0.9.3:
- il BES usa `Spkr` come etichetta dello Speaker;
- il parser riconosceva `Spk` e `Speaker`, ma non `Spkr`;
- l'integrity gate si fermava quindi prima del backtest.

Correzioni:
- `Spkr` -> `other`;
- supporto più robusto per Speaker / Independent / Labour Co-op;
- ogni etichetta GB non appartenente ai partiti modellati viene aggregata in
  `other`, che è esattamente la famiglia del modello;
- le etichette non riconosciute vengono comunque registrate nel report:
  `unknown_winner_labels` e `unknown_second_labels`;
- `raw_winner_labels` / `raw_second_labels` consentono di vedere tutte le
  etichette effettivamente presenti nel BES;
- il gate sui conteggi storici resta invariato, quindi un partito principale
  classificato per errore come `other` fa comunque fallire la validazione.

Restano attivi:
- filtro Northern Ireland prima del parsing;
- esattamente 632 righe GB;
- WinnerXX / SecondXX ufficiali;
- regola anti-super-partito per `Other`;
- holdout >=80%, +5pp, seat error <=200;
- publication-ready >=85%, seat error <=140;
- workflow automatico push/schedule/manuale;
- cancel-in-progress: true.
