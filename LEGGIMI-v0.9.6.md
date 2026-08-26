# Modello UK v0.9.6 — BES metadata propagation fix

Il run v0.9.5 ha dimostrato che il parser finalmente funziona:
- BES integrity: passed
- 2019 actual: Con 365, Lab 202, SNP 48, LD 11, PC 4, Green 1, Other 1
- 2024 actual: Lab 411, Con 121, LD 72, SNP 9, Reform 5, Green 4, PC 4, Other 6
- geografia vecchi/nuovi confini corretta.

L'errore successivo era puramente interno:
`extract_election()` restituiva correttamente
`ni_filtered_before_party_parsing=True`, ma `merge_demo()` creava un nuovo
dizionario contenente solo year/frame/demo_columns e scartava quel metadato.

Il workflow vedeva quindi il campo assente e produceva:
`2010 actual parsed parties before filtering NI`.

La v0.9.6 modifica solo `merge_demo()`:
- copia l'intero dizionario election;
- sostituisce frame con quello arricchito dalle variabili demografiche;
- aggiunge demo_columns;
- conserva tutti gli altri metadati.

Nessuna modifica:
- ai dati elettorali;
- al parser dei partiti;
- al modello ML;
- ai gate 80% / +5pp / seat error <=200;
- alla soglia publication-ready 85% / <=140.
