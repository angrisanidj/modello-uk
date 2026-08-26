# Modello UK v0.9.9 — scenario-aware territorial calibration

Obiettivo: conservare il forte miglioramento della v0.9.8 sul benchmark 2024
senza applicare la stessa correzione a una configurazione molto più stabile
come il 2019.

## Electoral turnover
Il modello calcola, da baseline e target nazionale:

    turnover = 0.5 * sum(|target_party - baseline_party|)

Non usa risultati futuri di collegio.

Attivazione di sistema:
- turnover <= 6 p.p.  -> 0
- turnover >= 18 p.p. -> 1
- interpolazione lineare fra le due soglie.

## Attivazione party-specific
La forza finale combina:
- electoral turnover;
- variazione nazionale del singolo partito;
- Conservative collapse per Con/Lab/LD/Reform;
- Reform surge per Reform.

Quindi:
- scenario stabile -> beta di dispersione tende a 1 e FPTP strength tende a 0;
- shock/realignment -> entra progressivamente la calibrazione completa.

## Dispersione
La v0.9.8 produceva un beta strutturale party-specific.
Ora viene applicato:

    beta_effective = 1 + activation * (beta_structural - 1)

La stima storica di concentrazione resta identica; cambia soltanto quanto viene
usata nello scenario corrente.

## FPTP
Anche le strength selezionate sul 2017 vengono moltiplicate per la stessa
activation party-specific.

## Validazione
- 2017: parameter selection;
- 2019: temporal validation;
- 2024: development benchmark;
- publication_ready resta false senza validazione esterna/fresca.

## Gate beta-live
Invariati:
- benchmark 2024 >=80%;
- +5 p.p. sul baseline;
- seat abs error <=200;
- 2019 non può perdere >1 p.p. di accuracy;
- errore seggi 2019 non può peggiorare >30.

## Diagnostica
`mrp-lite-model.json` contiene `scenario_activation` con:
- turnover;
- delta di ogni partito;
- Conservative drop;
- Reform rise;
- system activation;
per 2017, 2019, 2024 e live.
