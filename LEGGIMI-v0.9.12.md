# Modello UK — v0.9.12 · latent Reform/Brexit geography (shadow)

## Obiettivo

La v0.9.11 ha mostrato un errore strutturale: i 39 seggi Reform previsti nel benchmark 2024 non coincidevano con nessuno dei 5 seggi realmente vinti. La causa plausibile è che la baseline 2019 tratta spesso lo zero Brexit/Reform come informazione territoriale, mentre in molti collegi — soprattutto conservatori — il Brexit Party non presentò un candidato.

La v0.9.12 testa quindi una sola ipotesi strutturale: **“non contestato” non equivale a “0% di potenziale locale”**.

## Cosa cambia

1. Il parser distingue la presenza del principale veicolo della famiglia Reform:
   - 2010/2015/2017: UKIP;
   - 2019: Brexit Party, separato dall'eventuale UKIP residuo;
   - 2024: Reform UK.
2. Viene stimato un prior geografico latente con una Ridge a penalità fissa (`alpha = 20`) usando **soltanto la distribuzione UKIP 2015**, quando il partito era largamente presente nel paese.
3. Il modello 2015 usa solo dati disponibili prima del 2024: quote degli altri partiti, turnout, vincitore/secondo, regione/paese e demografia/Census.
4. Il prior viene trasportato alle baseline 2019. Nei seggi in cui il principale veicolo Reform/Brexit non si presentò, viene conservata la quota osservata per il calcolo nazionale ma viene costruita una quota geografica latente separata.
5. Il prior latente entra nella conversione locale **solo** se contemporaneamente:
   - la copertura dei candidati Reform-family nella baseline è bassa;
   - il target nazionale Reform cresce in modo sostanziale.
6. Il raking continua a imporre il target nazionale. **Nessun voto storico non espresso viene aggiunto alla quota nazionale 2019.**

## Regola di attivazione fissata prima del benchmark

Non viene effettuato alcun tuning sul 2024.

- copertura: attivazione zero a `>= 75%`, piena a `<= 40%`;
- crescita Reform: attivazione zero fino a `+3 p.p.`, piena da `+8 p.p.`;
- fra i due estremi viene usata interpolazione lineare;
- attivazione finale = componente copertura × componente crescita.

Questi valori sono fissi nella v0.9.12 e il workflow li verifica.

## Salvaguardie metodologiche

- Il parser BES deve passare prima che venga stimato qualunque modello.
- Il donor latente è esclusivamente UKIP 2015.
- `uses_2024 = false` e `parameter_tuning = false` sono hard gate nel workflow.
- Il 2019 deve restare **583/632 corretti e 42 di errore seggi**: se cambia, il workflow fallisce.
- Il layer deve risultare inattivo nella validazione 2019.
- Il layer deve attivarsi nella transizione 2019→2024, altrimenti il workflow fallisce.
- Il routing v0.9.10 resta obbligatoriamente `0 / 0`.
- La diagnostica continua a separare predittori ex ante dagli outcome 2024.
- È aggiunto esplicitamente il confronto **false positive vs false negative**, necessario dopo il risultato 0 true positive della v0.9.11.

## Perché resta shadow anche se supera l'80%

La v0.9.12 nasce da un failure mode osservato nel benchmark 2024. Per questo motivo il 2024 non è più una validazione indipendente per questa ipotesi. Il codice calcola comunque il vecchio gate numerico per capire quanto migliora il candidato, ma:

- `approved = false` sempre;
- `publication_ready = false` sempre;
- `shadow_only = true` sempre.

Un eventuale superamento dell'80% è quindi **evidenza di sviluppo**, non autorizzazione al live.

## File prodotti dalla build

- `data/mrp-lite-model.json`
- `data/mrp-lite-live.json`
- `data/backtest-v0912-ref-latent-potential.json`
- `data/bes-integrity-v0912.json`
- `data/reform-diagnostics-v0912.json`

Nel report Reform sono presenti anche:

- `ref_primary_stood`;
- `ref_latent_share`;
- `ref_geo_share`;
- `ref_latent_activation`;
- confronto false positive / false negative.

## Cosa controllare dopo l'Action

I numeri decisivi saranno:

1. accuratezza 2024 e errore seggi complessivo;
2. seggi Reform previsti;
3. true positive / false positive / false negative Reform;
4. quanti dei 5 seggi Reform reali vengono finalmente intercettati;
5. quanti dei 39 falsi positivi Labour vengono eliminati;
6. eventuali nuovi errori introdotti su Conservative/Labour/LD;
7. conferma `2019 = 583/632`, errore seggi `42`;
8. valore dell'attivazione latente 2019→2024 e copertura candidati rilevata.

## Installazione

Sovrascrivere i file contenuti nello ZIP nella root del repository e avviare **Update and deploy UK model**.

Il workflow completo è incluso in `.github/workflows/update-data.yml` ed è fornito anche separatamente come `update-data-v0.9.12.yml`.

## Nota di isolamento del layer latente

Il prior latente Reform non aggiunge nuove variabili al feature set generale del modello residuale o del classificatore di contestability. Quando l'activation è 0, feature matrix e base prediction devono essere identiche alla v0.9.10; il workflow applica inoltre il regression guard 2019 (583 collegi corretti, errore seggi 42).
