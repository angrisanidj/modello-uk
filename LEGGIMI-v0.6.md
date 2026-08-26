# Modello UK v0.6 — transfer / competition model

## Cosa cambia
Il candidato v0.6 non prova più a stimare altri beta regionali.

1. Parte dalla baseline constituency-level.
2. Applica lo swing nazionale.
3. Rake delle quote locali per far coincidere esattamente il target nazionale.
4. Applica una matrice di trasferimento cross-party stimata solo su:
   - 2010→2015
   - 2015→2017
5. Rake finale: il layer territoriale può cambiare **dove** finiscono i voti, non quanti voti nazionali esistono.
6. Gate non visti:
   - 2017→2019
   - 2019 nozionale→2024

Se il candidato fallisce anche una sola delle due metriche chiave (winner accuracy / errore seggi)
in uno dei due gate, `approved=false` e il live resta sul fallback prudente.

## Monte Carlo
Se il transfer model passa il gate, la Monte Carlo parte dalle quote centrali già trasformate e
applica gli shock probabilistici attorno a quel centro, evitando di riapplicare il trasferimento
50.000 volte nel browser.

## Revisione grafica
La revisione grafica è esplicitamente lo step successivo alla chiusura del seat model:
- gerarchia desktop/mobile;
- emiciclo e tabella seggi;
- card KPI;
- mappa e pannello collegio;
- tooltip;
- responsive/overflow;
- leggibilità colori;
- social preview e rifiniture editoriali.

## File da sostituire
- `index.html`
- `scripts/app.js`
- `tools/build_backtest.py`
- `.github/workflows/update-data.yml`
