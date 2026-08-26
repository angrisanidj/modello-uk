# Modello UK v0.5 — gerarchia territoriale

Questa patch non modifica la mappa v0.4.2, che resta ottimizzata e in Web Mercator.

## Cosa aggiunge

1. **Sondaggi Westminster subnazionali**
   - la build prova a leggere automaticamente le sezioni Scotland e Wales della pagina Wikipedia dei sondaggi UK;
   - genera `data/subnational-polls.json`;
   - il layer è fail-soft: se la fonte cambia o non risponde, il sito torna al segnale GB.

2. **Baseline territoriale 2024**
   - `build_data.py` conserva i voti validi e i voti per partito di ogni collegio;
   - genera `data/territorial-baseline.json` con GB, England, Scotland, Wales e le 9 regioni inglesi;
   - i pesi paese derivano dai voti validi 2024, non da quote inventate.

3. **Modello live gerarchico**
   - GB → England / Scotland / Wales → 9 regioni inglesi → constituency;
   - Scotland e Wales usano i poll Westminster locali con half-life 28 giorni e shrinkage verso il segnale GB;
   - England viene ricavata come residuo coerente con la media GB;
   - le regioni inglesi reagiscono con sensibilità storiche solo se il backtest le approva.

4. **Backtest v0.5**
   - training: 2010→2015 e 2015→2017;
   - validation: 2017→2019;
   - holdout: 2019 nozionale→2024;
   - stima lambda specifici per partito e beta territoriali per Scotland, Wales e 9 regioni inglesi;
   - ridge/shrinkage verso beta=1 per evitare overfit;
   - `approved=true` solo se il modello non peggiora né winner accuracy né errore aggregato sui seggi su entrambe le elezioni non usate nel fit.

5. **Monte Carlo**
   - mantiene 50.000 simulazioni a blocchi da 1.000;
   - la proiezione centrale territoriale diventa il punto di partenza della simulazione;
   - lo shock nazionale è applicato come deviazione rispetto al target centrale, evitando di contare due volte lo swing;
   - resta il rumore correlato regionale e quello locale.

## File da sostituire

- `index.html`
- `scripts/app.js`
- `tools/build_data.py`
- `tools/build_backtest.py`
- `.github/workflows/update-data.yml`

Non sostituire `map-performance.js`, `map-performance.css` o gli altri file: la v0.5 conserva la mappa v0.4.2.

## Nuovi file generati automaticamente dalla Action

- `data/subnational-polls.json` (se il parsing è disponibile)
- `data/territorial-baseline.json`
- `data/model-params.json` aggiornato alla versione `uk-v05-hierarchical-territorial`
- `data/backtest-2024-territorial.json` con confronto common / party-only / hierarchical

## Cosa guardare nella Action

Lo step `Validate datasets` stampa:
- numero di sondaggi nazionali e subnazionali;
- elenco delle nove regioni inglesi;
- `Live hierarchical model approved: True/False`;
- metriche 2019 e 2024.

`approved=False` non è un errore: in quel caso il live usa automaticamente lambda 0,82 e beta territoriali 1, mantenendo comunque il layer Scotland/Wales se sono disponibili poll subnazionali.
