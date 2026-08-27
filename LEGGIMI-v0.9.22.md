# modello-UK v0.9.22 — solution search unificata territoriale (shadow)

## Obiettivo

La v0.9.22 mantiene congelato il miglior riferimento metodologicamente difendibile finora, la v0.9.15 (`501/632` collegi corretti nel benchmark 2024, errore seggi `166`), e prova in un solo run cinque famiglie di informazione aggiuntiva che erano assenti o incomplete nei tentativi precedenti.

Il gate di ricerca è **almeno 506/632 collegi corretti** e **seat absolute error <= 166**. La v0.9.22 resta comunque `shadow_only`: nessun risultato 2024 può attivare automaticamente il modello live.

## Lane A — Scozia: Westminster polling + Holyrood

Per la Scozia il modello non usa più i risultati locali STV aggregati a council come correzione principale. Usa invece due segnali parlamentari disponibili prima della generale:

- media finale dei sondaggi Westminster specifici per la Scozia;
- quota di constituency vote della precedente elezione di Holyrood come prior strutturale limitato.

I dati pre-elettorali sono fissati per 2015, 2017, 2019 e 2024. La forza del blend e il peso del prior Holyrood sono scelti solo usando 2015/2017/2019. Il target nazionale GB resta invariato: la trasformazione redistribuisce territorialmente il consenso e calcola il complemento necessario nel resto della Gran Bretagna.

## Lane B — target seats pubblici

La seconda lane usa liste di target seats pubblicate prima del voto:

- Liberal Democrats: target list 2017, 2019 e 2024;
- Labour in Scozia: target/marginal list 2017, 2019 e 2024.

La lista non determina direttamente il vincitore. Introduce soltanto una concentrazione di campagna limitata e rank-weighted nei collegi in cui il partito è ancora competitivo. Dopo la trasformazione il modello viene nuovamente raked al target nazionale, quindi non vengono creati voti aggiuntivi a livello GB.

Le intensità sono scelte esclusivamente sulle elezioni storiche 2017 e 2019. Il 2024 non seleziona alcun parametro.

## Lane C — calibratore generico dei marginali

La lane del calibratore dei marginali non è party-specific. È un classificatore logistico dei soli casi in cui il vincitore reale appartiene ai due partiti in testa nella previsione. Usa caratteristiche conoscibili prima del risultato:

- margine previsto e quote top-two;
- ruolo winner/runner-up nell'elezione precedente;
- paese/regione;
- identità dei due partiti in testa.

Il modello viene addestrato su 2015+2017; `C` e soglia sono scelti sul 2019. Se il 2019 non migliora, la lane viene automaticamente spenta (`meta_off`).

## Selezione combinata

Ogni lane può entrare nella combinazione finale soltanto se mostra un guadagno storico positivo senza regressioni materiali. La combinazione selezionata viene quindi applicata al riferimento v0.9.15 e **solo a quel punto** viene misurato il benchmark 2024.

Output principale:

- `data/solution-search-v0922.json`
- `data/v0915-reference-v0922.json`
- `data/backtest-v0922-solution-search.json`
- `data/bes-integrity-v0922.json`

Il report mostra anche il risultato 2024 di ciascuna lane separatamente, così è possibile identificare quale informazione produce l'eventuale guadagno.

## Safeguard

La GitHub Action blocca il deploy se non vengono riprodotti:

- canonico 2019: `583/632`, errore seggi `42`;
- canonico 2024: `494/632`, errore seggi `176`;
- v0.9.15 2019: `585/632`, errore seggi `42`;
- v0.9.15 2024: `501/632`, errore seggi `166`;
- incumbent routing: `0 / 0`.

Verifica inoltre che `uses_2024_for_parameter_selection=false` e che i layer sperimentali non siano applicati al live.

## Fonti metodologiche

- Electoral Calculus: predictor separato per la Scozia e tabelle final-campaign dei sondaggi Westminster scozzesi.
- Scottish Parliament / House of Commons Library: risultati constituency vote di Holyrood 2011, 2016 e 2021.
- Liberal Democrats: descrizione pubblica della strategia di concentrazione sui target seats nel 2024 e review della campagna 2019.
- Liste pre-elettorali di target/marginal seats pubblicate da Election Polling e stampa contemporanea.

## Politica di promozione

Anche se `research_gate=true`, la v0.9.22 resta shadow. Un'eventuale promozione richiede una revisione separata della provenienza dei dati, della stabilità storica e degli input necessari per trasferire lo stesso meccanismo al live 2026.


## Estensione unificata: England/Scotland/Wales + Brexit/Farage

Questa build include nello stesso run anche i due test emersi dalla revisione metodologica successiva:

1. **Country split England / Scotland / Wales.** Scozia e Galles usano target Westminster pubblicati prima del voto; England non usa il risultato elettorale ma viene ricavata come complemento necessario a mantenere esattamente il target GB. SNP e Plaid restano vincolati ai rispettivi totali GB, quindi il segnale serve soprattutto a distribuire Labour/Conservative/LD/Reform/Green fra le tre nazioni. La forza del blend viene scelta su 2015/2017/2019, mai sul 2024.
2. **Brexit/Farage geography.** Il modello scarica i risultati LAD delle Europee 2019 della House of Commons e costruisce una geografia completa del Brexit Party. Il modello Ridge viene calibrato sul voto GE2019 soltanto nei collegi dove il Brexit Party si presentò; negli altri collegi il dato è imputato e non trattato come 0. La calibrazione viene scelta con cross-validation 2019 e viene accettata solo se migliora un benchmark basato sul solo Leave 2016. Il 2024 serve solo per lo score finale.

Fonti principali: House of Commons FOI F23-289 (European Parliament 2019 LAD results); YouGov/ITV Cymru Wales/Cardiff University final Welsh Barometer polls 2015/2017/2019; Barn Cymru/YouGov 2024; Electoral Calculus final-campaign Scottish polling tables. Il fallback GitHub del dataset europeo è solo un backstop di rete e viene registrato nel report se utilizzato.

Il report `data/solution-search-v0922.json` contiene ora i rami `scotland_signal`, `country_split`, `brexit_geography`, `public_target_lists`, `winner_meta` e `combined_selected_pre2024`.

## Hotfix 27/08/2026 — unified solution search

Correzione del crash `IndexError: list index out of range` nel blocco di selezione delle lane sperimentali.
La ricerca mantiene la v0.9.22 e i medesimi gate: se una lane non produce alcun candidato storicamente ammissibile, viene selezionato un **no-op esplicito** per quella lane invece di indicizzare una lista vuota. Nessun parametro viene selezionato sui risultati 2024.

Inoltre il builder ora stampa il traceback completo su stderr in caso di errore, così un eventuale problema successivo espone immediatamente funzione e riga precise nella GitHub Action.

Marker sorgente: `V0922_HOTFIX="explicit-noop-candidate-fallback-and-traceback"`.
