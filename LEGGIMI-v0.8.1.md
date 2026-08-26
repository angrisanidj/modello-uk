# Modello UK v0.8.1 — palette NI + Monte Carlo UX

Correzioni:
- nuova palette Northern Ireland, separata visivamente da Plaid Cymru e dai principali colori GB;
- mentre le 50.000 simulazioni sono in corso, emiciclo e mappa sono etichettati chiaramente come proiezione centrale provvisoria;
- pulsante "Probabilità" disabilitato fino al completamento del Monte Carlo;
- al termine il titolo passa a "Distribuzione dei seggi" e la mappa probabilistica diventa disponibile;
- `state.mc` viene azzerato a ogni refresh, evitando che un vecchio risultato Monte Carlo resti visibile durante il nuovo calcolo;
- cache JS e Monte Carlo invalidate con v0.8.1.

Nessuna modifica al seat model, ai dati NI o al backtest.
Il workflow completo è incluso, invariato rispetto alla v0.8.
