(() => {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const clean = (value) => String(value ?? "").replace(/\s+/g, " ").trim();
  const text = (id, fallback = "—") => clean(byId(id)?.textContent) || fallback;
  const rowTexts = (selector, limit = 10) =>
    Array.from(document.querySelectorAll(selector))
      .map((el) => clean(el.innerText || el.textContent))
      .filter(Boolean)
      .slice(0, limit);

  function dashboardUrl() {
    const canonical = document.querySelector('link[rel="canonical"]')?.href;
    if (canonical) return canonical;
    return `${location.origin}${location.pathname}`;
  }

  function section(title, rows) {
    if (!rows?.length) return "";
    return `\n${title}\n${rows.map((row) => `- ${row}`).join("\n")}\n`;
  }

  function buildPrompt() {
    const voteRows = rowTexts("#voteBars .vote-row", 12);
    const seatRows = rowTexts("#seatTable .seat-row", 14);
    const countryRows = rowTexts("#countrySummary .country-card", 4);
    const marginalRows = rowTexts("#marginalTableBody tr", 10);
    const uncertaintyRows = rowTexts("#uncertaintyPartyGrid .uncertainty-party", 10);
    const battlefieldRows = rowTexts("#battlefieldList .battlefield-seat", 8);
    const coalitionRows = rowTexts("#coalitionOptions .coalition-option", 6);

    const probabilityRows = [
      `Maggioranza Labour: ${text("probLabMaj")}`,
      `Maggioranza Conservative: ${text("probConMaj")}`,
      `Maggioranza Reform UK: ${text("probRefMaj")}`,
      `Hung parliament: ${text("probHung")}`,
      `Labour sopra la soglia operativa: ${text("probLabWorkMaj")}`,
      `Conservative sopra la soglia operativa: ${text("probConWorkMaj")}`,
      `Reform UK sopra la soglia operativa: ${text("probRefWorkMaj")}`,
      `Soglia operativa indicata dalla dashboard: ${text("workingThreshold")}`,
      `Monte Carlo: ${text("mcCount")} · ${text("mcStatus")}`,
    ];

    const kpis = [
      `Ultimo sondaggio: ${text("kpiLastPoll")} · ${text("kpiLastPollMeta")}`,
      `Partito in testa nei sondaggi: ${text("kpiLeader")} · ${text("kpiLeaderMeta")}`,
      `Primo partito per seggi: ${text("kpiLargest")} · ${text("kpiLargestMeta")}`,
      `Maggioranza: ${text("kpiMajority")} · ${text("kpiMajorityMeta")}`,
    ];

    return clean(`
Sto consultando un nowcast sulle elezioni generali britanniche. Voglio una lettura pensata per un normale lettore interessato alle elezioni, non un audit del codice o dello sviluppo del modello.

Dashboard: ${dashboardUrl()}
Versione interfaccia: 0.9.36. Motore statistico di produzione: v0.9.29 congelato.

INDICATORI PRINCIPALI
${kpis.map((row) => `- ${row}`).join("\n")}
${section("MEDIA CORRENTE DEI SONDAGGI", voteRows)}${section("STIME CORRENTI PER PARTITO", seatRows)}${section("PROBABILITÀ MONTE CARLO", probabilityRows)}${section("DISTRIBUZIONE DEI SEGGI — MEDIANA E INTERVALLO 80%", uncertaintyRows)}${section("QUADRO TERRITORIALE", countryRows)}${section("BATTLEFIELD — COLLEGI PIÙ INCERTI", battlefieldRows)}${section("COLLEGI PIÙ INCERTI MOSTRATI DAL CONSTITUENCY EXPLORER", marginalRows)}${section("COMBINAZIONI MINIME DI MAGGIORANZA MOSTRATE", coalitionRows)}
VALIDAZIONE DICHIARATA DAL MODELLO
- Backtest 2019 del Geography Blend: 609/632 vincitori corretti, errore assoluto complessivo sui seggi 14.
- Benchmark 2024 contro la geografia YouGov: 578/632, errore seggi 56.
- Cross-validation leave-one-region-out 2024 del provider stack: 584/632, errore seggi 44. Questa misura non va descritta come un holdout elettorale puro e incontaminato: serve a validare il weighting geografico del provider stack.
- La forza geografica 0,875 è stata selezionata sul 2019; il 2024 non è usato per selezionare quel parametro storico.
- I topline nazionali dei provider MRP esterni non vengono importati nel modello: vengono usate soltanto informazioni geografiche secondo le regole dichiarate.

COSA TI CHIEDO
1. Spiega in modo chiaro che cosa dice oggi il nowcast, distinguendo voto nazionale, seggi e probabilità. Non trattare lo scenario centrale come una certezza.
2. Se puoi consultare il web, verifica indipendentemente gli ultimi sondaggi britannici disponibili: indica date e fonti, segnala se esistono rilevazioni più recenti di quella inclusa nella dashboard e non sostituire i dati del modello senza dirlo esplicitamente.
3. Valuta se la trasformazione da voto nazionale a seggi è plausibile alla luce del First Past the Post, della geografia britannica e del trattamento separato dell'Irlanda del Nord. Usa intervalli e probabilità, non soltanto mediane.
4. Individua 3-5 fonti principali di incertezza e le regioni o i collegi marginali che potrebbero cambiare maggiormente il risultato.
5. Per le coalizioni, separa sempre l'aritmetica parlamentare dalla plausibilità politica attuale. Se fai affermazioni su veti, compatibilità o disponibilità dei partiti, verificale online e cita la fonte.
6. Costruisci tre scenari qualitativi plausibili: scenario centrale; scenario favorevole ai partiti oggi in crescita; scenario favorevole ai loro principali rivali. Evita falsa precisione e non inventare percentuali mancanti.
7. Concludi con una valutazione sintetica dell'affidabilità del quadro (alta/media/bassa), spiegando quali elementi sono robusti e quali fragili.

REGOLE DI LETTURA
- Distingui sempre: (a) dati riportati dalla dashboard, (b) fatti verificati da fonti esterne, (c) tue inferenze.
- Un nowcast risponde a “cosa accadrebbe se si votasse oggi?” e non è una previsione certa del giorno delle elezioni.
- Non entrare nei dettagli del codice salvo che servano a spiegare un'anomalia sostanziale nei risultati.
- Se un dato necessario non è presente, dichiaralo invece di ricostruirlo arbitrariamente.
    `).replace(/\n[ \t]+/g, "\n").trim();
  }

  async function copyText(value) {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return;
    }
    const area = document.createElement("textarea");
    area.value = value;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    if (!ok) throw new Error("copy-not-supported");
  }

  function setStatus(message, kind = "") {
    const status = byId("aiStatus");
    if (!status) return;
    status.textContent = message;
    status.classList.remove("ok", "error");
    if (kind) status.classList.add(kind);
  }

  function refreshPreview() {
    const preview = byId("aiPromptPreview");
    if (preview) preview.textContent = buildPrompt();
  }

  const destinations = {
    perplexity: (prompt) => `https://www.perplexity.ai/?q=${encodeURIComponent(prompt)}`,
    openai: (prompt) => `https://chatgpt.com/?q=${encodeURIComponent(prompt)}`,
    claude: (prompt) => `https://claude.ai/new?q=${encodeURIComponent(prompt)}`,
    gemini: (prompt) => `https://www.google.com/search?udm=50&q=${encodeURIComponent(prompt)}`,
  };

  async function handleAction(kind) {
    const prompt = buildPrompt();
    refreshPreview();
    const buildUrl = kind === "copy" ? null : destinations[kind];
    if (kind !== "copy" && !buildUrl) {
      setStatus("Destinazione IA non riconosciuta.", "error");
      return;
    }

    // Open synchronously while the click still counts as a user gesture;
    // waiting for Clipboard API first can make browsers classify the tab as a popup.
    const opened = buildUrl ? window.open(buildUrl(prompt), "_blank") : null;
    if (opened) opened.opener = null;
    try {
      await copyText(prompt);
      if (kind === "copy") {
        setStatus("Prompt aggiornato e copiato negli appunti ✓", "ok");
        return;
      }
      setStatus(
        opened
          ? "Prompt copiato ✓ · si apre l’assistente scelto. Se il testo non viene precompilato, incollalo dagli appunti."
          : "Prompt copiato ✓ · il browser ha bloccato la nuova scheda: apri l’assistente e incollalo dagli appunti.",
        "ok"
      );
    } catch (error) {
      console.error("AI prompt action failed", error);
      setStatus(
        opened
          ? "Assistente aperto, ma non sono riuscito a copiare il prompt: usa l’anteprima qui sotto."
          : "Non sono riuscito ad aprire la nuova scheda né a copiare il prompt: usa l’anteprima qui sotto.",
        "error"
      );
    }
  }

  document.querySelectorAll("[data-ai]").forEach((button) => {
    button.addEventListener("click", () => handleAction(button.dataset.ai));
  });

  byId("aiPromptDetails")?.addEventListener("toggle", (event) => {
    if (event.currentTarget.open) refreshPreview();
  });

  window.addEventListener("load", () => {
    // The core app renders asynchronously; defer once so the preview normally contains live values.
    window.setTimeout(refreshPreview, 1200);
  });
})();
