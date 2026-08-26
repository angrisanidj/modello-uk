# Modello UK v0.4 — patch

## Mappa
La pagina ora prova prima `data/constituencies-map.geojson`, generato automaticamente
da `build_data.py`. Il GeoJSON ONS completo resta nel repository come backstop.

La versione display:
- usa Douglas–Peucker con tolleranza 0,0025°;
- conserva tutti i 650 collegi e i codici ONS;
- elimina proprietà GIS non necessarie;
- arrotonda le coordinate;
- usa path SVG a precisione 0,1 px;
- non gestisce più `pointermove`: l'hover scatta solo quando si entra in un nuovo collegio;
- usa click delegation e cache dei path, evitando scansioni dei 650 elementi.

La Action stampa dimensione e numero di vertici prima/dopo.

## Modello
`build_backtest.py` non calibra più sul 2024:
- training: 2010→2015 e 2015→2017;
- validation: 2017→2019;
- holdout: 2019 nozionale→2024.

Genera `data/model-params.json`.
`app.js` usa quei coefficienti soltanto quando `approved=true`.
Altrimenti conserva automaticamente il lambda prudente 0,82.

## File da sostituire/aggiungere
- `index.html`
- `scripts/app.js`
- `scripts/map-performance.js`
- `map-performance.css`
- `tools/build_data.py`
- `tools/build_backtest.py`
- `.github/workflows/update-data.yml`
