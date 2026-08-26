# Modello UK v0.9.5 — RUK + validator fix

La v0.9.4 aveva due difetti distinti.

1. Parser:
   - `Spkr` era stato corretto;
   - mancava però `RUK`, abbreviazione standard di Reform UK;
   - v0.9.5 mappa esplicitamente `RUK -> ref`.

2. GitHub Action:
   - il workflow caricava:
       v094 = load("data/backtest-v094-mrp-lite.json")
   - ma verificava per errore:
       v092.get("version")
   - questo è un NameError certo quando l'integrity gate arriva oltre quel punto.

La v0.9.5 usa il nome neutro:
    backtest = load(...)
e verifica:
    backtest.get("version")

Così un cambio di versione futuro non può più lasciare riferimenti v092/v094
inconsistenti.

Il validator stampa anche `integrity.errors` esplicitamente nei log.

Restano invariati:
- 632 collegi GB;
- Northern Ireland esclusa prima del parsing;
- WinnerXX / SecondXX ufficiali;
- Other non è un super-candidato;
- holdout >=80%;
- guadagno >=5 p.p.;
- seat abs error <=200;
- publication-ready >=85% e <=140;
- push automatico, schedule e workflow_dispatch;
- cancel-in-progress:true.
