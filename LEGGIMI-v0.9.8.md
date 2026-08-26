# Modello UK v0.9.8 — party-specific territorial calibration

La v0.9.7 ha mostrato che un unico correttore FPTP non è adatto a tutti:
- Liberal Democrats quasi perfetti nel benchmark 2024;
- Reform ancora troppo efficiente territorialmente;
- validazione 2019 peggiorata.

## Party-specific dispersion
Per ogni partito viene stimato, usando solo elezioni precedenti,
`sd(share locale) / mean(share locale)`.
Le elezioni con consenso nazionale più simile al target pesano di più.
Il risultato modifica la geografia, poi il raking ripristina il totale nazionale.

## Party-specific FPTP strength
Il classificatore è congelato alla logistic regression C=3 della v0.9.7.
Sul 2017 si sceglie solo quanto usarlo per ciascun partito:
Lab, Con, Reform, LD, Green, SNP, Plaid, Other.
Il 2019 resta la validazione temporale.

## 2024
Dopo le diagnosi delle precedenti v0.9.x, il 2024 non viene più definito
holdout incontaminato. Rimane un development benchmark severo.
La chiave `holdout_2024` resta nei JSON solo per compatibilità.

`publication_ready` è sempre false in questa versione: una futura v1 richiede
una validazione esterna/fresca oltre al benchmark 2024.

## Gate beta-live
- benchmark 2024 >=80%;
- almeno +5 p.p. sul baseline;
- seat absolute error <=200;
- 2019 non può peggiorare oltre i limiti già fissati.

Il workflow incluso parte dalla versione riparata con deploy-pages completo.
