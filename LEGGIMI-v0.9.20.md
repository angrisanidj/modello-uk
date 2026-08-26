# modello-uk v0.9.20 — Scotland + Conservative/Labour sweep

Questa versione è **shadow research** e non modifica il modello live approvato. Parte dal miglior riferimento metodologicamente difendibile emerso finora, la v0.9.15:

- validazione 2019: **585/632**, errore seggi **42**;
- benchmark 2024: **501/632**, errore seggi **166**.

## Obiettivo

La v0.9.17 aveva individuato, oltre al blocco Reform già ampiamente testato, due grandi famiglie residue:

- **SNP previsto → Labour reale** in Scozia;
- **Conservative previsto → Labour reale**.

La v0.9.20 testa entrambe nello stesso run, ma le mantiene statisticamente separate.

## Metodo

Il nuovo layer è una correzione **pairwise e simmetrica** guidata esclusivamente da informazioni pre-elettorali:

- quote previste prima del layer;
- competitività prevista del collegio;
- forza relativa nelle elezioni locali Democracy Club;
- affidabilità/copertura del segnale locale.

Il layer interviene solo se i due partiti della coppia sono i primi due nella previsione e il segnale locale favorisce il partito attualmente secondo. La correzione può quindi operare in entrambe le direzioni e non codifica il vincitore reale 2024.

### Scotland

Coppia `SNP ↔ Labour`, esclusivamente nei collegi scozzesi.

### Conservative/Labour

Coppia `Conservative ↔ Labour`, esclusivamente in Inghilterra e Galles. La Scozia è esclusa da questo layer per evitare sovrapposizioni con l'esperimento SNP/Lab.

## Selezione temporale

Ogni layer viene selezionato **solo su 2017 + 2019**. Per il 2017 si usa un riferimento deterministico 2015→2017 che non ha visto il risultato 2017; per il 2019 si usa il riferimento v0.9.15 congelato.

Dopo la selezione indipendente, una shortlist dei migliori candidati storici dei due layer viene combinata e selezionata ancora esclusivamente su 2017+2019. Solo dopo il lock dei parametri viene aperto il benchmark 2024.

Il 2024 non può selezionare alcun parametro.

## Griglia

Per ciascun layer:

- strength: `0.00, 0.20, 0.40, 0.60`;
- margin cap: `10, 20, nessun cap` punti;
- local-advantage floor: `0, 2` punti;
- local-confidence floor: `0.35` fisso.

Totale: **24 configurazioni per layer**. La combinazione usa i migliori **6 candidati storicamente ammissibili** per ciascun layer, quindi fino a **36 combinazioni**.

## Gate

Il riferimento v0.9.15 deve essere riprodotto esattamente. Il nuovo research gate richiede al candidato selezionato storicamente:

- almeno **506/632** collegi corretti nel benchmark 2024;
- errore seggi **≤166**.

Anche se il gate viene superato, la v0.9.20 resta `shadow_only`: le due ipotesi sono state nominate dall'audit 2024 e richiedono ulteriore validazione prima di qualsiasi promozione.

## Output principali

- `data/mrp-lite-model.json`
- `data/mrp-lite-live.json`
- `data/backtest-v0920-scotland-conlab.json`
- `data/bes-integrity-v0920.json`
- `data/v0915-reference-v0920.json`
- `data/scotland-conlab-sweep-v0920.json`

Il report dello sweep contiene risultati separati `Scotland-only`, `ConLab-only` e `combined`, oltre al conteggio diagnostico degli errori `SNP→Lab` e `Con→Lab` prima e dopo il candidato combinato.
