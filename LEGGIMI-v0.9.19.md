# modello-uk v0.9.19 — validazione storica del targeting Liberal Democrat

Questa release resta **shadow research** e non modifica il modello live/canonico. Parte dal miglior riferimento pre-2024 disponibile, la v0.9.15 (`local_strength=0.25`, by-election a zero), che deve riprodurre esattamente 585/632 con errore seggi 42 nel 2019 e 501/632 con errore seggi 166 nel benchmark 2024.

## Ipotesi

La v0.9.18 ha mostrato che una concentrazione territoriale del voto Liberal Democrat può portare il benchmark 2024 oltre l'80%, ma il solo 2019 selezionava forza zero. La v0.9.19 testa una spiegazione indipendente e pre-elettorale: un collegio LD deve avere una **forza locale reale** prima di essere trattato come target. Il principio è coerente con il review elettorale Liberal Democrat del 2019, che indicava l'alta rappresentanza nel governo locale come una pre-condizione fondamentale per il target-seat status e criticava il fatto che nel 2019 fosse stata ignorata.

## Disciplina temporale

- **2017:** riferimento deterministico 2015→2017 basato sullo swing nazionale, senza modelli o calibrazioni selezionati sul risultato 2017. Dati locali: 5 maggio 2016 e 4 maggio 2017, cutoff 8 giugno 2017.
- **2019:** riferimento congelato v0.9.15. Dati locali disponibili prima del 12 dicembre 2019.
- **2024:** soltanto benchmark score-only dopo che la configurazione è stata scelta su 2017+2019.

Il risultato 2024 non sceglie forza, score floor, soglia di vantaggio locale o soglia di affidabilità.

## Sweep

120 configurazioni fisse:

- `strength`: 0.00, 0.20, 0.40, 0.60, 0.80
- `score_floor`: 0.50, 0.65
- `local_adv_floor`: -1.5, 0.0, 2.0, 4.0 punti
- `local_conf_floor`: 0.00, 0.35, 0.55

Una configurazione non può essere selezionata se compra il guadagno complessivo deteriorando materialmente uno dei due test storici. Il ranking usa prima il guadagno complessivo di collegi corretti 2017+2019, poi il miglioramento complessivo dell'errore seggi, con preferenza per interventi più conservativi in caso di parità.

## Output principali

- `data/ld-footprint-validation-v0919.json`
- `data/v0915-reference-v0919.json`
- `data/backtest-v0919-ld-footprint-validation.json`
- `data/bes-integrity-v0919.json`

Il report contiene anche la classifica ex-post 2024, ma è esplicitamente diagnostica e non può selezionare parametri.

## Gate di ricerca

La configurazione scelta solo su 2017+2019 viene considerata numericamente interessante se nel 2024 raggiunge:

- almeno **506/632** collegi corretti;
- `seat_abs_error_sum <= 166`.

Anche in caso di successo la release resta `approved:false`, `publication_ready:false`, `shadow_only:true`: l'ipotesi originaria è nata dall'audit 2024 e il benchmark non è un holdout pristine per la promozione.

## Salvaguardie

- baseline canonica invariata: 583/42 nel 2019 e 494/176 nel 2024;
- riferimento v0.9.15 invariato: 585/42 nel 2019 e 501/166 nel 2024;
- incumbent routing resta 0/0;
- regione esclusa dal target score;
- 2024 escluso dalla selezione;
- il layer LD non viene applicato al live;
- build fallita = workflow fallito prima del deploy.
