# Modello UK v0.7.1 — hotfix Monte Carlo

Correzioni:
- ripristinato il blocco `runMonteCarlo()` perso accidentalmente nel merge v0.7;
- ripristinate funzioni RNG, fingerprint/cache, `prepareSeatModel()` e quantili;
- la Monte Carlo parte dal centro già raked quando il modello parziale è approvato;
- nuovo namespace cache `uk-v071-20260826-mcfix`;
- cache-busting esplicito in `index.html` (`app.js?v=0.7.1`);
- testo Beta aggiornato dalla vecchia descrizione v0.5 alla metodologia v0.7;
- il workflow v0.7 completo è incluso anche se non richiede modifiche.

La v0.8 Northern Ireland viene dopo la verifica di questo hotfix.
