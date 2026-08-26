#!/usr/bin/env python3
from __future__ import annotations
import csv, io, json, re, unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"; DATA.mkdir(exist_ok=True)
RESULTS_CSV="https://researchbriefings.files.parliament.uk/documents/CBP-10009/HoC-GE2024-results-by-candidate.csv"
UA="FocusAmerica-UK-election-model/0.8 (+https://angrisanidj.github.io/modello-uk/)"
NI_PARTIES=("sf","dup","alliance","sdlp","uup","tuv","aontu","pbp","ni_green","ind","ni_other")
ASSEMBLY_MAY_2024={"sf":29.0,"dup":21.0,"alliance":15.0,"uup":11.0,"sdlp":8.0,"tuv":8.0,"ni_green":1.0}
ASSEMBLY_JULY_2026={"sf":22.0,"dup":15.0,"alliance":10.0,"uup":16.0,"sdlp":13.0,"tuv":12.0,"ni_green":5.0,"pbp":2.0,"aontu":3.0,"ni_other":2.0}
SIGNAL_WEIGHT=.25

def clean(v):
    text=unicodedata.normalize("NFKD",v or "")
    text="".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+"," ",text).strip().lower()

def party_id(abbrev,full):
    a,f=clean(abbrev),clean(full); j=f"{a} {f}"
    if "sinn fein" in j or a=="sf": return "sf"
    if "democratic unionist" in j or a=="dup": return "dup"
    if "social democratic and labour" in j or a=="sdlp": return "sdlp"
    if "ulster unionist" in j or a=="uup": return "uup"
    if "alliance party" in j or a in {"all","apni","alliance"}: return "alliance"
    if "traditional unionist voice" in j or a=="tuv": return "tuv"
    if "aontu" in j: return "aontu"
    if "people before profit" in j or a in {"pbp","pba"}: return "pbp"
    if "green party northern ireland" in j or "green party ni" in j: return "ni_green"
    if "independent" in j or a in {"ind","independent"}: return "ind"
    return "ni_other"

def fetch_csv():
    r=requests.get(RESULTS_CSV,headers={"User-Agent":UA},timeout=60)
    r.raise_for_status()
    return r.content.decode("utf-8-sig")

def build():
    grouped={}
    for row in csv.DictReader(io.StringIO(fetch_csv())):
        if (row.get("Country name") or "").strip().lower()!="northern ireland": continue
        ons=(row.get("ONS ID") or "").strip()
        if not ons: continue
        item=grouped.setdefault(ons,{
            "id":ons,"name":(row.get("Constituency name") or "").strip(),
            "region":"Northern Ireland","country":"Northern Ireland","candidates":[]
        })
        try: votes=int(float((row.get("Votes") or "0").replace(",","").strip() or 0))
        except ValueError: votes=0
        pid=party_id(row.get("Party abbreviation"),row.get("Party name"))
        item["candidates"].append({
            "party":pid,"party_name":(row.get("Party name") or "").strip(),
            "candidate":" ".join(x for x in [(row.get("Candidate first name") or "").strip(),(row.get("Candidate surname") or "").strip()] if x),
            "votes":votes
        })
    if len(grouped)!=18: raise RuntimeError(f"Expected 18 NI constituencies, found {len(grouped)}")

    constituencies=[]; national_votes=Counter(); winner_counts=Counter(); total_ni_votes=0
    for item in grouped.values():
        candidates=sorted(item.pop("candidates"),key=lambda x:x["votes"],reverse=True)
        total=sum(c["votes"] for c in candidates)
        if total<=0: raise RuntimeError(f"No valid votes for {item['name']}")
        shares=defaultdict(float); party_votes=defaultdict(int)
        for c in candidates:
            c["share"]=round(c["votes"]/total*100,3)
            shares[c["party"]]+=c["votes"]/total*100
            party_votes[c["party"]]+=c["votes"]
            national_votes[c["party"]]+=c["votes"]
        winner=candidates[0]["party"]; winner_counts[winner]+=1; total_ni_votes+=total
        item.update({
            "valid_votes":total,"shares":{p:round(shares.get(p,0),4) for p in NI_PARTIES},
            "party_votes":dict(party_votes),"winner2024":winner,
            "winner2024_name":candidates[0]["party_name"],"winner2024_candidate":candidates[0]["candidate"],
            "majority2024":candidates[0]["votes"]-candidates[1]["votes"],
            "top_candidates_2024":candidates[:5],"eligible_parties":sorted({c["party"] for c in candidates})
        })
        constituencies.append(item)

    expected={"sf":7,"dup":5,"sdlp":2,"alliance":1,"uup":1,"tuv":1,"ind":1}
    if {p:winner_counts.get(p,0) for p in expected}!=expected or sum(winner_counts.values())!=18:
        raise RuntimeError(f"NI winner validation failed: {dict(winner_counts)}")

    baseline={p:national_votes[p]/total_ni_votes*100 for p in NI_PARTIES}
    target=dict(baseline)
    for p in ASSEMBLY_MAY_2024:
        target[p]=max(.05,baseline[p]+SIGNAL_WEIGHT*(ASSEMBLY_JULY_2026[p]-ASSEMBLY_MAY_2024[p]))
    total_target=sum(target.values()); target={p:target[p]/total_target*100 for p in NI_PARTIES}
    constituencies.sort(key=lambda x:x["name"])
    return {
        "meta":{"version":"uk-v08-ni-constituency","generated_at":datetime.now(timezone.utc).isoformat(),"seats":18,
            "mode":"constituency-baseline-plus-weak-assembly-trend","signal_weight":SIGNAL_WEIGHT,
            "signal_warning":"No recent NI-only Westminster voting-intention poll is available. LucidTalk Assembly movement is used only as a 25% directional signal.",
            "candidacy_assumption":"Only parties present in each constituency in 2024 are eligible in v0.8; future pacts/candidacy changes require an explicit update."},
        "national_2024":{p:round(baseline[p],5) for p in NI_PARTIES},
        "assembly_reference_2024":ASSEMBLY_MAY_2024,"assembly_current_2026":ASSEMBLY_JULY_2026,
        "target_shares":{p:round(target[p],5) for p in NI_PARTIES},
        "winner_counts_2024":dict(winner_counts),"constituencies":constituencies
    }

def main():
    payload=build(); path=DATA/"ni-2024.json"
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Wrote {path.relative_to(ROOT)}"); print("NI winner counts:",payload["winner_counts_2024"]); print("NI weak target:",payload["target_shares"])
    return 0
if __name__=="__main__": raise SystemExit(main())
