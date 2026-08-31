# Baseline snapshot

Questa cartella congela gli artefatti di produzione del modello UK senza rieseguire il modello.

- **Commit sorgente:** `f3a3ec9`
- **Data e ora copia:** `2026-08-31T11:40:14+02:00` (Europe/Rome)
- **Metodo di copia:** `git show <commit>:<path>` — copia diretta degli oggetti Git
- **Modello eseguito durante la copia:** no

## Artefatti congelati

| Sorgente | Copia baseline | Blob SHA |
|---|---|---|
| `data/monte-carlo-current.json` | `baseline/monte-carlo-current.json` | `cc811693dff1137546ae702d1c9e83c0a913134d` |
| `data/mrp-lite-live.json` | `baseline/mrp-lite-live.json` | `ad25caed78fd5e913fecf97b2b0b707cfe1a7fd7` |
| `data/promotion-audit-v0929.json` | `baseline/promotion-audit-v0929.json` | `a9de9a955e0f639f8680a2cd10cf3df15f43f6e6` |

## CONFIG.nationalSigma

| Partito | Sigma (punti percentuali) |
|---|---:|
| `lab` | 1.35 |
| `con` | 1.35 |
| `ref` | 1.35 |
| `ld` | 0.95 |
| `green` | 0.95 |
| `snp` | 0.5 |
| `pc` | 0.3 |
| `rb` | 0.65 |
| `other` | 0.7 |

## Altri parametri Monte Carlo

- `swingLambda`: `0.82`
- `regionNoise`: `0.035`
- `localNoise`: `0.055`
- `niSwingLambda`: `0.55`
- `niNationalNoise`: `0.05`
- `niLocalNoise`: `0.1`
- `selected_strength`: `0.875`

## Seed della simulazione

Il codice di produzione inizializza il PRNG con:

`mulberry32(hashString(simulationSeedKey()))`

- valore restituito da `simulationSeedKey()`: `uk-v0931-20260827-constituency-explorer-scenario-builder:1084808147`
- seed numerico passato a `mulberry32()`: `1909399682`
- stato di `modelParams` nella seed key: `fallback`

## Verifica dell'output Monte Carlo

- `summary.sims`: `50000`
- tutti gli array di `summary.dist` hanno 50.000 elementi: **sì**
- collegi presenti in `seatProb`: **650**
- tutti i collegi hanno esattamente lo stesso set di campi previsto da `SEAT_ORDER`: **sì**
- campi per collegio: `lab`, `con`, `ref`, `ld`, `green`, `snp`, `pc`, `rb`, `sf`, `dup`, `alliance`, `sdlp`, `uup`, `tuv`, `aontu`, `pbp`, `ni_green`, `ind`, `ni_other`, `other`

### Lunghezza di summary.dist per partito

| Partito | Valori |
|---|---:|
| `lab` | 50000 |
| `con` | 50000 |
| `ref` | 50000 |
| `ld` | 50000 |
| `green` | 50000 |
| `snp` | 50000 |
| `pc` | 50000 |
| `rb` | 50000 |
| `sf` | 50000 |
| `dup` | 50000 |
| `alliance` | 50000 |
| `sdlp` | 50000 |
| `uup` | 50000 |
| `tuv` | 50000 |
| `aontu` | 50000 |
| `pbp` | 50000 |
| `ni_green` | 50000 |
| `ind` | 50000 |
| `ni_other` | 50000 |
| `other` | 50000 |

## Esito verifica

- `sims === 50000`: **OK**
- `dist` completo per ogni partito: **OK**
- `seatProb` contiene 650 collegi: **OK**
- schema `seatProb` uniforme: **OK**
