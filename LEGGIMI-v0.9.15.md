# modello-UK v0.9.15 — local-election + by-election strength sweep

Questa versione resta **shadow research** e non modifica il modello pubblicato. La baseline canonica resta congelata alla v0.9.10-equivalente: **583/632, errore seggi 42 nel 2019; 494/632, errore seggi 176 nel benchmark 2024**.

## Perché questo esperimento è diverso

Dopo aver respinto routing, correzioni Reform-specifiche, imputazione/latent share e place/regradienting, la v0.9.15 introduce una fonte di informazione **nuova**: la forza elettorale locale osservata tra due elezioni generali.

La scelta è motivata anche da modelli britannici pubblici: Survation ha descritto il proprio MRP 2024 come aggiornato con i risultati delle elezioni locali di maggio 2024 per rappresentare la forza locale dei partiti; altri practitioner hanno incorporato by-election e fattori di campagna locale.

## Fonti esterne

- Democracy Club, CSV export di candidati e risultati: `https://candidates.democracyclub.org.uk/data/export_csv/`
- ONS Open Geography Portal, ward → Westminster constituency → local authority lookup 2019 e 2024.
- BES/Figshare per il modello generale e i backtest, come nelle versioni precedenti.

La build fallisce se le fonti locali non vengono scaricate o se il mapping copre meno di 300 collegi GB: non viene interpretata l'assenza di dati come assenza di effetto locale.

## Segnale elezioni locali

Per ogni ballot locale:

1. i voti di più candidati dello stesso partito nello stesso ward vengono mediati, evitando di moltiplicare artificialmente la forza di un partito nei ward multi-member;
2. si ricava la quota effettiva del partito nel ward;
3. i ward vengono aggregati all'autorità locale;
4. dalla quota dell'autorità viene sottratta la quota nazionale dello stesso partito nelle **stesse elezioni locali e nello stesso giorno**;
5. viene poi sottratta la normale geografia già osservata nell'ultima elezione generale.

Il risultato è quindi un indicatore di **forza locale relativa**, non un semplice swing di midterm.

Il collegamento autorità locale → collegio parlamentare usa gli lookup ONS ward/PCON/LAD. Se un collegio contiene più autorità, il segnale è combinato in base al numero di ward associati; è un'approssimazione geografica esplicitamente auditata nel JSON di output.

## By-election

Le by-election parlamentari vengono trattate separatamente. Sono accettati solo collegi con corrispondenza di nome esatta dopo normalizzazione. La differenza fra quota nella by-election e quota nell'ultima generale decade rapidamente nel tempo (half-life 0,75 anni), per limitare il rischio di trasferire indefinitamente effetti candidati/protesta tipici delle suppletive.

## Disciplina temporale

### Validazione 2019

Elezioni locali ammesse:

- 4 maggio 2017
- 3 maggio 2018
- 2 maggio 2019

By-election: dopo la generale 2017 e **prima del 12 dicembre 2019**.

Le intensità del segnale locale e delle by-election vengono selezionate **esclusivamente sul 2019**.

### Benchmark 2024

Elezioni locali ammesse:

- 2 maggio 2019
- 6 maggio 2021
- 5 maggio 2022
- 4 maggio 2023
- 2 maggio 2024

By-election: dopo la generale 2019 e **prima del 4 luglio 2024**.

Il risultato 2024 serve solo a misurare la configurazione già scelta sul 2019. La build produce anche la classifica ex-post dell'intera griglia 2024, ma la etichetta esplicitamente come diagnostica e non può usarla per selezionare parametri.

## Sweep

Griglia fissata nel sorgente:

- local strength: `0, 0.25, 0.50, 0.75, 1.00`
- by-election strength: `0, 0.15, 0.30, 0.50`

Totale: **20 configurazioni**, compresa `0/0`, che replica il candidato canonico. Dopo ogni aggiustamento il raking riporta esattamente il modello al target nazionale della generale.

## Gate

Una configurazione è interessante solo se, dopo essere stata selezionata sul 2019:

- raggiunge **almeno 506/632 collegi corretti (80%)** nel 2024;
- mantiene `seat_abs_error_sum <= 176`.

Anche se passa, `approved:false`, `publication_ready:false` e `shadow_only:true` restano obbligatori. Il 2024 è ormai un benchmark di sviluppo, non una validazione indipendente utilizzabile per la promozione.

## Output nuovi

- `data/local-strength-sweep-v0915.json`
- `data/backtest-v0915-local-strength.json`
- `data/error-structure-v0915.json`
- `data/bes-integrity-v0915.json`

Il report `local-strength-sweep-v0915.json` include le fonti effettivamente scaricate, le date, la copertura geografica, il candidato scelto sul 2019 e la classifica 2024 solo diagnostica.
