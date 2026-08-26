# Piano di calibrazione del backtest

## Elezioni

| Elezione target | Baseline preferita |
|---|---|
| 2010 | 2005 nozionale sui confini 2010 |
| 2015 | 2010 |
| 2017 | 2015 |
| 2019 | 2017 |
| 2024 | 2019 nozionale sui confini 2024 |

## Metriche

- MAE dei seggi per partito;
- errore assoluto totale della composizione della Camera;
- percentuale di collegi con vincitore corretto;
- Brier score per constituency;
- log loss, con floor probabilistico;
- calibrazione per bucket: 0–10, 10–20, …, 90–100%;
- copertura degli intervalli 50% e 80%;
- probabilità corretta di maggioranza / hung parliament;
- errore per paese e regione;
- errore per tipologia di gara: safe, likely, lean, toss-up.

## Parametri da stimare, non fissare a mano

- half-life dei poll;
- peso del campione;
- house effects;
- shrinkage nazionale → regione;
- shrinkage regione → constituency;
- varianza nazionale per partito;
- varianza regionale;
- varianza locale;
- correlazioni tra errori di Labour / Conservative / Reform / LD / Green;
- comportamento territoriale dei partiti con voto molto concentrato;
- floor per nuovi partiti;
- incumbency e by-election correction.

## Obiettivo

La versione da pubblicare dovrà scegliere la specificazione che migliora il backtest fuori campione, non quella che riproduce meglio il 2024 in-sample.
