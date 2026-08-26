#!/usr/bin/env python3
"""
modello-uk v0.9.5 — robust official-party label parser / hybrid residual model

Purpose
-------
This is deliberately a SHADOW model until it clears a hard historical gate.

Data:
- BES 2010-2019 Constituency Results with Census and Candidate Data
- BES 2024 Constituency Results with Census and Candidate Data
Both are CC BY 4.0 and downloaded through the Figshare API.

Rolling-origin validation:
1. Tune model family/hyperparameters on:
      train 2010->2015
      internal test 2015->2017
2. Refit selected model on 2010->2015 + 2015->2017
      validation 2017->2019
3. Refit selected model on all pre-2024 transitions
      holdout 2019 notional (2024 boundaries) -> 2024
4. Only after the holdout has been scored, refit on all known history including
   2024 to create today's live central projection.

The 2024 holdout is NEVER used to select model family, hyperparameters, blend
strength or the approval threshold.

Model structure
---------------
- Conservative proportional-swing centre (lambda=0.82)
- Residual model using:
    * all parties' local baseline shares
    * national base/target shares and changes
    * baseline winner, runner-up, margin and party ranks
    * England/Scotland/Wales + English region
    * constituency demographics expressed as within-wave percentiles:
      density, age structure, tenure, ethnicity, economic activity,
      industrial structure, NS-SEC and Leave estimate
    * explicit competition/tactical interactions for Conservative collapse,
      Reform growth, Labour/LD second-place positioning and Scotland
- Candidate families: ridge, gradient boosting, and conservative hybrid blends
- Final iterative raking to the supplied GB vote target.

Hard gate
---------
The model can go live only if:
- holdout 2024 winner accuracy >= 80%
- holdout improves baseline winner accuracy by >= 5 percentage points
- holdout aggregate seat absolute error <= 200
- validation 2019 accuracy is no worse than baseline by >1 percentage point
- validation seat error is no worse than baseline by >30 seats

This gate is intentionally difficult. approved=False is a valid outcome.
"""
from __future__ import annotations

import json
import math
import re
import sys
import tempfile
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
DATA.mkdir(exist_ok=True)

MODEL_OUT=DATA/"mrp-lite-model.json"
LIVE_OUT=DATA/"mrp-lite-live.json"
BACKTEST_OUT=DATA/"backtest-v095-mrp-lite.json"
INTEGRITY_OUT=DATA/"bes-integrity-v095.json"

HIST_ARTICLE=20278599
CURR_ARTICLE=28430672
FIGSHARE_API="https://api.figshare.com/v2/articles/{article_id}"

PARTIES=("lab","con","ref","ld","green","snp","pc","other")
MAIN_PARTIES=("lab","con","ref","ld","green","snp","pc")
COMMON_LAMBDA=.82
FLOOR_MAIN=.18
FLOOR_SMALL=.03
RAKE_ITERATIONS=80

REGION_KEYS=(
    "north_east","north_west","yorkshire","east_midlands","west_midlands",
    "east_england","london","south_east","south_west","scotland","wales"
)

MODEL_SPECS=(
    {"name":"ridge_a1_g075","kind":"ridge","alpha":1.0,"gamma":.75},
    {"name":"ridge_a5_g075","kind":"ridge","alpha":5.0,"gamma":.75},
    {"name":"ridge_a20_g075","kind":"ridge","alpha":20.0,"gamma":.75},
    {"name":"ridge_a5_g100","kind":"ridge","alpha":5.0,"gamma":1.0},
    {"name":"ridge_a20_g100","kind":"ridge","alpha":20.0,"gamma":1.0},
    {"name":"hgb_d2_g075","kind":"hgb","depth":2,"leaf":24,"l2":2.0,"gamma":.75},
    {"name":"hgb_d3_g075","kind":"hgb","depth":3,"leaf":28,"l2":4.0,"gamma":.75},
    {"name":"hgb_d2_g100","kind":"hgb","depth":2,"leaf":24,"l2":2.0,"gamma":1.0},
    {"name":"hybrid_a5_d2_w25","kind":"hybrid","alpha":5.0,"depth":2,"leaf":24,"l2":2.0,"hgb_weight":.25,"gamma":.85},
    {"name":"hybrid_a20_d2_w25","kind":"hybrid","alpha":20.0,"depth":2,"leaf":24,"l2":2.0,"hgb_weight":.25,"gamma":.85},
    {"name":"hybrid_a5_d2_w40","kind":"hybrid","alpha":5.0,"depth":2,"leaf":24,"l2":2.0,"hgb_weight":.40,"gamma":.85},
)

UA="FocusAmerica-UK-election-model/0.9.5 (+https://angrisanidj.github.io/modello-uk/)"

def utcnow():
    return datetime.now(timezone.utc)

def nkey(value:Any)->str:
    return re.sub(r"[^a-z0-9]+","",str(value or "").lower())

def clamp(x:float,a:float,b:float)->float:
    return max(a,min(b,x))

def normalize_share_series(s:pd.Series)->pd.Series:
    """Normalize a percentage/fraction column without using distribution quantiles.

    Sparse regional-party columns (e.g. Plaid Cymru) are zero in most GB seats,
    so a 95th-percentile unit detector can misclassify a genuine 0-100 share
    column as 0-1. The maximum finite value is safe here: a fraction column
    cannot exceed 1, while an election percentage column routinely does.
    """
    x=pd.to_numeric(s,errors="coerce")
    finite=x[np.isfinite(x)]
    if len(finite) and float(finite.max())<=1.5:
        x=x*100.0
    return x.fillna(0.0).clip(lower=0.0)

def find_col(df:pd.DataFrame,*names:str)->str|None:
    lookup={nkey(c):c for c in df.columns}
    for name in names:
        k=nkey(name)
        if k in lookup:return lookup[k]
    return None

def cols_matching(df:pd.DataFrame, include:list[str], exclude:list[str]|None=None)->list[str]:
    inc=[nkey(x) for x in include]
    exc=[nkey(x) for x in (exclude or [])]
    out=[]
    for c in df.columns:
        k=nkey(c)
        if all(x in k for x in inc) and not any(x in k for x in exc):
            out.append(c)
    return out

def fetch_article_file(article_id:int,dest:Path)->tuple[Path,dict[str,Any]]:
    meta=requests.get(
        FIGSHARE_API.format(article_id=article_id),
        headers={"User-Agent":UA},
        timeout=60
    )
    meta.raise_for_status()
    article=meta.json()
    files=article.get("files") or []
    if not files:
        raise RuntimeError(f"Figshare article {article_id}: no files returned")

    preferred=[]
    ext_score={".dta":0,".csv":1,".xlsx":2,".xls":3,".sav":4}
    for f in files:
        name=str(f.get("name") or "")
        ext=Path(name).suffix.lower()
        if ext in ext_score:
            preferred.append((ext_score[ext],-int(f.get("size") or 0),f))
    if not preferred:
        raise RuntimeError(
            f"Figshare article {article_id}: no supported data file; "
            f"available={[f.get('name') for f in files]}"
        )
    _,_,chosen=sorted(preferred,key=lambda x:(x[0],x[1]))[0]
    name=str(chosen.get("name") or f"{article_id}.data")
    url=chosen.get("download_url")
    if not url:
        file_id=chosen.get("id")
        if not file_id:raise RuntimeError("Figshare file has neither download_url nor id")
        url=f"https://api.figshare.com/v2/file/download/{file_id}"

    path=dest/name
    with requests.get(url,headers={"User-Agent":UA},timeout=120,stream=True) as r:
        r.raise_for_status()
        with path.open("wb") as fh:
            for chunk in r.iter_content(1024*1024):
                if chunk:fh.write(chunk)
    if path.stat().st_size<20_000:
        raise RuntimeError(f"Downloaded BES file unexpectedly small: {path}")
    return path,{
        "article_id":article_id,
        "title":article.get("title"),
        "doi":article.get("doi"),
        "license":(article.get("license") or {}).get("name") if isinstance(article.get("license"),dict) else article.get("license"),
        "file_name":name,
        "file_id":chosen.get("id"),
        "file_size":chosen.get("size"),
    }

def read_table(path:Path)->pd.DataFrame:
    ext=path.suffix.lower()
    if ext==".dta":
        # Country/Region/Winner are labelled Stata variables. Discarding value
        # labels silently turns them into integer codes and destroys geography.
        try:
            return pd.read_stata(path,convert_categoricals=True)
        except Exception:
            import pyreadstat
            df,_=pyreadstat.read_dta(str(path),apply_value_formats=True)
            return df
    if ext==".csv":return pd.read_csv(path)
    if ext in {".xlsx",".xls"}:return pd.read_excel(path)
    if ext==".sav":
        import pyreadstat
        df,_=pyreadstat.read_sav(str(path),apply_value_formats=True)
        return df
    raise RuntimeError(f"Unsupported data file {path}")

def find_cols(df:pd.DataFrame,*names:str)->list[str]:
    lookup={nkey(c):c for c in df.columns}
    out=[]
    for name in names:
        c=lookup.get(nkey(name))
        if c and c not in out:out.append(c)
    return out

def party_share_cols(df:pd.DataFrame,p:str,yy:str)->list[str]:
    variants={
        "lab":[f"Lab{yy}",f"Labour{yy}"],
        "con":[f"Con{yy}",f"Conservative{yy}"],
        "ld":[f"LD{yy}",f"LibDem{yy}",f"LiberalDemocrat{yy}"],
        "green":[f"Green{yy}",f"Grn{yy}"],
        "snp":[f"SNP{yy}"],
        "pc":[f"PC{yy}",f"Plaid{yy}",f"PlaidCymru{yy}"],
        "other":[f"Other{yy}",f"Others{yy}"],
        # Treat UKIP -> Brexit Party -> Reform UK as one historical family.
        # In 2019 both UKIP19 and Brexit19 can coexist and MUST be added.
        "ref":[
            f"RUK{yy}",f"Reform{yy}",f"ReformUK{yy}",
            f"Brexit{yy}",f"Brx{yy}",f"BrexitParty{yy}",
            f"UKIP{yy}",f"UKIndependence{yy}"
        ],
    }
    return find_cols(df,*variants[p])

def party_vote_cols(df:pd.DataFrame,p:str,yy:str)->list[str]:
    variants={
        "lab":[f"LabVote{yy}",f"LabourVote{yy}"],
        "con":[f"ConVote{yy}",f"ConservativeVote{yy}"],
        "ld":[f"LDVote{yy}",f"LibDemVote{yy}",f"LiberalDemocratVote{yy}"],
        "green":[f"GreenVote{yy}",f"GrnVote{yy}"],
        "snp":[f"SNPVote{yy}"],
        "pc":[f"PCVote{yy}",f"PlaidVote{yy}",f"PlaidCymruVote{yy}"],
        "other":[f"OtherVote{yy}",f"OthersVote{yy}"],
        "ref":[
            f"RUKVote{yy}",f"ReformVote{yy}",f"ReformUKVote{yy}",
            f"BrexitVote{yy}",f"BrxVote{yy}",f"BrexitPartyVote{yy}",
            f"UKIPVote{yy}",f"UKIndependenceVote{yy}"
        ],
    }
    return find_cols(df,*variants[p])

def sum_numeric_cols(df:pd.DataFrame,cols:list[str])->pd.Series:
    if not cols:return pd.Series(0.0,index=df.index,dtype=float)
    return df[cols].apply(pd.to_numeric,errors="coerce").fillna(0.0).sum(axis=1)

def total_vote_col(df:pd.DataFrame,yy:str)->str|None:
    return find_col(df,f"TotalVote{yy}",f"ValidVote{yy}",f"ValidVotes{yy}")

def turnout_col(df:pd.DataFrame,yy:str)->str|None:
    return find_col(df,f"Turnout{yy}")

def id_col(df:pd.DataFrame)->str|None:
    return find_col(df,"ONSConstID","ONSCode","ons_id","pcon24cd","ConstituencyID")

def name_col(df:pd.DataFrame)->str|None:
    return find_col(df,"ConstituencyName","Constituency","SeatName","Name")

def country_col(df:pd.DataFrame)->str|None:
    return find_col(df,"Country","CountryName")

def region_col(df:pd.DataFrame)->str|None:
    return find_col(df,"Region","RegionName")

def normalize_country(v:Any)->str:
    s=str(v or "").strip().lower()
    if "england" in s or s in {"eng","1","1.0"}:return "England"
    if "scot" in s or s in {"sco","2","2.0"}:return "Scotland"
    if "wale" in s or s in {"wal","3","3.0"}:return "Wales"
    if "northern ireland" in s or s in {"ni","nir","4","4.0"}:return "Northern Ireland"
    raise ValueError(f"Unrecognised Country value: {v!r}")

def region_key(v:Any,country:str)->str:
    if country=="Scotland":return "scotland"
    if country=="Wales":return "wales"
    if country=="Northern Ireland":return "northern_ireland"
    s=str(v or "").strip().lower()
    if "north east" in s:return "north_east"
    if "north west" in s:return "north_west"
    if "york" in s or "humber" in s:return "yorkshire"
    if "east mid" in s:return "east_midlands"
    if "west mid" in s:return "west_midlands"
    if "east of england" in s or s in {"east","eastern"}:return "east_england"
    if "london" in s:return "london"
    if "south east" in s:return "south_east"
    if "south west" in s:return "south_west"
    # Never silently dump unknown regions into East of England.
    raise ValueError(f"Unrecognised England Region value: {v!r}")

def allowed(p:str,country:str)->bool:
    if p=="snp":return country=="Scotland"
    if p=="pc":return country=="Wales"
    return country!="Northern Ireland"

def winner_col(df:pd.DataFrame,yy:str)->str|None:
    return find_col(df,f"Winner{yy}",f"WinningParty{yy}",f"Winner20{yy}")

def second_col(df:pd.DataFrame,yy:str)->str|None:
    return find_col(df,f"Second{yy}",f"SecondParty{yy}",f"RunnerUp{yy}")

def canonical_party_label(
    value:Any,
    allow_blank:bool=False,
    unknown_sink:set[str]|None=None
)->str|None:
    """Map raw BES WinnerXX/SecondXX labels into model party families.

    The model intentionally aggregates all independents, Speaker and minor
    parties into `other`. Unknown GB labels are therefore safely bucketed into
    `other` *and recorded*. Historical expected-winner counts remain a hard
    integrity gate, so a misspelled/misparsed major party cannot silently pass.
    """
    if value is None or (isinstance(value,float) and np.isnan(value)):
        if allow_blank:return None
        raise ValueError("Missing official winner label")

    s=str(value).strip()
    if not s or s.lower() in {"nan","none","na","n/a"}:
        if allow_blank:return None
        raise ValueError(f"Missing official winner label: {value!r}")

    k=nkey(s)

    mapping={
        "c":"con","con":"con","cons":"con","conservative":"con","conservatives":"con",
        "conservativeparty":"con",

        "lab":"lab","labour":"lab","labourparty":"lab","labcoop":"lab",
        "labourcoop":"lab","labourcooperative":"lab",

        "ld":"ld","libdem":"ld","libdems":"ld","liberaldemocrat":"ld",
        "liberaldemocrats":"ld",

        "green":"green","grn":"green","greenparty":"green","greens":"green",

        "snp":"snp","scottishnationalparty":"snp",

        "pc":"pc","plaid":"pc","plaidcymru":"pc",

        "ukip":"ref","ukindependenceparty":"ref",
        "unitedkingdomindependenceparty":"ref",
        "brexit":"ref","brexitparty":"ref",
        "ruk":"ref","reform":"ref","reformuk":"ref",

        # Speaker labels used in historical constituency datasets.
        "spk":"other","spkr":"other","speaker":"other",
        "thespeaker":"other","commonspeaker":"other",
        "speakerofhouseofcommons":"other","speakerofcommons":"other",

        "ind":"other","inds":"other","independent":"other",
        "independents":"other",

        "other":"other","others":"other","minor":"other","minorparty":"other",
    }
    if k in mapping:
        return mapping[k]

    # Annotated/long-form labels.
    if "conservative" in k:return "con"
    if "labour" in k:return "lab"
    if "liberal" in k and "democrat" in k:return "ld"
    if "scottishnational" in k:return "snp"
    if "plaid" in k:return "pc"
    if "green" in k:return "green"
    if "ukip" in k or "brexit" in k or "reform" in k:return "ref"
    if "speaker" in k or k.startswith("spkr") or k.startswith("spk"):return "other"
    if "independent" in k:return "other"

    # For this model every unmodelled GB minor party belongs to `other`.
    # Record it so the integrity report exposes exactly what was encountered.
    if unknown_sink is not None:
        unknown_sink.add(s)
    return "other"

def competitive_parties(row:pd.Series)->list[str]:
    """Parties allowed to WIN the seat without pooling unrelated 'Other' votes.

    Main parties are always eligible where geographically valid. The aggregate
    'other' bucket becomes a seat-winning competitor only when an Other/
    independent/Speaker candidate was already winner or runner-up in the
    baseline election. This uses baseline information only and prevents a sum
    of several minor candidates from behaving like one artificial super-party.
    """
    country=str(row["country"])
    candidates=[p for p in MAIN_PARTIES if allowed(p,country)]
    if row.get("actual_winner")=="other" or row.get("actual_second")=="other":
        candidates.append("other")
    return candidates

def predicted_winner(predicted_row:pd.Series|dict[str,float],baseline_row:pd.Series)->str:
    candidates=competitive_parties(baseline_row)
    return max(candidates,key=lambda p:float(predicted_row[p]))

def extract_election(df:pd.DataFrame,yy:str)->dict[str,Any]:
    ic=id_col(df); nc=name_col(df); cc=country_col(df); rc=region_col(df)
    if nc is None:raise RuntimeError("BES dataset has no constituency name column")
    if cc is None:raise RuntimeError("BES dataset has no Country column")
    if rc is None:raise RuntimeError("BES dataset has no Region column")

    # IMPORTANT: this model is GB-only. Remove Northern Ireland immediately,
    # before WinnerXX / SecondXX or any party field is interpreted.
    countries=df[cc].map(normalize_country)
    gb_index=countries[countries!="Northern Ireland"].index
    if len(gb_index)!=632:
        counts={k:int(v) for k,v in Counter(countries).items()}
        raise RuntimeError(
            f"Election {yy}: expected exactly 632 GB rows after NI exclusion, "
            f"got {len(gb_index)}; country counts={counts}"
        )

    source=df.loc[gb_index].copy()
    data=pd.DataFrame(index=gb_index)
    data["id"]=source[ic].astype(str) if ic else [f"row-{i}" for i in range(len(source))]
    data["name"]=source[nc].astype(str)
    data["country"]=countries.loc[gb_index]
    data["region"]=[region_key(source.loc[i,rc],data.loc[i,"country"]) for i in gb_index]

    wc=winner_col(source,yy)
    if wc is None:
        raise RuntimeError(f"Election {yy}: BES dataset has no official Winner{yy} column")
    sc=second_col(source,yy)

    unknown_winner_labels=set()
    unknown_second_labels=set()
    data["actual_winner"]=source[wc].map(
        lambda v:canonical_party_label(v,allow_blank=False,unknown_sink=unknown_winner_labels)
    )
    if sc is not None:
        data["actual_second"]=source[sc].map(
            lambda v:canonical_party_label(v,allow_blank=True,unknown_sink=unknown_second_labels)
        )
    else:
        data["actual_second"]=None

    tv=total_vote_col(source,yy)
    total_votes=(
        pd.to_numeric(source[tv],errors="coerce").fillna(0.0)
        if tv else pd.Series(0.0,index=source.index)
    )

    # Prefer vote counts, avoiding all sparse-share unit ambiguities.
    vote_cols={p:party_vote_cols(source,p,yy) for p in MAIN_PARTIES}
    has_vote_basis=bool(tv and vote_cols["lab"] and vote_cols["con"] and vote_cols["ld"])

    if has_vote_basis:
        known_votes={}
        for p in MAIN_PARTIES:
            known_votes[p]=sum_numeric_cols(source,vote_cols[p]).clip(lower=0.0)

        den=total_votes.replace(0,np.nan)
        for p in MAIN_PARTIES:
            data[p]=(known_votes[p]/den*100.0).replace([np.inf,-np.inf],np.nan).fillna(0.0)

        known_sum=sum(known_votes.values())
        other_votes=(total_votes-known_sum).clip(lower=0.0)
        data["other"]=(other_votes/den*100.0).replace([np.inf,-np.inf],np.nan).fillna(0.0)
        data["weight"]=total_votes.clip(lower=1.0)
        share_source="vote_counts"
    else:
        for p in MAIN_PARTIES:
            cols=party_share_cols(source,p,yy)
            if cols:
                series=sum(
                    (normalize_share_series(source[c]) for c in cols),
                    start=pd.Series(0.0,index=source.index,dtype=float)
                )
                data[p]=series
            else:
                data[p]=0.0

        other_cols=party_share_cols(source,"other",yy)
        if other_cols:
            data["other"]=sum(
                (normalize_share_series(source[c]) for c in other_cols),
                start=pd.Series(0.0,index=source.index,dtype=float)
            )
        else:
            data["other"]=(100.0-data[list(MAIN_PARTIES)].sum(axis=1)).clip(lower=0.0)

        data["weight"]=total_votes.clip(lower=1.0) if tv else 1.0
        share_source="published_shares"

    tc=turnout_col(source,yy)
    data["turnout"]=normalize_share_series(source[tc]) if tc else 0.0

    # Enforce party geography and normalize each GB constituency.
    for idx,row in data.iterrows():
        country=row["country"];vals={};total=0.0
        for p in PARTIES:
            v=float(row[p]) if allowed(p,country) else 0.0
            vals[p]=max(0.0,v);total+=vals[p]
        if total<=0:
            raise RuntimeError(f"Election {yy}: zero party-share total in {row['name']}")
        for p in PARTIES:data.at[idx,p]=vals[p]/total*100.0

    if data["actual_winner"].isna().any():
        bad=data.loc[data["actual_winner"].isna(),["id","name"]].head(5).to_dict("records")
        raise RuntimeError(f"Election {yy}: missing official GB winners: {bad}")
    if len(data)!=632:
        raise RuntimeError(f"Election {yy}: expected exactly 632 GB seats, got {len(data)}")
    if data["id"].duplicated().any():
        raise RuntimeError(f"Election {yy}: duplicate constituency IDs")

    row_sums=data[list(PARTIES)].sum(axis=1)
    if float((row_sums-100.0).abs().max())>.02:
        raise RuntimeError(f"Election {yy}: constituency shares do not sum to 100")

    return {
        "year":yy,
        "frame":data,
        "share_source":share_source,
        "ni_filtered_before_party_parsing":True,
        "unknown_winner_labels":sorted(unknown_winner_labels),
        "unknown_second_labels":sorted(unknown_second_labels),
        "raw_winner_labels":sorted({str(x) for x in source[wc].dropna().unique()}),
        "raw_second_labels":sorted({str(x) for x in source[sc].dropna().unique()}) if sc is not None else [],
    }

EXPECTED_COUNTRIES_OLD={"England":533,"Scotland":59,"Wales":40}
EXPECTED_COUNTRIES_NEW={"England":543,"Scotland":57,"Wales":32}
EXPECTED_REGIONS_OLD={
    "north_east":29,"north_west":75,"yorkshire":54,"east_midlands":46,
    "west_midlands":59,"east_england":58,"london":73,"south_east":84,"south_west":55
}
EXPECTED_REGIONS_NEW={
    "north_east":27,"north_west":73,"yorkshire":54,"east_midlands":47,
    "west_midlands":57,"east_england":61,"london":75,"south_east":91,"south_west":58
}
EXPECTED_WINNERS={
    "10":{"con":306,"lab":258,"ld":57,"snp":6,"pc":3,"green":1,"other":1},
    "15":{"con":330,"lab":232,"snp":56,"ld":8,"pc":3,"green":1,"ref":1,"other":1},
    "17":{"con":317,"lab":262,"snp":35,"ld":12,"pc":4,"green":1,"other":1},
    "19":{"con":365,"lab":202,"snp":48,"ld":11,"pc":4,"green":1,"other":1},
    "24":{"lab":411,"con":121,"ld":72,"snp":9,"ref":5,"green":4,"pc":4,"other":6},
}

def actual_winner_counts(election:dict[str,Any])->dict[str,int]:
    counts=Counter(str(v) for v in election["frame"]["actual_winner"])
    return {p:int(counts[p]) for p in PARTIES if counts[p]}

def integrity_record(label:str,election:dict[str,Any],boundary:str,expected_winners:dict[str,int]|None):
    df=election["frame"]
    countries={k:int(v) for k,v in Counter(df["country"]).items()}
    english={k:int(v) for k,v in Counter(df.loc[df["country"]=="England","region"]).items()}
    winners=actual_winner_counts(election)
    exp_countries=EXPECTED_COUNTRIES_NEW if boundary=="new" else EXPECTED_COUNTRIES_OLD
    exp_regions=EXPECTED_REGIONS_NEW if boundary=="new" else EXPECTED_REGIONS_OLD

    errors=[]
    if countries!=exp_countries:
        errors.append(f"countries expected {exp_countries}, got {countries}")
    if english!=exp_regions:
        errors.append(f"English regions expected {exp_regions}, got {english}")
    if expected_winners is not None:
        compact={p:winners.get(p,0) for p in expected_winners}
        if compact!=expected_winners or sum(winners.values())!=632:
            errors.append(f"winner counts expected {expected_winners}, got {winners}")

    # Geographic party sanity.
    scotland=df[df["country"]!="Scotland"]["snp"].abs().max()
    wales=df[df["country"]!="Wales"]["pc"].abs().max()
    if float(scotland)>.001:errors.append(f"SNP non-zero outside Scotland: {scotland}")
    if float(wales)>.001:errors.append(f"Plaid non-zero outside Wales: {wales}")

    return {
        "label":label,
        "year":election["year"],
        "boundary":boundary,
        "share_source":election.get("share_source"),
        "countries":countries,
        "english_regions":english,
        "winner_counts":winners,
        "official_winner_source":True,
        "gb_rows":int(len(df)),
        "ni_filtered_before_party_parsing":bool(election.get("ni_filtered_before_party_parsing")),
        "unknown_winner_labels":election.get("unknown_winner_labels",[]),
        "unknown_second_labels":election.get("unknown_second_labels",[]),
        "raw_winner_labels":election.get("raw_winner_labels",[]),
        "raw_second_labels":election.get("raw_second_labels",[]),
        "other_winner_seats":int((df["actual_winner"]=="other").sum()),
        "other_runnerup_seats":int((df["actual_second"]=="other").sum()),
        "errors":errors,
    }

def run_integrity_checks(elections:list[tuple[str,dict[str,Any],str,dict[str,int]|None]]):
    checks=[integrity_record(label,e,boundary,winners) for label,e,boundary,winners in elections]
    errors=[f"{c['label']}: {err}" for c in checks for err in c["errors"]]
    payload={
        "version":"uk-v095-bes-integrity",
        "generated_at":utcnow().isoformat(),
        "status":"passed" if not errors else "failed",
        "checks":checks,
        "errors":errors,
        "hard_expectations":{
            "2019_actual_gb":EXPECTED_WINNERS["19"],
            "2024_actual_gb":EXPECTED_WINNERS["24"],
            "old_boundaries":EXPECTED_COUNTRIES_OLD,
            "new_boundaries":EXPECTED_COUNTRIES_NEW,
        }
    }
    INTEGRITY_OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    if errors:
        raise RuntimeError("BES integrity checks failed: "+" | ".join(errors))
    return payload

def nat_shares(election:dict[str,Any])->dict[str,float]:
    df=election["frame"]; w=df["weight"].to_numpy(dtype=float)
    den=float(np.sum(w))
    out={}
    for p in PARTIES:
        out[p]=float(np.sum(df[p].to_numpy(dtype=float)*w)/den) if den else 0.0
    s=sum(out.values()) or 1.0
    return {p:out[p]/s*100.0 for p in PARTIES}

def _num(df:pd.DataFrame,col:str|None)->pd.Series:
    if not col:return pd.Series(np.nan,index=df.index,dtype=float)
    return pd.to_numeric(df[col],errors="coerce")

def _sum_named(df:pd.DataFrame,names:list[str])->pd.Series:
    cols=[]
    lookup={nkey(c):c for c in df.columns}
    for n in names:
        c=lookup.get(nkey(n))
        if c:cols.append(c)
    if not cols:return pd.Series(np.nan,index=df.index,dtype=float)
    return df[cols].apply(pd.to_numeric,errors="coerce").sum(axis=1,min_count=1)

def _ratio(num:pd.Series,den:pd.Series)->pd.Series:
    return (num/den.replace(0,np.nan)).replace([np.inf,-np.inf],np.nan)

def demo_frame(df:pd.DataFrame)->pd.DataFrame:
    """
    Build conceptual demographics from either the c11 or c21/c22 fields.
    The returned values are converted to within-dataset percentile ranks,
    which makes the 2011 and 2021/22 census waves comparable.
    """
    cols_norm=[nkey(c) for c in df.columns]
    wave="21" if any(k.startswith("c21") for k in cols_norm) else ("11" if any(k.startswith("c11") for k in cols_norm) else "")
    pre=f"c{wave}" if wave else ""

    def sfx(*suffixes):
        return _sum_named(df,[f"{pre}{x}" for x in suffixes]+list(suffixes))

    age_all=sfx(
        "Age0to4","Age5to9","Age10to15","Age16to19","Age20to24","Age25to29",
        "Age30to34","Age35to39","Age40to44","Age45to49","Age50to54",
        "Age55to59","Age60to64","Age65to69","Age70to74","Age75to79",
        "Age80to84","Age85plus"
    )
    age_young=sfx("Age16to19","Age20to24","Age25to29","Age30to34")
    age_old=sfx("Age65to69","Age70to74","Age75to79","Age80to84","Age85plus")

    tenure_owner=sfx("HouseOutright","HouseMortgage")
    tenure_social=sfx("HouseSocialLA","HouseSocialOther")
    tenure_private=sfx("HousePrivateLandlord","HousePrivateOther")
    tenure_total=tenure_owner+tenure_social+tenure_private

    eth_white=sfx("EthnicityWhite")
    eth_asian=sfx("EthnicityAsian")
    eth_black=sfx("EthnicityBlack")
    eth_mixed=sfx("EthnicityMixed")
    eth_other=sfx("EthnicityOther")
    eth_total=eth_white+eth_asian+eth_black+eth_mixed+eth_other

    employed=sfx("Employed","SelfEmployedwithEmployees","SelfEmployedwithoutEmployees")
    unemployed=sfx("Unemployed","UnemployedFTStudent")
    student=sfx("EmployedFTStudent","InactiveFTStudent")
    retired=sfx("InactiveRetired")
    inactive_home=sfx("InactiveLookingAfterHome")
    inactive_sick=sfx("InactiveLongTermSick")
    activity_total=employed+unemployed+student+retired+inactive_home+inactive_sick

    industry_names=[
        "IndustryAgriculture","IndustryMining","IndustryManufacturing","IndustryElectricitySupply",
        "IndustryWaterSupply","IndustryConstruction","IndustryWholesale","IndustryTransport",
        "IndustryAccommodation","IndustryCommunication","IndustryFinance","IndustryRealEstate",
        "IndustryProfessional","IndustryAdministrative","IndustryPublicAdministration",
        "IndustryEducation","IndustrySocialWork","IndustryOther"
    ]
    industry_total=sfx(*industry_names)
    manufacturing=sfx("IndustryManufacturing")
    professional=sfx("IndustryCommunication","IndustryFinance","IndustryProfessional","IndustryEducation")

    routine=sfx("NSSECSemiRoutine","NSSECRoutine","NSSECNeverWorked","NSSECLongtermUnemployed")
    nssec_cols=[c for c in df.columns if f"{pre}nssec" in nkey(c) or (not pre and "nssec" in nkey(c))]
    nssec_total=(df[nssec_cols].apply(pd.to_numeric,errors="coerce").sum(axis=1,min_count=1)
                 if nssec_cols else pd.Series(np.nan,index=df.index,dtype=float))

    dens_col=find_col(df,f"{pre}PopulationDensity","PopulationDensity")
    density=np.log1p(_num(df,dens_col).clip(lower=0))
    leave_col=find_col(df,"HanrettyLeave","LeaveVote","LeaveShare")
    leave=normalize_share_series(df[leave_col])/100.0 if leave_col else pd.Series(np.nan,index=df.index,dtype=float)

    raw=pd.DataFrame({
        "density":density,
        "young":_ratio(age_young,age_all),
        "old":_ratio(age_old,age_all),
        "owner":_ratio(tenure_owner,tenure_total),
        "social_rent":_ratio(tenure_social,tenure_total),
        "private_rent":_ratio(tenure_private,tenure_total),
        "white":_ratio(eth_white,eth_total),
        "asian":_ratio(eth_asian,eth_total),
        "black":_ratio(eth_black,eth_total),
        "unemployed":_ratio(unemployed,activity_total),
        "student":_ratio(student,activity_total),
        "retired":_ratio(retired,activity_total),
        "manufacturing":_ratio(manufacturing,industry_total),
        "professional":_ratio(professional,industry_total),
        "routine":_ratio(routine,nssec_total),
        "leave":leave,
    },index=df.index)

    # Keep only fields with real cross-sectional information.
    out=pd.DataFrame(index=df.index)
    for c in raw.columns:
        x=pd.to_numeric(raw[c],errors="coerce")
        valid=x.dropna()
        if len(valid)<max(200,int(len(df)*.35)) or valid.nunique()<8:
            continue
        fill=float(valid.median())
        x=x.fillna(fill)
        out[c]=x.rank(method="average",pct=True)-.5
    if len(out.columns)<7:
        raise RuntimeError(f"Only {len(out.columns)} usable demographic features found: {list(out.columns)}")
    return out

def merge_demo(election:dict[str,Any],demo:pd.DataFrame)->dict[str,Any]:
    frame=election["frame"].copy()
    # election frame preserves original index after NI filtering
    d=demo.reindex(frame.index)
    for c in d.columns:frame[f"demo_{c}"]=d[c].astype(float)
    return {"year":election["year"],"frame":frame,"demo_columns":[f"demo_{c}" for c in d.columns]}

def row_context(row:pd.Series,nat_base:dict[str,float],nat_target:dict[str,float],party:str,demo_cols:list[str])->dict[str,float]:
    local={p:float(row[p])/100.0 for p in PARTIES}
    rankable=competitive_parties(row)
    ordered=sorted(rankable,key=lambda p:local[p],reverse=True)

    winner=str(row.get("actual_winner") or ordered[0])
    second=row.get("actual_second")
    if second not in rankable or second==winner:
        second=next((p for p in ordered if p!=winner),ordered[0])

    own_rank=(ordered.index(party)+1) if party in ordered else (len(ordered)+1)
    margin=max(0.0,local.get(winner,0.0)-local.get(second,0.0))

    f={}
    for p in PARTIES:
        f[f"local_{p}"]=local[p]
        f[f"nat_base_{p}"]=float(nat_base[p])/100.0
        f[f"nat_target_{p}"]=float(nat_target[p])/100.0
        delta=(float(nat_target[p])-float(nat_base[p]))/100.0
        f[f"delta_{p}"]=delta
        f[f"local_x_delta_{p}"]=local[p]*delta

    f["own_rank"]=(own_rank-1)/max(1.0,float(len(ordered)))
    f["own_winner"]=1.0 if winner==party else 0.0
    f["own_second"]=1.0 if second==party else 0.0
    f["other_competitive"]=1.0 if "other" in rankable else 0.0
    f["margin"]=margin
    f["turnout"]=float(row.get("turnout",0.0))/100.0
    country=str(row["country"])
    f["is_scotland"]=1.0 if country=="Scotland" else 0.0
    f["is_wales"]=1.0 if country=="Wales" else 0.0

    rk=str(row.get("region") or "")
    for r in REGION_KEYS:f[f"region_{r}"]=1.0 if rk==r else 0.0

    for c in demo_cols:
        f[c]=float(row.get(c,0.0))

    con_drop=max(0.0,(nat_base["con"]-nat_target["con"])/100.0)
    ref_rise=max(0.0,(nat_target["ref"]-nat_base["ref"])/100.0)
    ld_rise=max(0.0,(nat_target["ld"]-nat_base["ld"])/100.0)
    lab_rise=max(0.0,(nat_target["lab"]-nat_base["lab"])/100.0)
    leave=float(row.get("demo_leave",0.0))
    density=float(row.get("demo_density",0.0))

    f.update({
        "con_drop":con_drop,
        "ref_rise":ref_rise,
        "ld_rise":ld_rise,
        "lab_rise":lab_rise,
        "con_winner_x_drop":(1.0 if winner=="con" else 0.0)*con_drop,
        "lab_second_x_condrop":(1.0 if second=="lab" else 0.0)*con_drop,
        "ld_second_x_condrop":(1.0 if second=="ld" else 0.0)*con_drop,
        "ref_leave_x_rise":leave*ref_rise,
        "ref_conbase_x_rise":local["con"]*ref_rise,
        "ld_local_x_condrop":local["ld"]*con_drop,
        "lab_local_x_condrop":local["lab"]*con_drop,
        "density_x_condrop":density*con_drop,
        "density_x_ldrise":density*ld_rise,
        "scotland_x_snpdelta":f["is_scotland"]*f["delta_snp"],
        "wales_x_pcdelta":f["is_wales"]*f["delta_pc"],
    })
    return f

def base_prediction(election:dict[str,Any],target_nat:dict[str,float])->pd.DataFrame:
    df=election["frame"]
    base_nat=nat_shares(election)
    out=pd.DataFrame(index=df.index,columns=PARTIES,dtype=float)
    for idx,row in df.iterrows():
        country=row["country"]; raw={}
        for p in PARTIES:
            if not allowed(p,country):
                raw[p]=0.0;continue
            if p=="other":
                raw[p]=max(float(row[p]),FLOOR_SMALL);continue
            b=max(float(row[p]),FLOOR_MAIN if p in {"lab","con","ref","ld","green"} else FLOOR_SMALL)
            bn=max(.05,base_nat[p]);tn=max(.05,target_nat[p])
            raw[p]=b*(max(.08,tn/bn)**COMMON_LAMBDA)
        s=sum(raw.values()) or 1.0
        for p in PARTIES:out.at[idx,p]=raw[p]/s*100.0
    return out

def weighted_nat_rows(rows:pd.DataFrame,election:dict[str,Any])->dict[str,float]:
    df=election["frame"];w=df["weight"].to_numpy(float);den=float(w.sum()) or 1.0
    return {p:float(np.sum(rows[p].to_numpy(float)*w)/den) for p in PARTIES}

def normalize_target(target:dict[str,float])->dict[str,float]:
    vals={p:max(.0001,float(target.get(p,0.0))) for p in PARTIES}
    s=sum(vals.values()) or 1.0
    return {p:vals[p]/s*100.0 for p in PARTIES}

def rake(rows:pd.DataFrame,election:dict[str,Any],target:dict[str,float])->pd.DataFrame:
    out=rows.copy().astype(float);target=normalize_target(target);df=election["frame"]
    for _ in range(RAKE_ITERATIONS):
        cur=weighted_nat_rows(out,election)
        if max(abs(cur[p]-target[p]) for p in PARTIES)<.01:break
        mult={p:clamp(target[p]/max(.01,cur[p]),.35,3.0) for p in PARTIES}
        for idx,row in df.iterrows():
            country=row["country"];vals={}
            for p in PARTIES:vals[p]=max(.0001,out.at[idx,p]*mult[p]) if allowed(p,country) else 0.0
            s=sum(vals.values()) or 1.0
            for p in PARTIES:out.at[idx,p]=vals[p]/s*100.0
    return out

def feature_matrix(election:dict[str,Any],target_nat:dict[str,float],party:str,feature_names:list[str]|None=None):
    df=election["frame"];base_nat=nat_shares(election)
    demo_cols=[c for c in df.columns if str(c).startswith("demo_")]
    records=[row_context(row,base_nat,target_nat,party,demo_cols) for _,row in df.iterrows()]
    x=pd.DataFrame(records,index=df.index)
    if feature_names is not None:
        for c in feature_names:
            if c not in x:x[c]=0.0
        x=x[feature_names]
    return x.replace([np.inf,-np.inf],0).fillna(0.0)

def build_transition(base:dict[str,Any],actual:dict[str,Any])->dict[str,Any]:
    # The two elections in a historical BES file share rows/boundaries.
    if len(base["frame"])!=len(actual["frame"]):
        raise RuntimeError(f"Transition {base['year']}->{actual['year']}: row count mismatch")
    target=nat_shares(actual)
    base_pred=base_prediction(base,target)
    y={p:(actual["frame"][p]-base_pred[p]).astype(float) for p in PARTIES}
    return {"base":base,"actual":actual,"target":target,"base_pred":base_pred,"residual":y}

def make_estimator(spec:dict[str,Any]):
    if spec["kind"]=="ridge":
        return Pipeline([
            ("scale",StandardScaler()),
            ("ridge",Ridge(alpha=float(spec["alpha"])))
        ])
    if spec["kind"]=="hgb":
        return HistGradientBoostingRegressor(
            loss="squared_error",
            learning_rate=.05,
            max_iter=110,
            max_leaf_nodes=15,
            max_depth=int(spec["depth"]),
            min_samples_leaf=int(spec["leaf"]),
            l2_regularization=float(spec["l2"]),
            random_state=202609,
        )
    raise ValueError(spec["kind"])

def train_models(transitions:list[dict[str,Any]],spec:dict[str,Any]):
    models={};feature_names={}
    kinds=("ridge","hgb") if spec["kind"]=="hybrid" else (spec["kind"],)
    for p in PARTIES:
        xs=[];ys=[]
        for tr in transitions:
            x=feature_matrix(tr["base"],tr["target"],p)
            xs.append(x);ys.append(tr["residual"][p].reindex(x.index))
        all_cols=sorted(set().union(*(set(x.columns) for x in xs)))
        xcat=pd.concat([
            x.reindex(columns=all_cols,fill_value=0.0) for x in xs
        ],axis=0,ignore_index=True)
        ycat=pd.concat([y.reset_index(drop=True) for y in ys],axis=0,ignore_index=True).astype(float)
        feature_names[p]=all_cols

        if spec["kind"]=="hybrid":
            ridge_spec={"kind":"ridge","alpha":spec["alpha"]}
            hgb_spec={"kind":"hgb","depth":spec["depth"],"leaf":spec["leaf"],"l2":spec["l2"]}
            r=make_estimator(ridge_spec);h=make_estimator(hgb_spec)
            r.fit(xcat,ycat);h.fit(xcat,ycat)
            models[p]=(r,h)
        else:
            m=make_estimator(spec);m.fit(xcat,ycat);models[p]=m
    return models,feature_names

def predict_transition(base:dict[str,Any],target:dict[str,float],models,feature_names,spec:dict[str,Any])->pd.DataFrame:
    base_pred=base_prediction(base,target)
    out=base_pred.copy()
    gamma=float(spec.get("gamma",1.0))
    for p in PARTIES:
        x=feature_matrix(base,target,p,feature_names[p])
        if spec["kind"]=="hybrid":
            r,h=models[p]
            wr=float(spec["hgb_weight"])
            corr=(1-wr)*r.predict(x)+wr*h.predict(x)
        else:
            corr=models[p].predict(x)
        out[p]=base_pred[p].to_numpy(float)+gamma*np.asarray(corr,float)

    # Conservative clipping before row normalisation.
    for idx,row in base["frame"].iterrows():
        country=row["country"];vals={}
        for p in PARTIES:
            vals[p]=max(.01,float(out.at[idx,p])) if allowed(p,country) else 0.0
        s=sum(vals.values()) or 1.0
        for p in PARTIES:out.at[idx,p]=vals[p]/s*100.0
    return rake(out,base,target)

def evaluate_rows(rows:pd.DataFrame,actual:dict[str,Any],base:dict[str,Any])->dict[str,Any]:
    df=actual["frame"];base_df=base["frame"]
    pred=Counter();real=Counter();correct=0
    by_region=defaultdict(lambda:[0,0]);share_abs=0.0;share_n=0

    if not df.index.equals(base_df.index):
        raise RuntimeError(f"Evaluation {base['year']}->{actual['year']}: row indexes do not align")

    for idx,row in df.iterrows():
        baseline_row=base_df.loc[idx]
        pw=predicted_winner(rows.loc[idx],baseline_row)
        rw=str(row["actual_winner"])
        pred[pw]+=1;real[rw]+=1
        if pw==rw:
            correct+=1;by_region[row["region"]][0]+=1
        by_region[row["region"]][1]+=1

        # Share MAE is still computed against aggregate Other vote share. It is
        # a vote-share metric, not a claim that pooled Other is one candidate.
        for p in PARTIES:
            if allowed(p,row["country"]):
                share_abs+=abs(float(rows.at[idx,p])-float(row[p]));share_n+=1

    n=len(df)
    err={p:int(pred[p]-real[p]) for p in PARTIES}
    return {
        "winner_accuracy":correct/n,
        "correct_winners":correct,
        "gb_seats":n,
        "predicted_seats":{p:int(pred[p]) for p in PARTIES},
        "actual_seats":{p:int(real[p]) for p in PARTIES},
        "seat_error":err,
        "seat_abs_error_sum":int(sum(abs(v) for v in err.values())),
        "share_mae":share_abs/share_n if share_n else None,
        "winner_source":"official_BES_WinnerXX",
        "other_prediction_rule":"eligible_only_if_baseline_winner_or_runner_up",
        "regional_accuracy":{
            r:{"correct":v[0],"n":v[1],"accuracy":v[0]/v[1] if v[1] else None}
            for r,v in sorted(by_region.items())
        }
    }

def evaluate_baseline(base:dict[str,Any],actual:dict[str,Any])->dict[str,Any]:
    target=nat_shares(actual)
    return evaluate_rows(base_prediction(base,target),actual,base)

def score_tuple(metrics:dict[str,Any])->tuple:
    return (
        metrics["correct_winners"],
        -metrics["seat_abs_error_sum"],
        -(metrics["share_mae"] or 999),
    )

def tune_spec(tr10_15:dict[str,Any],tr15_17:dict[str,Any]):
    candidates=[]
    for spec in MODEL_SPECS:
        models,names=train_models([tr10_15],spec)
        rows=predict_transition(tr15_17["base"],tr15_17["target"],models,names,spec)
        metrics=evaluate_rows(rows,tr15_17["actual"],tr15_17["base"])
        candidates.append({"spec":spec,"metrics":metrics})
    candidates.sort(key=lambda x:score_tuple(x["metrics"]),reverse=True)
    return candidates[0]["spec"],candidates

def calculate_poll_target(path:Path)->tuple[dict[str,float],dict[str,Any]]:
    payload=json.loads(path.read_text(encoding="utf-8"))
    polls=payload.get("polls",[])
    now=utcnow()
    keys=("lab","con","ref","ld","green","snp","pc","other")
    sums={p:0.0 for p in keys};dens={p:0.0 for p in keys};effective=0
    for poll in polls:
        try:d=datetime.fromisoformat(str(poll["date"])+"T12:00:00+00:00")
        except Exception:continue
        age=max(0.0,(now-d).total_seconds()/86400.0)
        if age>100:continue
        temporal=.5**(age/7.0)
        sample=float(poll.get("sample") or 2000)
        sample_w=clamp(math.sqrt(max(500.0,sample)/2000.0),.75,1.25)
        area_w=.97 if str(poll.get("area") or "").upper()=="UK" else 1.0
        w=temporal*sample_w*area_w
        if w>.04:effective+=1
        for p in keys:
            v=poll.get(p)
            if isinstance(v,(int,float)) and math.isfinite(float(v)):
                sums[p]+=w*float(v);dens[p]+=w
    avg={p:(sums[p]/dens[p] if dens[p] else 0.0) for p in keys}
    # Restore Britain is intentionally excluded from constituency conversion,
    # matching the browser model. Renormalise the modelled parties only.
    target=normalize_target(avg)
    return target,{"effective_polls":effective,"raw_average":avg}

def live_projection(current:dict[str,Any],target:dict[str,float],models,names,spec:dict[str,Any])->dict[str,Any]:
    rows=predict_transition(current,target,models,names,spec)
    df=current["frame"];seats=[];totals=Counter()
    for idx,row in df.iterrows():
        winner=predicted_winner(rows.loc[idx],row)
        other_eligible=("other" in competitive_parties(row))
        totals[winner]+=1
        seats.append({
            "id":str(row["id"]),
            "name":str(row["name"]),
            "country":str(row["country"]),
            "region":str(row["region"]),
            "projected":{p:round(float(rows.at[idx,p]),5) for p in PARTIES},
            "centralWinner":winner,
            "otherEligible":bool(other_eligible),
            "baselineWinner":str(row.get("actual_winner") or ""),
            "baselineSecond":str(row.get("actual_second") or ""),
        })
    return {
        "seats":seats,
        "totals":{p:int(totals[p]) for p in PARTIES},
        "other_rule":"Aggregate Other share is not treated as a single candidate; Other can win only if winner/runner-up in the 2024 baseline."
    }

def approval_gate(validation:dict[str,Any],holdout:dict[str,Any],val_base:dict[str,Any],hold_base:dict[str,Any])->tuple[bool,list[str]]:
    reasons=[]
    if holdout["winner_accuracy"]<.80:
        reasons.append("holdout_2024_accuracy_below_80pct")
    if holdout["winner_accuracy"]<hold_base["winner_accuracy"]+.05:
        reasons.append("holdout_gain_below_5pp")
    if holdout["seat_abs_error_sum"]>200:
        reasons.append("holdout_seat_error_above_200")
    if validation["winner_accuracy"]<val_base["winner_accuracy"]-.01:
        reasons.append("validation_accuracy_worse_by_more_than_1pp")
    if validation["seat_abs_error_sum"]>val_base["seat_abs_error_sum"]+30:
        reasons.append("validation_seat_error_worse_by_more_than_30")
    return (not reasons),reasons

def write_failure(exc:Exception):
    payload={
        "version":"uk-v095-mrp-lite",
        "model_type":"constituency-residual-ml-v1",
        "status":"error",
        "approved":False,
        "publication_ready":False,
        "generated_at":utcnow().isoformat(),
        "error":str(exc),
        "traceback_tail":traceback.format_exc().splitlines()[-12:],
        "note":"Shadow model failed to build; production must remain on the v0.8.1 fallback.",
    }
    MODEL_OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    LIVE_OUT.write_text(json.dumps({
        "version":"uk-v095-mrp-lite-live","approved":False,"status":"error",
        "generated_at":utcnow().isoformat(),"seats":[]
    },ensure_ascii=False,indent=2),encoding="utf-8")
    BACKTEST_OUT.write_text(json.dumps({
        "version":"uk-v095-mrp-lite-backtest","status":"error","error":str(exc)
    },ensure_ascii=False,indent=2),encoding="utf-8")
    if not INTEGRITY_OUT.exists():
        INTEGRITY_OUT.write_text(json.dumps({
            "version":"uk-v095-bes-integrity","status":"failed",
            "generated_at":utcnow().isoformat(),"errors":[str(exc)],"checks":[]
        },ensure_ascii=False,indent=2),encoding="utf-8")

def main()->int:
    with tempfile.TemporaryDirectory() as td:
        td=Path(td)
        hist_path,hist_meta=fetch_article_file(HIST_ARTICLE,td)
        curr_path,curr_meta=fetch_article_file(CURR_ARTICLE,td)
        hist_df=read_table(hist_path)
        curr_df=read_table(curr_path)

        hist_demo=demo_frame(hist_df)
        curr_demo=demo_frame(curr_df)

        e10=merge_demo(extract_election(hist_df,"10"),hist_demo)
        e15=merge_demo(extract_election(hist_df,"15"),hist_demo)
        e17=merge_demo(extract_election(hist_df,"17"),hist_demo)
        e19=merge_demo(extract_election(hist_df,"19"),hist_demo)
        e19n=merge_demo(extract_election(curr_df,"19"),curr_demo)
        e24=merge_demo(extract_election(curr_df,"24"),curr_demo)

        # HARD PARSER GATE. No model fitting is allowed before these pass.
        integrity=run_integrity_checks([
            ("2010 actual",e10,"old",EXPECTED_WINNERS["10"]),
            ("2015 actual",e15,"old",EXPECTED_WINNERS["15"]),
            ("2017 actual",e17,"old",EXPECTED_WINNERS["17"]),
            ("2019 actual",e19,"old",EXPECTED_WINNERS["19"]),
            # Notional 2019 on 2024 boundaries: validate geography hard;
            # the notional winner distribution is source-derived, not an official election.
            ("2019 notional on 2024 boundaries",e19n,"new",None),
            ("2024 actual",e24,"new",EXPECTED_WINNERS["24"]),
        ])
        print("BES integrity gate: PASSED")
        for check in integrity["checks"]:
            print(check["label"],check["countries"],check["winner_counts"],check["share_source"])

        t10_15=build_transition(e10,e15)
        t15_17=build_transition(e15,e17)
        t17_19=build_transition(e17,e19)
        t19n_24=build_transition(e19n,e24)

        # Baselines.
        internal_base=evaluate_baseline(e15,e17)
        validation_base=evaluate_baseline(e17,e19)
        holdout_base=evaluate_baseline(e19n,e24)

        # Tune using only pre-validation history.
        selected_spec,tuning=tune_spec(t10_15,t15_17)

        # Unseen validation.
        models_val,names_val=train_models([t10_15,t15_17],selected_spec)
        val_rows=predict_transition(e17,t17_19["target"],models_val,names_val,selected_spec)
        validation=evaluate_rows(val_rows,e19,e17)

        # Genuine holdout. Refit using everything known by the end of 2019.
        models_hold,names_hold=train_models([t10_15,t15_17,t17_19],selected_spec)
        hold_rows=predict_transition(e19n,t19n_24["target"],models_hold,names_hold,selected_spec)
        holdout=evaluate_rows(hold_rows,e24,e19n)

        approved,reasons=approval_gate(validation,holdout,validation_base,holdout_base)
        publication_ready=bool(
            approved
            and holdout["winner_accuracy"]>=.85
            and holdout["seat_abs_error_sum"]<=140
        )

        # Live refit can use 2024 only AFTER the holdout has been scored.
        target_now,poll_meta=calculate_poll_target(DATA/"polls.json")
        models_live,names_live=train_models([t10_15,t15_17,t17_19,t19n_24],selected_spec)
        live=live_projection(e24,target_now,models_live,names_live,selected_spec)

        model_payload={
            "version":"uk-v095-mrp-lite",
            "model_type":"constituency-residual-ml-v1",
            "status":"ok",
            "approved":approved,
            "publication_ready":publication_ready,
            "generated_at":utcnow().isoformat(),
            "selected_spec":selected_spec,
            "hard_gate":{
                "min_holdout_accuracy":.80,
                "min_holdout_gain_pp":5.0,
                "max_holdout_seat_abs_error":200,
                "max_validation_accuracy_loss_pp":1.0,
                "max_validation_seat_error_increase":30,
            },
            "gate_failures":reasons,
            "validation_2019":{
                "baseline":validation_base,
                "candidate":validation,
            },
            "holdout_2024":{
                "baseline":holdout_base,
                "candidate":holdout,
                "accuracy_gain_pp":(holdout["winner_accuracy"]-holdout_base["winner_accuracy"])*100,
                "seat_error_improvement":holdout_base["seat_abs_error_sum"]-holdout["seat_abs_error_sum"],
            },
            "internal_selection_2017":{
                "baseline":internal_base,
                "candidates":[
                    {
                        "spec":x["spec"],
                        "winner_accuracy":x["metrics"]["winner_accuracy"],
                        "correct_winners":x["metrics"]["correct_winners"],
                        "seat_abs_error_sum":x["metrics"]["seat_abs_error_sum"],
                        "share_mae":x["metrics"]["share_mae"],
                    } for x in tuning
                ],
            },
            "features":{
                "historical_demographics":[c.replace("demo_","") for c in e19["demo_columns"]],
                "current_demographics":[c.replace("demo_","") for c in e24["demo_columns"]],
                "notes":"Census fields are converted to within-wave percentile ranks before modelling. Official WinnerXX/SecondXX fields define seat competition; aggregate Other remains a vote-share bucket, not a pooled candidate.",
            },
            "integrity":{
                "version":integrity.get("version"),
                "status":integrity.get("status"),
                "checks":integrity.get("checks"),
            },
            "sources":{
                "historical_bes":hist_meta,
                "current_bes":curr_meta,
            },
            "note":(
                "2024 was not used to choose model family or hyperparameters. "
                "The live refit includes 2024 only after the holdout score is frozen."
            )
        }
        MODEL_OUT.write_text(json.dumps(model_payload,ensure_ascii=False,indent=2),encoding="utf-8")

        live_payload={
            "version":"uk-v095-mrp-lite-live",
            "model_type":"constituency-residual-ml-v1",
            "status":"ok",
            "approved":approved,
            "publication_ready":publication_ready,
            "generated_at":utcnow().isoformat(),
            "model_version":model_payload["version"],
            "selected_spec":selected_spec,
            "target_gb":target_now,
            "poll_meta":poll_meta,
            "holdout_accuracy":holdout["winner_accuracy"],
            "holdout_seat_abs_error":holdout["seat_abs_error_sum"],
            **live,
        }
        LIVE_OUT.write_text(json.dumps(live_payload,ensure_ascii=False,indent=2),encoding="utf-8")

        backtest_payload={
            "version":"uk-v095-mrp-lite-backtest",
            "status":"ok",
            "selected_spec":selected_spec,
            "approved_for_live":approved,
            "publication_ready":publication_ready,
            "validation_2019":{"baseline":validation_base,"candidate":validation},
            "holdout_2024":{"baseline":holdout_base,"candidate":holdout},
            "internal_selection_2017":model_payload["internal_selection_2017"],
        }
        BACKTEST_OUT.write_text(json.dumps(backtest_payload,ensure_ascii=False,indent=2),encoding="utf-8")

        print("v0.9.5 selected spec:",selected_spec)
        print(
            "2019 validation:",
            f"baseline {validation_base['winner_accuracy']:.2%}/{validation_base['seat_abs_error_sum']}",
            f"candidate {validation['winner_accuracy']:.2%}/{validation['seat_abs_error_sum']}"
        )
        print(
            "2024 HOLDOUT:",
            f"baseline {holdout_base['winner_accuracy']:.2%}/{holdout_base['seat_abs_error_sum']}",
            f"candidate {holdout['winner_accuracy']:.2%}/{holdout['seat_abs_error_sum']}"
        )
        print("Approved for beta live:",approved,reasons)
        print("Publication-ready threshold (85% / seat error <=140):",publication_ready)
        print("Live central GB seat totals:",live["totals"])
    return 0

if __name__=="__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"build_mrp_lite.py v0.9.5 shadow build failed: {exc}",file=sys.stderr)
        write_failure(exc)
        # Shadow failure must not break the existing production model.
        raise SystemExit(0)
