# modello-UK v0.9.14 — place + regradient sweep

## Obiettivo

La v0.9.14 cambia bersaglio dopo il fallimento delle correzioni Reform-specifiche delle v0.9.10–0.9.13.

Il candidato canonico resta **congelato** alla v0.9.10 equivalente:

- 2019: **583/632**, errore seggi **42**;
- benchmark 2024: **494/632**, errore seggi **176**;
- Reform 2024: **39 previsti**, **5 reali**.

La release è **shadow research only** e non può attivare il nuovo layer sul sito.

## Perché questa strada

Una ricerca sulle metodologie UK pubbliche e accademiche ha indicato due problemi che non avevamo ancora testato in modo mirato:

1. **attenuation / gradient bias**: gli MRP e i modelli regolarizzati possono rendere troppo piatta la distribuzione territoriale dei voti. Focaldata ha descritto l'uso di *unwinding/regradienting* e ha mostrato che nel 2024 la correzione spostava decine di seggi Conservative senza cambiare il totale nazionale;
2. **place / spatial residuals**: lavori accademici sulle elezioni britanniche 2019 e 2024 trovano struttura spaziale residua anche dopo demografia, risultato precedente, incumbent, runner-up e marginalità.

Fonti principali consultate:

- Focaldata, *Focaldata / Prolific UK General Election MRP*: https://www.focaldata.com/blog/focaldata-prolific-uk-general-election-mrp
- Focaldata, *Review into our performance at the 2024 UK general election*: https://www.focaldata.com/blog/review-into-our-performance-at-the-2024-uk-general-election
- YouGov, *YouGov MRP shows Labour would win 1997-style landslide...*: https://yougov.co.uk/politics/articles/48371-yougov-mrp-shows-labour-would-win-1997-style-landslide-if-election-were-held-today
- More in Common, giugno 2024 MRP: https://www.moreincommon.org.uk/research/the-conservative-party-on-course-for-their-worst-defeat-in-over-a-century/
- Horan, Brunsdon & Domijan (2024), *A Multilevel Spatial Model to Investigate Voting Behaviour in the 2019 UK General Election*: https://link.springer.com/article/10.1007/s12061-023-09563-6
- Horan, Domijan & Brunsdon (2025/2026), *Incorporating varying degrees of spatial cohesion... UK General Election 2024*: https://academic.oup.com/jrsssc/article/75/2/526/8307260
- UK Elections, backtest pubblico GE2024: https://ukelections.co.uk/data-quality/
- Electoral Calculus, *Shaped Strong Transition Model*: https://www.electoralcalculus.co.uk/blogs/Analysis_shapedstm.html

## Cosa testa la v0.9.14

### 1. Regradienting storico

La correzione non aumenta genericamente la dispersione: modifica **soltanto la componente della previsione locale correlata alla forza del partito nell'elezione precedente**.

Per ogni partito eleggibile (Lab, Con, LD, Green, SNP, Plaid):

- misura il gradiente `quota elezione precedente -> quota elezione successiva` nelle transizioni storiche disponibili;
- pesa maggiormente le transizioni con swing nazionale simile e quelle più recenti;
- confronta quel gradiente con quello della previsione corrente;
- corregge la pendenza con strength prefissata;
- esegue nuovamente il raking, quindi **la quota nazionale target resta invariata**.

Reform è esclusa dal regradienting storico perché la geografia 2019 è contaminata dal patto di non-concorrenza Brexit Party/Conservative già diagnosticato nelle versioni precedenti.

### 2. Persistenza dei residui di luogo/competizione

Questa non è una falsa implementazione ICAR. È volutamente un proxy a bassa dimensionalità trasferibile anche attraverso il cambio dei confini 2019→2024.

Dopo un'elezione già osservata, il modello conserva residui shrunk per:

- regione;
- partito vincitore nella baseline;
- runner-up nella baseline;
- fascia del margine precedente: `<2`, `2–5`, `5–10`, `10–20`, `>=20`.

La chiave è quindi:

`regione | winner precedente | runner-up precedente | fascia margine`

Gli effetti di celle piccole vengono fortemente shrinkati verso zero.

## Disciplina temporale

Questa è la parte più importante.

1. Il modello canonico produce una previsione **onesta del 2017** usando solo dati precedenti.
2. I residui di quella previsione costruiscono il profilo di luogo/competizione disponibile per il 2019.
3. La griglia v0.9.14 viene ordinata **esclusivamente sul 2019**.
4. Solo dopo la selezione vengono calcolati i residui 2019 e trasportati al benchmark 2024.
5. Il 2024 viene aperto esclusivamente per assegnare il punteggio finale.

Il report deve avere:

`uses_2024_for_parameter_selection = false`

## Griglia

Sono testate **54 configurazioni prefissate**:

- regradient: `0, 0.25, 0.50, 0.75, 1.00, 1.25`;
- residuo regione: `0, 0.50, 1.00`;
- residuo competizione: `0, 0.50, 1.00`.

La configurazione `(0,0,0)` coincide con il candidato canonico; quindi il selettore 2019 non può scegliere razionalmente una configurazione con score peggiore della baseline.

## Nuovi output

- `data/error-structure-v0914.json`
  - matrice completa predicted→actual del 2024;
  - tutti i **138 collegi canonici sbagliati**;
  - errori per regione;
  - errori per margine previsto;
  - top-3 previsto e quote reali per ogni errore.

- `data/place-regradient-sweep-v0914.json`
  - 54 configurazioni ordinate sul 2019;
  - configurazione scelta **prima di guardare il 2024**;
  - benchmark 2024 della configurazione scelta;
  - benchmark 2024 dei primi 12 candidati già pre-selezionati dal 2019.

- `data/backtest-v0914-place-regradient.json`
- `data/bes-integrity-v0914.json`
- `data/mrp-lite-model.json`
- `data/mrp-lite-live.json`

## Gate di ricerca

Il nuovo candidato è numericamente interessante soltanto se nel 2024 ottiene contemporaneamente:

- **>=506/632** collegi corretti (>=80%);
- errore seggi **<=176**.

Anche se passa, **non viene promosso**: la v0.9.14 resta shadow e richiede una successiva validazione indipendente.

## Safeguard

Il workflow blocca il deploy se:

- il bundle contiene versioni miste;
- BES integrity non passa;
- il candidato canonico cambia da 583/42 nel 2019 o 494/176 nel 2024;
- la matrice degli errori non riconcilia esattamente 494 corretti + 138 errati;
- il tuner non contiene esattamente 54 configurazioni;
- compare qualunque uso del 2024 per la selezione dei parametri;
- il layer shadow tenta di diventare `approved` o `publication_ready`.

## Limiti consapevoli

YouGov/Focaldata dispongono di grandi panel individuali in campagna; questa v0.9.14 non finge di ricostruire quell'informazione da dati aggregati. Inoltre il layer “place” non è un ICAR a contiguità: se il proxy mostra un segnale forte ma insufficiente, il passo successivo naturale sarà una vera struttura di vicinato usando le geometrie storiche 2010–2019 e 2024.
