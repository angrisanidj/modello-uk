# Floor e Geometry audit — 31 agosto 2026

## Esito

**La migrazione della geometria nazionale da shock additivi censurati + closure a logistic-normal in coordinate ILR non viene promossa. Il motore statistico di produzione resta invariato.**

La decisione non deriva da un esperimento incompleto o da una difficoltà di calibrazione. La sostituzione è stata portata fino a una parametrizzazione logistic-normal capace di riprodurre con precisione numerica la media nazionale e la covarianza target; nonostante questo, le probabilità constituency-by-constituency restano materialmente diverse dalla produzione.

L'invariante rilevante del modello vive quindi nella **propagazione territoriale della distribuzione nazionale**, non nei soli primi due momenti delle quote nazionali.

## Anchor e identità sperimentale

Il ciclo è ancorato a:

- commit `fcec1741c024694466bb1b02076c270798581df7`;
- tag diagnostico `geometry-ab-20260831-base`;
- fingerprint `uk-v0931-20260827-constituency-explorer-scenario-builder:2282281613`;
- seed key `uk-v0931-20260827-constituency-explorer-scenario-builder:2802926631`;
- 50.000 simulazioni per ciascun braccio A/B;
- stesso target nazionale, stessa scala marginale, stesso materiale del seed e stesso downstream RNG;
- nessuna modifica ai parametri geografici, regionali/locali, al centro del nowcast o alla conversione in seggi.

Nel secondo A/B i parametri logistic-normal sono stati risolti **prima** dell'esecuzione e congelati tramite SHA-256:

`bf14f6f99c06c03ebd9b41a0f138ba8fe3855bf2db6106e490d9ef16d350a6dd`

Questo impedisce per costruzione una calibrazione sui 50.000 draw usati per la valutazione.

## 1. Floor audit: una guardia numerica diventata parte attiva del modello

La produzione nazionale applica, prima della closure:

```js
drawn[p] = Math.max(.05, target[p] + normalApprox(rng) * sigma);
```

Questa operazione è **censura**, non truncation: tutti i valori grezzi inferiori a `0,05` vengono collassati sullo stesso valore pre-closure.

Sul target reale dell'anchor:

- PC target `1,041878%`;
- σ grezza PC `0,525 p.p.`;
- α PC `-1,889`;
- probabilità teorica Box-Muller di colpire il floor `2,9426%`;
- floor hit osservati PC `1.439 / 50.000`;
- bias teorico pre-closure da censura `+0,005967 p.p.`;
- σ PC pre-closure `0,525000 → 0,511430 p.p.` per effetto della censura.

Altri floor hit Box-Muller osservati:

- RB `134 / 50.000`;
- Other `90 / 50.000`;
- SNP `41 / 50.000`.

Restore Britain resta escluso dalla conversione diretta `SEAT_MODEL_PARTIES`, ma il suo shock influenza comunque indirettamente tutte le quote GB attraverso la closure.

### Interpretazione corretta del floor

Il `2,94%` di PC **non diventa un atomo a 0,05% nella quota nazionale finale**. L'atomo è nel valore pre-closure. Dopo la rinormalizzazione:

\[
p_{PC}=100\frac{0,05}{\sum_j Y_j}
\]

e il denominatore continua a variare.

Neppure gli esiti territoriali diventano identici: gli altri shock nazionali, regionali e locali restano liberi.

La proprietà rilevante è invece questa:

> **Nel 2,94% circa delle simulazioni PC perde il proprio grado di libertà nazionale verso il basso: tutti i valori grezzi sotto soglia collassano sullo stesso punto pre-closure.**

Una logistic-normal strettamente positiva conserva invece una gradazione continua nella coda inferiore. Le due costruzioni hanno quindi geometrie condizionali diverse, che la propagazione territoriale riesce a distinguere.

Il floor non può più essere trattato come una semplice salvaguardia numerica: è diventato accidentalmente una componente attiva della distribuzione effettiva del modello.

## 2. Floor audit analitico

La distribuzione censurata Box-Muller è stata confrontata con la teoria esatta della normale censurata. Il controfattuale legacy Irwin-Hall è stato confrontato con la propria CDF esatta, non con una normale approssimata.

Nessun conteggio di floor con almeno 5 hit teorici si è discostato dalla teoria di oltre 4 errori standard.

Per la closure, il Jacobiano costruito attorno alle medie censurate ha riprodotto la covarianza osservata con:

- errore massimo sulle σ marginali `0,010789 p.p.`;
- errore massimo assoluto sulle covarianze `0,045395 (p.p.)²`;
- Corr(Lab, Ref) nazionale `-0,2653` teorica locale contro `-0,2695` osservata.

La correlazione nazionale degli errori non va confusa con la correlazione dei **totali di seggi** Lab-Ref, molto più negativa per effetto della competizione sugli stessi collegi.

## 3. Geometry A/B #1 — FAIL

### Arm A

Produzione:

**Box-Muller → shock additivi → censura 0,05 → closure.**

### Arm B

Prima candidata:

**Box-Muller → proiezione 9→8 → logistic-normal ILR → softmax**, senza floor.

Il target di covarianza era il controfattuale additivo **non censurato** dopo closure:

\[
C_u = J D_{nom} J^\top
\]

Per PC il target comparabile post-closure era `0,522222 p.p.`, non la σ grezza `0,525`.

Passavano centro, struttura nazionale, indicatori parlamentari aggregati e positività.

Fallivano scala dei piccoli partiti e `seatProb`.

Errore relativo sulla σ:

- SNP `2,533%`;
- PC `5,072%`;
- RB `2,358%`;
- Other `2,548%`.

`seatProb`:

- Δ assoluta media `0,0629 p.p.`;
- Δ assoluta massima `8,660 p.p.`;
- 18 celle oltre `5 p.p.`;
- 8 collegi con leader probabilistico diverso.

Il preflight latente risultò inizialmente `NaN` per un bug esclusivamente diagnostico (`latentY.n` non incrementato). La covarianza latente è stata ricostruita dai raw già prodotti:

- U max errore diagonale `0,012089`;
- U max off-diagonal `0,010700`;
- Y covariance relative error `1,242%`;

quindi **latent implementation PASS**. Il bug diagnostico non modifica il verdetto.

## 4. Spike di secondo ordine — ipotesi non supportata

È stata testata, senza nuovo Monte Carlo, l'ipotesi che il fallimento di scala fosse spiegato dal termine di secondo ordine della softmax:

\[
Cov_2(g_i,g_j)
=
J_i\Sigma J_j^\top
+\frac12 tr(H_i\Sigma H_j\Sigma)
\]

Pre-registrazione:

- PC/RB/Other/SNP devono migliorare tutti;
- il massimo errore sulle σ deve diminuire di almeno il 50%;
- per Lab/Con/Ref la variazione dell'errore deve restare sotto `0,005 p.p.`.

Risultato:

- tutti e quattro i piccoli migliorano;
- massimo errore σ `0,082205 → 0,054200 p.p.`, riduzione `34,07%`: **FAIL** sul gate 50%;
- Lab/Con/Ref peggiorano di circa `0,0062–0,0064 p.p.`: **FAIL** sul gate di stabilità;
- errore Frobenius sulla covarianza: miglioramento `25,90%`.

Verdetto preregistrato: **HYPOTHESIS_NOT_SUPPORTED**.

Conclusione: media e covarianza della logistic-normal non possono essere trattate come due problemi sequenziali indipendenti.

## 5. Joint moment matching — logistic-normal numericamente fattibile

È stato risolto congiuntamente:

\[
E[p(\mu,\Sigma)] = p_{target}
\]

\[
Cov[p(\mu,\Sigma)] = C_u
\]

In 9 componenti composizionali esistono 8 gradi di libertà della media e 36 elementi indipendenti della covarianza: **44 condizioni contro 44 parametri liberi** della normale ILR.

Il solve è stato verificato con cubatura sparse Smolyak-Gauss-Hermite e con una base ILR ruotata indipendentemente.

Risultato:

- residuo level 4 `1,65×10⁻10`;
- rango Jacobiano `44/44`;
- condition number Jacobiano `108,152`;
- stabilità level 4→5 PASS;
- invarianza fisica rispetto alla base ILR ruotata PASS;
- max errore level 5 sulla media `7,9×10⁻8 p.p.`;
- max errore level 5 sulle σ `1,77×10⁻6 p.p.`;
- max errore level 5 sulle correlazioni `3,81×10⁻6`.

Verdetto: **LOGISTIC_NORMAL_FEASIBLE**.

Questo stabilisce la fattibilità numerica locale del matching dei momenti; non prova unicità globale e non risolve automaticamente la propagazione territoriale.

## 6. Geometry A/B #2 — FAIL / NOT PROMOTED

Il secondo A/B usa i parametri joint moment-matched congelati prima dell'esecuzione.

Il gate relativo sulla scala è stato deliberatamente **irrigidito all'1%** rispetto al 3% discusso nel disegno iniziale. Nessun gate è stato allargato.

Tutti i gate nazionali passano:

- latent implementation PASS;
- centro PASS;
- scala PASS per tutti i 9 partiti;
- struttura nazionale PASS, max `|Δcorr| = 0,0102`;
- positività PASS.

PC passa da un errore relativo di scala del `5,072%` nel primo A/B a `0,878%` nel secondo.

Anche il gate parlamentare aggregato passa:

- P(Lab primo) `71,90% → 72,23%`, Δ `+0,33 p.p.`;
- Hung `96,08% → 95,64%`, Δ `-0,44 p.p.`;
- Labour ≥326 `3,81% → 4,22%`;
- Labour ≥ soglia operativa `4,54% → 4,92%`.

### `seatProb`

| metrica | Geometry #1 | Geometry #2 |
|---|---:|---:|
| Δ assoluta media | 0,0629 p.p. | 0,0616 p.p. |
| Δ assoluta massima | 8,660 p.p. | 8,376 p.p. |
| celle >5 p.p. | 18 | 18 |
| leader probabilistico diverso | 8 | 7 |

La calibrazione nazionale di PC migliora di circa un fattore sei, mentre la Δ massima `seatProb` migliora soltanto di circa il 3%.

Questo separa le due cause: **la calibrazione nazionale dei piccoli partiti era un problema reale del primo A/B, ma non era la causa principale della divergenza territoriale.**

## 7. Decisione di produzione

**Geometry migration: NOT PROMOTED.**

La produzione resta:

> **Box-Muller → shock additivi → censura 0,05 → closure.**

Non viene mantenuta per inerzia. La sostituzione logistic-normal è stata costruita, calibrata congiuntamente e testata; pur preservando con precisione i primi due momenti nazionali, non preserva l'invariante operativo richiesto a livello constituency.

Non viene eseguito un Geometry #3. Aggiungere skewness matching, momenti superiori o ulteriori parametri alla logistic-normal significherebbe progressivamente arricchire la nuova famiglia per ricostruire la vecchia distribuzione, senza una giustificazione empirica indipendente.

### Risultato riutilizzabile

> **Il floor 0,05 non è più soltanto una salvaguardia numerica. La censura che introduce è diventata parte della distribuzione effettiva del modello e produce effetti materialmente rilevanti dopo la propagazione territoriale. Preservare i primi due momenti delle quote nazionali non preserva questi effetti.**

Più in generale:

> **L'invariante rilevante del modello vive nella propagazione territoriale, non nelle sole quote nazionali.**

## 8. Conseguenza per la roadmap Structure

Il successivo esperimento sulla **struttura** dell'incertezza nazionale non può essere progettato con il solo obiettivo di preservare i momenti nazionali o di mantenere invariata ogni `seatProb`.

Se vengono introdotte deliberatamente nuove correlazioni nello spazio log-ratio, alcune variazioni territoriali saranno parte dell'effetto cercato. Il preregistro dovrà quindi distinguere:

1. **conseguenze territoriali causali e attese** dalla correlazione introdotta;
2. **effetti collaterali non desiderati**;
3. controlli di stabilità sugli output parlamentari che non devono essere modificati dal meccanismo testato.

La validazione di Structure è quindi un problema **territoriale**, più complesso del matching di momenti nazionali. Questo audit non autorizza alcuna modifica alla struttura di correlazione di produzione.

## 9. Stato finale del ciclo

1. Floor audit — **COMPLETE**.
2. Geometry A/B #1 — **FAIL**.
3. Second-order explanation spike — **HYPOTHESIS_NOT_SUPPORTED**.
4. Joint moment feasibility — **LOGISTIC_NORMAL_FEASIBLE**.
5. Geometry A/B #2 — **FAIL / NOT PROMOTED**.
6. Produzione — **INVARIATA**.

Il risultato negativo chiude una strada di sviluppo con evidenza sperimentale invece di lasciarla aperta come ipotesi non verificata.
