# Modello UK v0.9.1 — BES parser integrity

Questa è una correzione metodologica della v0.9. Il precedente 76,3% NON viene
considerato valido.

## Correzioni

1. Stata
   - le value labels vengono preservate;
   - Country e Region non possono più diventare codici numerici silenziosamente;
   - una regione inglese non riconosciuta genera errore invece di finire in East of England.

2. Quote di voto
   - quando sono disponibili i voti assoluti, le share vengono ricostruite dai voti;
   - `Other` è il residuo dei voti validi dopo i partiti modellati;
   - fallback sulle share pubblicate solo quando i vote-count non sono disponibili;
   - rilevazione 0-1 vs 0-100 basata sul massimo, non sul 95° percentile:
     questo corregge il bug delle colonne territorialmente sparse come Plaid Cymru.

3. UKIP / Brexit Party / Reform UK
   - tutte le colonne presenti nella stessa elezione vengono SOMMATE;
   - nel 2019 UKIP e Brexit non sono più mutuamente esclusivi.

## Hard parser gate

Prima di qualsiasi fit devono essere ricostruiti esattamente:

2010 GB:
Con 306, Lab 258, LD 57, SNP 6, PC 3, Green 1, Other/Speaker 1.

2015 GB:
Con 330, Lab 232, SNP 56, LD 8, PC 3, Green 1, UKIP/Reform-family 1,
Other/Speaker 1.

2017 GB:
Con 317, Lab 262, SNP 35, LD 12, PC 4, Green 1, Other/Speaker 1.

2019 GB:
Con 365, Lab 202, SNP 48, LD 11, PC 4, Green 1, Other/Speaker 1.

2024 GB:
Lab 411, Con 121, LD 72, SNP 9, Reform 5, Green 4, PC 4, Other 6.

Geografia:
- vecchi confini: England 533, Scotland 59, Wales 40;
- confini 2024: England 543, Scotland 57, Wales 32;
- tutti e 9 i conteggi regionali inglesi sono verificati.

Il file `data/bes-integrity-v091.json` conserva tutti i controlli.

Se l'integrity gate fallisce, la GitHub Action FALLISCE e non viene pubblicata
la nuova versione. Il sito stabile precedente resta intatto.

Se l'integrity gate passa ma il modello ML non supera il gate statistico,
la Action può pubblicare la v0.9.1 ma il browser continua sul fallback.

## File
- index.html
- scripts/app.js
- tools/build_mrp_lite.py
- requirements.txt
- .github/workflows/update-data.yml (completo)
