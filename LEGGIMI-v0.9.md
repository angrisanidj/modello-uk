# Modello UK v0.9 — MRP-lite in shadow validation

Questa versione NON forza un nuovo modello live.

## Nuovo motore
`tools/build_mrp_lite.py` scarica automaticamente:
- BES 2010-2019 Constituency Results with Census and Candidate Data;
- BES 2024 Constituency Results with Census and Candidate Data.

Costruisce un modello constituency-level residuale su:
- voto locale precedente;
- swing nazionale di tutti i partiti;
- winner, runner-up, margine e rank;
- England / Scotland / Wales e regioni inglesi;
- Leave 2016;
- Census: densità, età, tenure, etnia, attività economica, industria e NS-SEC;
- interazioni specifiche per crollo Conservative, crescita Reform, posizionamento Labour/LD e SNP.

## Validazione rolling-origin
1. 2010->2015 fit
2. 2015->2017 selezione modello
3. refit 2010->2017, test 2017->2019
4. refit 2010->2019, HOLDOUT 2019 notional->2024
5. solo dopo il punteggio holdout, refit con 2024 per la proiezione live.

Il 2024 NON sceglie modello, iperparametri o blend.

## Gate duro
Live solo se:
- holdout 2024 >= 80% collegi corretti;
- +5 punti percentuali almeno sul fallback;
- errore assoluto aggregato seggi <= 200;
- 2019 non perde oltre 1 punto di accuracy;
- 2019 non peggiora oltre 30 seggi di errore aggregato.

`approved:false` è un risultato valido e mantiene automaticamente il fallback v0.8.1.

`publication_ready:true` richiede una soglia ancora più alta:
- almeno 85% sul holdout 2024;
- errore seggi <= 140.

## File
Sostituire/aggiungere:
- `index.html`
- `scripts/app.js`
- `tools/build_mrp_lite.py` (nuovo)
- `requirements.txt`
- `.github/workflows/update-data.yml` completo

Dopo la GitHub Action, controllare:
- `data/mrp-lite-model.json`
- `data/backtest-v09-mrp-lite.json`
- `data/mrp-lite-live.json`
