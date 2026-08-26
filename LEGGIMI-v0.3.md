# v0.3 — cosa cambia

## Mappa
La lentezza in hover della v0.2 nasceva soprattutto dal fatto che ogni `path.constituency`
cambiava stroke/opacity al passaggio del mouse. Con confini SVG complessi questo forza repaint
costosi.

La v0.3:
- disattiva la transizione hover sui 650 path;
- rimuove i 650 `<title>` SVG dopo il rendering;
- usa **un solo path overlay** per evidenziare il collegio sotto il puntatore;
- usa event delegation, non 650 listener hover;
- aggiorna la posizione del tooltip al massimo una volta per animation frame.

Non cambia geometrie, colori o risultati del modello.

## Backtest stage 1
`tools/build_backtest.py` scarica il database SQLite ufficiale del progetto psephology del
Parlamento britannico e costruisce `data/backtest-2024-territorial.json`.

Il test usa:
- baseline = 2019 nozionale sui confini 2024;
- target nazionale = voto GB reale 2024;
- verità = vincitori reali 2024.

Quindi misura **solo la conversione territoriale**, senza errore di polling.

Viene confrontato il lambda corrente 0,82 con una griglia 0,40–1,20.
Non cambiare ancora automaticamente il lambda di produzione: prima leggiamo il risultato.
