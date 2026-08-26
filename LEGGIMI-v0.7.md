# Modello UK v0.7 — partial national raking

## Obiettivo
La v0.6 ha mostrato che il transfer model peggiora, mentre il raking completo migliora molto il 2024 ma perde 2 collegi nel 2019. La v0.7 prova soltanto a trovare il punto intermedio.

- α=0: nessun raking.
- α=1: raking completo.
- griglia: 0,000–1,000 a passi di 0,025.
- α scelto solo su 2010→2015 + 2015→2017.
- 2017→2019 e 2019N→2024 restano fuori dal fit.
- gate live: non può peggiorare né winner accuracy né errore seggi in nessuno dei due test.

Nel browser il raking viene applicato al centro constituency-level già comprensivo dei segnali Scotland/Wales e del modello territoriale fallback. Il Monte Carlo parte poi da quel nuovo centro, senza ricalcolare il raking 50.000 volte.

## Revisione grafica
È il passaggio immediatamente successivo alla validazione della v0.7: desktop/mobile, gerarchia, emiciclo, KPI, mappa, dettaglio collegio, tooltip, colori e rifinitura editoriale.

## File da sostituire
- `index.html`
- `scripts/app.js`
- `tools/build_backtest.py`
- `.github/workflows/update-data.yml`
