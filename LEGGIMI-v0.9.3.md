# Modello UK v0.9.3 — GB-first BES parser fix

La v0.9.2 falliva perché WinnerXX veniva interpretato prima di rimuovere
Northern Ireland. Il parser GB incontrava quindi partiti NI validi
(DUP, Sinn Féin, SDLP, Alliance, UUP, TUV) e li respingeva.

La v0.9.3:
- legge prima Country;
- esclude Northern Ireland;
- pretende esattamente 632 righe GB;
- solo dopo interpreta Region, WinnerXX, SecondXX, voti e share;
- registra `gb_rows: 632` e `ni_filtered_before_party_parsing: true`;
- mantiene WinnerXX ufficiali e la regola anti-super-partito per Other;
- mantiene il gate statistico invariato;
- mantiene push automatico, schedule, workflow_dispatch e cancel-in-progress:true.
