# Modello Regno Unito — UI v0.9.56 / motore statistico v0.9.29

Nowcast indipendente delle prossime elezioni generali del Regno Unito. Il progetto combina polling nazionale, geografia elettorale constituency-by-constituency, uno stack MRP territoriale e simulazioni Monte Carlo per rispondere a una domanda precisa: **che cosa accadrebbe se si votasse oggi?**

La dashboard pubblica è disponibile su: https://angrisanidj.github.io/modello-uk/

## Stato attuale

- **Interfaccia:** v0.9.56.
- **v0.9.55 — cartogramma esagonale:** griglia discreta senza sovrapposizioni, packing locale e sagoma UK più leggibile.
- **v0.9.56 — export serie storica:** snapshot PNG senza crosshair e riepilogo corrente con valori, variazione a 30 giorni e partito in testa.
- **Motore statistico di produzione:** **v0.9.29**, congelato durante le modifiche esclusivamente frontend.
- **Seggi:** 650 totali; 632 collegi della Gran Bretagna modellati constituency-by-constituency e 18 seggi dell'Irlanda del Nord trattati separatamente.
- **Monte Carlo:** 50.000 simulazioni deterministiche in 50 blocchi asincroni da 1.000; il risultato corrente viene persistito dal workflow delle social card e riutilizzato finché il fingerprint degli input non cambia.
- **Output principale:** mediane dei seggi, intervalli centrali all'80%, probabilità di maggioranza/hung parliament e probabilità di vittoria per collegio.

Il progetto resta nella serie **0.x**: il passaggio a v1.0 richiede una qualità e una stabilità del backtest considerate sufficienti, non soltanto il completamento delle funzionalità dell'interfaccia.

## Cosa fa oggi

### Sondaggi e nowcast

- aggiorna automaticamente il polling average nazionale;
- usa snapshot prodotti dalla GitHub Action con fallback fail-soft;
- mostra ultimo sondaggio, partito in testa e quadro nazionale corrente;
- distingue esplicitamente la **media ponderata del modello** dalla media aritmetica dei **6 sondaggi più recenti**: soltanto la prima alimenta il nowcast;
- ricostruisce una **serie storica della media del modello** con la stessa half-life/lookback del topline live, con intervalli 90 giorni / 6 mesi / 1 anno / tutto;
- mostra variazioni a 7 e 30 giorni, volume delle rilevazioni, numero di istituti attivi, campione cumulato e istituti più presenti negli ultimi 30 giorni;
- mantiene separati il dato nazionale e la traduzione in seggi.

### Proiezione territoriale

- parte dalla baseline 2024 a livello di constituency;
- usa un **precision-weighted contemporary MRP geography stack** per i 632 seggi GB;
- integra la dimensione England / Scotland / Wales e le regioni inglesi nella lettura territoriale;
- tratta Northern Ireland con un modulo separato invece di forzarla nel modello GB;
- produce una mappa dello scenario territoriale rappresentativo e modalità dedicate a margine, probabilità e scenario utente.

### Monte Carlo e probabilità

- esegue 50.000 simulazioni;
- restituisce scenario centrale e intervallo 10°–90° percentile;
- calcola probabilità di maggioranza per i principali partiti e probabilità di hung parliament;
- calcola la probabilità di vittoria constituency-by-constituency;
- riutilizza prima il riepilogo Monte Carlo persistito nel repository e poi la cache locale; un nuovo calcolo parte soltanto quando il fingerprint degli input è cambiato;
- il pulsante **Aggiorna dati** confronta la fonte nazionale live con i dati caricati: se non trova variazioni dichiara esplicitamente che il Monte Carlo resta invariato; se trova una nuova rilevazione o una correzione, aggiorna il nowcast e autorizza un solo nuovo Monte Carlo per quel fingerprint.

### Dashboard e strumenti di lettura

- emiciclo della House of Commons;
- tabella dei seggi e probabilità;
- dashboard **“Quanto è aperta davvero la corsa”** con intervalli 80% dei seggi, probabilità di primo partito e battlefield dei collegi più contendibili;
- constituency explorer completo con ricerca, filtri per nazione/regione/partito/stato del seggio e ordinamento;
- evidenziazione sulla mappa dei collegi filtrati;
- dashboard regionale e seat flows;
- elenco dei collegi più marginali/incerti;
- export CSV dei risultati filtrati e dell'intero set dei 650 seggi;
- scenario builder nazionale deterministico, separato dal Monte Carlo di produzione;
- calcolatore esplorativo **“Quanto voto serve?”** per stimare la quota nazionale necessaria a Labour, Reform UK o Conservative per raggiungere un obiettivo di seggi nella proiezione mediana, con conferma finale su 50.000 simulazioni e pulsante per applicare il risultato allo scenario;
- coalition builder e combinazioni minime di maggioranza;
- export grafici e strumenti di condivisione social;
- **masthead editoriale professionale** con Union Jack, metadati principali del modello, gerarchia tipografica e spaziatura ripensate sul linguaggio visivo del modello Germania;
- **condivisioni ridisegnate** con icone vettoriali, rail verticale su desktop ampio e barra orizzontale compatta sui dispositivi più piccoli;
- **barra sticky del nowcast** differenziata per viewport: su desktop una fascia editoriale chiara e sottile con i primi due partiti e la soglia 326; su mobile un riepilogo minimale che appare solo tornando verso l’alto;
- **stato della vista sempre esplicito**: quando sono attivi filtri o uno scenario utente compare un indicatore persistente desktop/mobile che segnala che non si sta guardando il nowcast completo, mostra i filtri attivi e offre sempre “Torna al nowcast completo”;
- **export grafici modulari** 16:9 / 5:2 per proiezione dei seggi, mappa e andamento dei sondaggi, con condivisione nativa quando disponibile;
- **snapshot JSON** dello stato corrente (media, seggi, intervalli, probabilità e scenario rappresentativo) per uso editoriale/archivio;
- guida **“Come leggere il modello”**;
- pannello **“Verifica e interpreta le stime con un'IA”**, che costruisce un prompt dai dati già visibili nella dashboard senza modificare il modello o i suoi risultati;
- sezione **“Come si sta muovendo il voto”** con serie storica del topline, movimento recente e attività demoscopica.

## Motore statistico e validazione

La versione di produzione v0.9.29 promuove, dopo audit, il geography stack sviluppato nella v0.9.28. La promozione non effettua un nuovo tuning statistico: il candidate viene validato e poi promosso soltanto se supera i gate previsti.

Risultati congelati controllati dalla pipeline:

- **2019 — Geography Blend:** 609/632 vincitori corretti; errore assoluto complessivo sui seggi 14;
- **2024 — benchmark YouGov:** 578/632; errore seggi 56;
- **2024 — provider stack, cross-validation leave-one-region-out:** 584/632; errore seggi 44.

La misura 2024 del provider stack è una validazione regionale del weighting geografico e **non va descritta come un holdout elettorale puro e incontaminato**. La forza geografica storica selezionata dal modello è **0,875**, scelta sul 2019. La pipeline verifica esplicitamente che il 2024 non entri nella selezione di quel parametro storico.

I **topline nazionali dei provider MRP esterni non vengono importati nel modello**. Le informazioni esterne entrano nel geography stack secondo le regole dichiarate e con controlli espliciti contro leakage e regressioni.

## Promotion gate v0.9.29

La GitHub Action:

1. aggiorna i dati elettorali e territoriali;
2. costruisce il modulo Northern Ireland;
3. ricostruisce il candidate v0.9.28 congelato;
4. verifica integrità, copertura, backtest, cross-validation e stabilità 2026;
5. impedisce la promozione se i risultati storici congelati regrediscono o se vengono violate le invarianti metodologiche;
6. promuove il candidate a **v0.9.29 production live**;
7. verifica che la promozione non abbia mutato le proiezioni constituency-by-constituency o il target GB;
8. pubblica GitHub Pages soltanto dopo il completamento della pipeline.

## Shadow MRP watcher

La pipeline contiene anche un controllo **shadow-only** per individuare eventuali nuovi MRP Westminster pubblicati da:

- More in Common;
- YouGov;
- Focaldata.

Il watcher può segnalare un nuovo aggiornamento, ma la policy è **detect and notify, never auto-adopt**: una nuova fonte non viene mai inserita automaticamente nel modello di produzione.

## Northern Ireland

I 18 seggi nordirlandesi sono tenuti separati dal geography stack della Gran Bretagna. La dashboard li ricompone poi nel totale dei 650 seggi della House of Commons. Anche gli export CSV completi mantengono le colonne dei partiti NI necessarie a rappresentare correttamente questi collegi.

## Fonti principali

- Sondaggi: https://en.wikipedia.org/wiki/Opinion_polling_for_the_next_United_Kingdom_general_election
- MediaWiki API: https://en.wikipedia.org/w/api.php
- House of Commons Library, General Election 2024: https://commonslibrary.parliament.uk/research-briefings/cbp-10009/
- Risultati per candidato 2024: https://researchbriefings.files.parliament.uk/documents/CBP-10009/HoC-GE2024-results-by-candidate.csv
- UK Parliament election results: https://electionresults.parliament.uk/
- Democracy Club: https://democracyclub.org.uk/
- ONS / Open Geography Portal: https://geoportal.statistics.gov.uk/

Le fonti MRP esterne sono usate e validate dal relativo geography stack secondo quanto dichiarato nei file diagnostici e negli audit di promozione inclusi in `data/`.

## Struttura principale del repository

```text
modello-uk/
├── index.html
├── styles.css
├── styles-v0935.css
├── styles-v0936.css
├── styles-v0937.css
├── styles-v0938.css
├── styles-v0939.css
├── styles-v0940.css
├── styles-v0941.css
├── styles-v0942.css
├── styles-v0943.css
├── styles-v0944.css
├── styles-v0945.css
├── styles-v0946.css
├── styles-v0947.css
├── styles-v0948.css
├── styles-v0949.css
├── styles-v0951.css
├── styles-v0952.css
├── styles-v0953.css
├── styles-v0954.css
├── styles-v0955.css
├── map-performance.css
├── scripts/
│   ├── app.js
│   ├── map-performance.js
│   ├── interpretation.js
│   └── generate-social-cards.mjs
├── data/
│   ├── polls.json
│   ├── constituencies-2024.json
│   ├── constituencies-2024.geojson
│   ├── mrp-lite-live.json
│   ├── promotion-audit-v0929.json
│   └── ...
├── tools/
│   ├── build_data.py
│   ├── build_ni.py
│   ├── build_mrp_lite.py
│   ├── build_mrp_geography_bridge.py
│   ├── promote_mrp_stack.py
│   ├── check_mrp_updates.py
│   ├── review_poll_updates.py
│   └── ...
├── share-x.html / share-threads.html / share-facebook.html / ...
├── social-card-uk-v2.png
├── social-card-uk-instagram-v2.png
├── .github/workflows/
│   ├── update-data.yml
│   ├── update-social-cards.yml
│   └── review-poll-updates.yml
└── requirements.txt
```

## Deploy e aggiornamento dati

La GitHub Action `Update and deploy UK model` può essere avviata manualmente, parte anche su push a `main` ed è programmata quotidianamente. La pipeline aggiorna e committa automaticamente soltanto i file sotto `data/` quando esistono modifiche effettive, quindi esegue il deploy su GitHub Pages.

Un workflow leggero `Review UK polling updates` controlla ogni tre ore i feed nazionali e subnazionali senza riscrivere i dataset. Se rileva una variazione effettiva nelle rilevazioni, avvia `Update and deploy UK model`; resta inoltre il rebuild giornaliero di sicurezza e l’avvio manuale.

Per una modifica esclusivamente frontend è sufficiente pubblicare i file dell'interfaccia; **non è necessario ritoccare il motore statistico**.

## Nota sulla lettura dei risultati

La dashboard è un **nowcast**, non una previsione certa del risultato finale delle prossime elezioni. Il numero centrale dei seggi va letto insieme agli intervalli di probabilità, alla distribuzione Monte Carlo e alla geografia dei collegi. Lo scenario personalizzato dell'utente è uno strumento esplorativo deterministico e non modifica il modello di produzione.


## UI v0.9.46

La v0.9.46 interviene sul passaggio mobile dopo la verifica su dispositivo reale. La barra fissa a tre card viene sostituita da un riepilogo molto più sottile, opaco e a tutta larghezza: compare solo quando si torna verso l’alto e si nasconde durante lo scorrimento verso il basso, oltre a scomparire automaticamente dopo una breve pausa. Mostra soltanto i primi due partiti per seggi e la soglia statica di 326 seggi; la probabilità di Parlamento senza maggioranza non compare più nella barra e non produce quindi il passaggio tardivo da “…” a “100%”.

La media storica usa un viewBox più alto sui telefoni, mantenendo invariata la serie e la logica del grafico. La barra della mappa mantiene `−`, livello di zoom, `+`, `Reset` e `Filtrati`; quando esiste un filtro attivo compare inoltre `Rimuovi filtri` (`× Filtri` su mobile), che azzera direttamente dalla mappa i filtri dei collegi e ripristina la vista completa.

## UI v0.9.45

La v0.9.45 rifinisce il passaggio mobile sulla base della verifica reale su telefono. La barra sticky diventa una card flottante color grafite, con tre celle compatte e numeri separati in capsule; il riquadro “Parlamento senza maggioranza” torna coerente con il tema scuro; i comandi PNG/Condividi sono trattati come utility compatte e non come call-to-action principali. Sulla mappa mobile restano contemporaneamente disponibili `−`, livello di zoom, `+`, `Reset` e `Filtrati`.

### Verifica manuale degli aggiornamenti

- **Aggiorna dati** interroga direttamente la fonte nazionale MediaWiki e confronta le rilevazioni recenti con quelle già caricate;
- se non trova alcuna novità mostra chiaramente **“Nessun nuovo sondaggio trovato · Monte Carlo non ricalcolato”**;
- se trova una nuova rilevazione o una correzione, aggiorna media e proiezione centrale e avvia un nuovo Monte Carlo da 50.000 simulazioni in 50 blocchi asincroni da 1.000;
- il ricalcolo manuale è autorizzato solo dopo una variazione effettiva del contenuto dei sondaggi e viene riutilizzato dalla cache se quel fingerprint è già stato simulato;
- la review server-side ogni tre ore resta l'autorità che rende persistenti dataset, Monte Carlo e social card per tutti i visitatori.

### Review automatica degli aggiornamenti

- `.github/workflows/review-poll-updates.yml` controlla ogni tre ore i contenuti delle rilevazioni nazionali e subnazionali;
- `tools/review_poll_updates.py` confronta le nuove fonti con gli snapshot correnti ignorando timestamp e metadati di build;
- solo se le rilevazioni sono cambiate viene avviato il workflow di produzione completo;
- il rebuild giornaliero di sicurezza resta separato.

### Monte Carlo persistito

- il calcolo resta di **50.000 simulazioni**, eseguite in **50 blocchi asincroni da 1.000** per non bloccare l'interfaccia;
- il normale caricamento/refresh della pagina riutilizza `data/monte-carlo-current.json` o la cache e non duplica la simulazione;
- `update-social-cards.yml` salva anche `data/monte-carlo-current.json`;
- una simulazione nel browser pubblico può partire soltanto dopo una richiesta esplicita **Aggiorna dati** che abbia trovato un contenuto di polling effettivamente diverso;
- il workflow social continua a produrre e persistere il risultato autorevole dopo l'aggiornamento server-side.

### Manutenzione GitHub Actions

I workflow restano sulle release delle Action basate su Node.js 24 (`cache@v5`, `configure-pages@v6`, `upload-pages-artifact@v5`, `deploy-pages@v5`, `setup-node@v6` nel workflow social).


## v0.9.47 — verifica sondaggi e filtri mappa

- Corretto il parser della verifica manuale MediaWiki: riferimenti bibliografici rimossi e campioni con separatore delle migliaia letti correttamente.
- Nuovi sondaggi, correzioni e rimozioni sono distinti e mostrati puntualmente prima/durante il ricalcolo.
- Il Monte Carlo non parte se il controllo live restituisce campioni manifestamente implausibili.
- I filtri attivi dei collegi sono ora visibili sopra la mappa e rimovibili singolarmente.
- Motore statistico invariato.


## UI v0.9.48 — barra desktop e soglia di maggioranza

- Aggiunta una barra sticky desktop ispirata alla soluzione del modello Germania: fondo chiaro, richiamo UK molto sottile, primi due partiti per seggi e soglia 326. Compare solo dopo aver superato l’intestazione ed è navigabile verso proiezione e probabilità di governo.
- La barra desktop mostra sempre il **nowcast corrente**, non lo scenario personalizzato.
- Nello scenario personalizzato è disponibile il nuovo strumento **“Quanto voto serve per arrivare alla maggioranza?”** con comandi rapidi per Labour, Reform UK e Conservative e obiettivo modificabile.
- Gli altri partiti vengono ridimensionati proporzionalmente alla media corrente mentre varia la quota del partito scelto.
- La ricerca usa prima una fase rapida per individuare la zona della soglia; il valore finale viene confermato con **50.000 simulazioni asincrone in blocchi da 1.000**, senza sovrascrivere o riutilizzare il Monte Carlo di produzione.
- Il risultato riporta quota nazionale indicativa, differenza dalla media corrente, mediana dei seggi, intervallo centrale 80% e probabilità di raggiungere l’obiettivo; può essere applicato con un clic allo scenario deterministico.
- `calculateAverage`, `buildCentral`, `prepareSeatModel`, `buildCustomScenario` e `runMonteCarlo` di produzione restano invariati.


## UI v0.9.51 — banner mobile e notifiche refresh

- Su mobile gli avvisi `Vista filtrata` / `Scenario personalizzato` diventano una striscia compatta a due righe: stato + ritorno immediato al nowcast nella prima riga, filtri/scenario nella seconda.
- Il dettaglio verboso viene nascosto sul telefono per evitare card troppo alte; resta disponibile su desktop.
- Gli stati della verifica sondaggi sono resi più evidenti con codifica visiva coerente: controllo, variazione trovata, completato, nessuna variazione, errore.
- La riga di stato del refresh occupa tutta la larghezza su mobile e il pannello dettaglio rilevazioni ha contrasto e gerarchia tipografica maggiori.
- Nessuna modifica al motore statistico o alle simulazioni Monte Carlo.

## v0.9.52 — allineamento sticky e emiciclo scenario
- Allineamento verticale uniforme del blocco `326 MAGGIORANZA` nella sticky bar desktop.
- Quando viene calcolato uno scenario personalizzato, l'emiciclo principale e la relativa legenda dei seggi passano subito ai totali dello scenario.
- La barra di contesto segnala `Emiciclo` come vista alternativa attiva.
- Disattivando lo scenario dalle viste o tornando al nowcast completo, emiciclo e legenda tornano immediatamente ai valori del nowcast/Monte Carlo di produzione.
- Nessuna modifica alle funzioni statistiche o al Monte Carlo di produzione.
