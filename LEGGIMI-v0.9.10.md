# Modello UK v0.9.10 — incumbent-collapse challenger routing

La v0.9.9 ha raggiunto:
- 2019 validation: 92,25%, migliore del baseline;
- 2024 development benchmark: 78,16%, seat error 176;
- unico gate fallito: accuracy 2024 <80%.

Il residuo 2024 era concentrato soprattutto in:
- Conservative troppo alto;
- Labour troppo basso;
- Reform ancora troppo efficiente;
- SNP troppo alto.

## Nuovo layer: incumbent-collapse routing

Non è calibrato sul 2024.

Il precedente storico è SNP 2015->2017:
- SNP parte da una posizione dominante;
- subisce un forte calo relativo;
- perde numerosi collegi;
- i beneficiari dipendono dal runner-up locale.

Per ogni partito:
    relative_decline = max(0, base - target) / base

Activation:
- <=10% di calo relativo: 0
- >=30%: 1
- lineare fra i due valori.

## Due meccanismi

1. Challenger routing
Nei collegi detenuti da un partito in forte calo, una quota del voto previsto
per terzi/quarti sfidanti viene trasferita al runner-up della baseline.

Questo rappresenta:
- tactical displacement;
- coordinamento implicito del voto anti-incumbent;
- organizzazione locale già dimostrata dal secondo posto precedente.

2. Incumbent unwind
Una quota del vantaggio previsto dell'incumbent sul runner-up viene attenuata.
Il trasferimento è proporzionale al gap previsto e alla gravità del declino.

## Selezione
Su 2015->2017 vengono testate:
- route strength: 0 / .20 / .40 / .60 / .80
- unwind strength: 0 / .15 / .30 / .45 / .60

Sono quindi 25 combinazioni.
Scelta primaria: collegi corretti nel 2017.
Tie-break: seat error e accuracy scozzese.

2019 resta completamente fuori dalla selezione.
2024 resta development benchmark.

## Perché dovrebbe aiutare il 2024
Conservative e SNP hanno forti cali relativi e attivano il layer.
Nel 2019 Conservative e SNP non sono in una configurazione analoga, quindi
l'attivazione è nulla o molto bassa: la buona validazione v0.9.9 è protetta.

## Gate
Invariati:
- benchmark 2024 >=80%;
- +5 p.p. vs baseline;
- seat error <=200;
- 2019 non perde >1 p.p.;
- 2019 seat error non peggiora >30.

`publication_ready` resta false senza nuova validazione esterna.
