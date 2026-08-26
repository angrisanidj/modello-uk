#!/usr/bin/env python3
"""
modello-uk v0.9.17 — remaining-error audit (shadow research)

Freezes the best pre-2024-selected local-election signal found so far: the v0.9.15
reference configuration local_strength=0.25, byelection_strength=0.  That configuration
must reproduce 585/632 with seat error 42 on the 2019 validation election and 501/632
with seat error 166 on the 2024 development benchmark.

v0.9.17 does NOT tune any new parameter and does NOT change the production/canonical
candidate.  It builds a systematic diagnostic of the 131 constituencies still missed by
the v0.9.15 reference: predicted→actual pairs, regions, predicted-margin bands, prior
winner/runner-up structure, party share errors, local-election profile coverage/confidence,
and the exact seats fixed or broken by the local-strength layer relative to the frozen
v0.9.10-equivalent candidate.

The 2024 labels are used for diagnosis only.  No coefficient, threshold, feature set,
rule or promotion decision is selected from this audit.  The next model experiment must
be specified separately and validated with an appropriate historical analogue.
"""
from __future__ import annotations

import io
import json
import math
import re
import sys
import tempfile
import traceback
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
from sklearn.ensemble import HistGradientBoostingRegressor, HistGradientBoostingClassifier
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
DATA.mkdir(exist_ok=True)

MODEL_OUT=DATA/"mrp-lite-model.json"
LIVE_OUT=DATA/"mrp-lite-live.json"
BACKTEST_OUT=DATA/"backtest-v0917-error-audit.json"
INTEGRITY_OUT=DATA/"bes-integrity-v0917.json"
DIAGNOSTIC_OUT=DATA/"error-audit-v0917.json"
SWEEP_OUT=DATA/"v0915-reference-v0917.json"

HIST_ARTICLE=20278599
CURR_ARTICLE=28430672
FIGSHARE_API="https://api.figshare.com/v2/articles/{article_id}"

PARTIES=("lab","con","ref","ld","green","snp","pc","other")
MAIN_PARTIES=("lab","con","ref","ld","green","snp","pc")
COMMON_LAMBDA=.82
FLOOR_MAIN=.18
FLOOR_SMALL=.03
RAKE_ITERATIONS=80

# Legacy structural-sweep constants retained for reproducibility; unused by the v0.9.17 audit.
REGRADE_PARTIES=("lab","con","ld","green","snp","pc")
REGRADE_STRENGTH_GRID=(0.0,0.25,0.50,0.75,1.00,1.25)
PLACE_REGION_STRENGTH_GRID=(0.0,0.50,1.00)
PLACE_COMP_STRENGTH_GRID=(0.0,0.50,1.00)
REGRADE_SIMILARITY_TAU=0.80
REGRADE_MAX_DELTA_SLOPE=0.65
REGRADE_MAX_SEAT_SHIFT=7.5
PLACE_REGION_PRIOR_N=14.0
PLACE_COMP_PRIOR_N=10.0
PLACE_MAX_SEAT_SHIFT=6.0

# Local-election source constants reused to reproduce the frozen v0.9.15 reference.
# v0.9.17 performs no strength sweep and keeps by-election strength at zero.
DC_EXPORT_URL="https://candidates.democracyclub.org.uk/data/export_csv/"
LOCAL_DATES_2019=("2017-05-04","2018-05-03","2019-05-02")
LOCAL_DATES_2024=("2019-05-02","2021-05-06","2022-05-05","2023-05-04","2024-05-02")
LOCAL_STRENGTH_GRID=(0.0,0.10,0.15,0.20,0.25,0.30,0.35,0.40,0.50)
LOCAL_CONFIDENCE_FLOOR_GRID=(0.0,0.35,0.55)
LOCAL_MARGIN_CAP_GRID=(None,15.0,25.0)
LOCAL_RECENCY_HALF_LIFE_YEARS=2.5
BYELECTION_RECENCY_HALF_LIFE_YEARS=0.75
LOCAL_MAX_SEAT_SHIFT=8.0
BYELECTION_MAX_SEAT_SHIFT=8.0
V0915_REFERENCE={"local_strength":0.25,"confidence_floor":0.0,"margin_cap":None}
ONS_LOOKUPS={
    "2019":{
        # Prefer ONS/Open Geography public Hub CSV downloads.  The underlying
        # FeatureServer was republished in 2026 and may now answer public REST
        # queries with Token Required, while the Hub CSV remains public.
        # The LAD-only item is sufficient for this model and currently has a
        # cached public CSV; the CTYUA item is retained as a second Hub fallback.
        "downloads":(
            "https://open-geography-portalx-ons.hub.arcgis.com/api/download/v1/items/552d79e95b30497bb073a9ac79c6a641/csv?layers=0",
            "https://open-geography-portalx-ons.hub.arcgis.com/api/download/v1/items/4fed3ee9994c4361bd8122c31bf1885f/csv?layers=0",
        ),
        "queries":(
            "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/WD19_PCON19_LAD19_UTLA19_UK_LU_e5a0b74eff43407b86dcc7a4300ceb25/FeatureServer/0/query",
            "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/WD19_PCON19_LAD19_UK_LU_2b79d5f36feb42938063932a4d4a3533/FeatureServer/0/query",
        ),
        "pcon":"PCON19NM","lad":"LAD19NM",
    },
    "2024":{
        "downloads":(
            "https://open-geography-portalx-ons.hub.arcgis.com/api/download/v1/items/62eb9df29a2f4521b5076a419ff9a47e/csv?layers=0",
        ),
        "queries":(),
        "pcon":"PCON24NM","lad":"LAD24NM",
    },
}

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

CONTEST_SPECS=(
    {"name":"none","kind":"none","strength":0.0},
    {"name":"logit_c025_s025","kind":"logit","C":0.25,"strength":0.25},
    {"name":"logit_c025_s040","kind":"logit","C":0.25,"strength":0.40},
    {"name":"logit_c100_s025","kind":"logit","C":1.00,"strength":0.25},
    {"name":"logit_c100_s040","kind":"logit","C":1.00,"strength":0.40},
    {"name":"logit_c300_s040","kind":"logit","C":3.00,"strength":0.40},
    {"name":"hgb_d2_s025","kind":"hgb","depth":2,"leaf":30,"l2":4.0,"strength":0.25},
    {"name":"hgb_d2_s040","kind":"hgb","depth":2,"leaf":30,"l2":4.0,"strength":0.40},
    {"name":"hgb_d3_s025","kind":"hgb","depth":3,"leaf":36,"l2":6.0,"strength":0.25},
)


# v0.9.8: party-specific calibration. The pooled classifier architecture is
# frozen to the v0.9.7 winner (logit C=3); only party-specific application
# strengths are selected on the 2017 development election.
PARTY_CONTEST_BASE_SPEC={"name":"logit_c300","kind":"logit","C":3.0}
PARTY_STRENGTH_GRID={
    "lab":(0.0,0.15,0.30,0.45,0.60),
    "con":(0.0,0.15,0.30,0.45,0.60),
    "ref":(0.0,0.20,0.40,0.60,0.80),
    "ld":(0.0,0.20,0.40,0.60,0.80),
    "green":(0.0,0.15,0.30,0.45),
    "snp":(0.0,0.15,0.30,0.45,0.60),
    "pc":(0.0,0.15,0.30,0.45,0.60),
    "other":(0.0,),
}
DISPERSION_BOUNDS={
    "ref":(0.35,1.15),
    "ld":(0.65,1.85),
    "snp":(0.65,1.65),
    "pc":(0.65,1.65),
    "green":(0.55,1.55),
    "lab":(0.65,1.45),
    "con":(0.65,1.45),
    "other":(0.80,1.20),
}
DISPERSION_SIMILARITY_TAU=0.70


# v0.9.9 scenario activation.
# "Turnover" is total variation in the national party vector between baseline
# and target.  The correction is deliberately weak in low-change elections and
# strong only once the system experiences a large reallocation of votes.
SCENARIO_TURNOVER_LOW=6.0
SCENARIO_TURNOVER_HIGH=18.0
SCENARIO_OWN_CHANGE_FULL=8.0
SCENARIO_CON_DROP_FULL=15.0
SCENARIO_REF_RISE_FULL=8.0


# v0.9.10 incumbent-collapse routing.
# The strength grid is selected ONLY on 2015->2017, where the SNP provides a
# genuine historical example of a previously dominant incumbent party losing a
# large fraction of its support and seats.
INCUMBENT_DECLINE_REL_LOW=0.10
INCUMBENT_DECLINE_REL_FULL=0.30
ROUTING_STRENGTH_GRID=(0.0,0.20,0.40,0.60,0.80)
UNWIND_STRENGTH_GRID=(0.0,0.15,0.30,0.45,0.60)


# Legacy latent Reform/Brexit constants retained for reproducibility; these values are fixed a priori and
# are NOT tuned on 2024. 2015 UKIP is the donor because it contested almost the
# whole country and predates both the 2019 Brexit Party withdrawal strategy and
# the 2024 benchmark. The latent prior changes geography only: nat_shares()
# always uses actually cast votes, and final raking still enforces the target.
REF_LATENT_DONOR_YEAR="15"
REF_LATENT_RIDGE_ALPHA=20.0
REF_LATENT_COVERAGE_ZERO=0.75
REF_LATENT_COVERAGE_FULL=0.40
REF_LATENT_RISE_ZERO=3.0
REF_LATENT_RISE_FULL=8.0
REF_LATENT_MIN_TRAIN=450
REF_CALIBRATION_RIDGE_ALPHA=10.0


UA="FocusAmerica-UK-election-model/0.9.14 (+https://angrisanidj.github.io/modello-uk/)"

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

def ref_primary_cols(df:pd.DataFrame,yy:str,votes:bool=False)->list[str]:
    """Columns for the principal Reform-family vehicle in a given election.

    This deliberately distinguishes the 2019 Brexit Party from residual UKIP.
    A small UKIP candidacy in a seat where the Brexit Party stood down must not
    make that seat look like an observed Brexit/Reform geography.
    """
    suffix="Vote" if votes else ""
    if yy=="19":
        names=[f"Brexit{suffix}{yy}",f"Brx{suffix}{yy}",f"BrexitParty{suffix}{yy}"]
    elif yy in {"24","25","26","27","28","29","30"}:
        names=[f"RUK{suffix}{yy}",f"Reform{suffix}{yy}",f"ReformUK{suffix}{yy}"]
    else:
        names=[f"UKIP{suffix}{yy}",f"UKIndependence{suffix}{yy}"]
    # Some datasets place the year before Vote (e.g. UKIPVote15); include both.
    alt=[]
    if votes:
        if yy=="19": alt=[f"BrexitVote{yy}",f"BrxVote{yy}",f"BrexitPartyVote{yy}"]
        elif yy in {"24","25","26","27","28","29","30"}: alt=[f"RUKVote{yy}",f"ReformVote{yy}",f"ReformUKVote{yy}"]
        else: alt=[f"UKIPVote{yy}",f"UKIndependenceVote{yy}"]
    return find_cols(df,*(names+alt))


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

    # Candidate-entry metadata for the principal Reform-family vehicle.
    # This is baseline-election information, never a future-election label.
    primary_vote_cols=ref_primary_cols(source,yy,votes=True)
    primary_share_cols=ref_primary_cols(source,yy,votes=False)
    if primary_vote_cols:
        primary_votes=sum_numeric_cols(source,primary_vote_cols)
        data["ref_primary_stood"]=(primary_votes>0.5)
        primary_source="vote_counts"
    elif primary_share_cols:
        primary_share=sum(
            (normalize_share_series(source[c]) for c in primary_share_cols),
            start=pd.Series(0.0,index=source.index,dtype=float)
        )
        data["ref_primary_stood"]=(primary_share>1e-6)
        primary_source="published_shares"
    else:
        # Fail-safe: if the specific vehicle cannot be separated, treat a
        # positive aggregate family share as evidence that it contested.
        data["ref_primary_stood"]=(data["ref"]>1e-6)
        primary_source="aggregate_family_fallback"

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
        "ref_primary_source":primary_source,
        "ref_primary_stood_count":int(data["ref_primary_stood"].sum()),
        "ref_primary_coverage":float(data["ref_primary_stood"].mean()),
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
        "ref_primary_source":election.get("ref_primary_source"),
        "ref_primary_stood_count":election.get("ref_primary_stood_count"),
        "ref_primary_coverage":election.get("ref_primary_coverage"),
        "errors":errors,
    }

def run_integrity_checks(elections:list[tuple[str,dict[str,Any],str,dict[str,int]|None]]):
    checks=[integrity_record(label,e,boundary,winners) for label,e,boundary,winners in elections]
    errors=[f"{c['label']}: {err}" for c in checks for err in c["errors"]]
    payload={
        "version":"uk-v0917-bes-integrity",
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
    """Attach demographic features without losing parser/integrity metadata."""
    frame=election["frame"].copy()
    # election frame preserves original index after NI filtering
    d=demo.reindex(frame.index)
    for c in d.columns:
        frame[f"demo_{c}"]=d[c].astype(float)

    # Preserve share_source, NI-filter flag and raw/unknown label diagnostics.
    merged=dict(election)
    merged["frame"]=frame
    merged["demo_columns"]=[f"demo_{c}" for c in d.columns]
    return merged

def _latent_ref_design(election:dict[str,Any],feature_names:list[str]|None=None)->pd.DataFrame:
    """Ex-ante design matrix for the fixed 2015 UKIP donor model."""
    df=election["frame"]
    demo_cols=[c for c in df.columns if str(c).startswith("demo_")]
    records=[]
    for _,row in df.iterrows():
        rec={
            "con":float(row["con"])/100.0,"lab":float(row["lab"])/100.0,
            "ld":float(row["ld"])/100.0,"green":float(row["green"])/100.0,
            "snp":float(row["snp"])/100.0,"pc":float(row["pc"])/100.0,
            "other":float(row["other"])/100.0,"turnout":float(row.get("turnout",0.0))/100.0,
        }
        winner=str(row.get("actual_winner") or "")
        second=str(row.get("actual_second") or "")
        for p in PARTIES:
            rec[f"winner_{p}"]=1.0 if winner==p else 0.0
            rec[f"second_{p}"]=1.0 if second==p else 0.0
        country=str(row.get("country") or "")
        rec["is_scotland"]=1.0 if country=="Scotland" else 0.0
        rec["is_wales"]=1.0 if country=="Wales" else 0.0
        rk=str(row.get("region") or "")
        for r in REGION_KEYS: rec[f"region_{r}"]=1.0 if rk==r else 0.0
        for c in demo_cols: rec[c]=float(row.get(c,0.0))
        records.append(rec)
    x=pd.DataFrame(records,index=df.index).replace([np.inf,-np.inf],0).fillna(0.0)
    if feature_names is not None:
        for c in feature_names:
            if c not in x: x[c]=0.0
        x=x[feature_names]
    return x

def fit_ref_latent_donor(donor:dict[str,Any]):
    """Fit the fixed latent geography model using only the 2015 UKIP cross-section."""
    if donor.get("year")!=REF_LATENT_DONOR_YEAR:
        raise RuntimeError(f"Latent Reform donor must be {REF_LATENT_DONOR_YEAR}, got {donor.get('year')}")
    df=donor["frame"]
    mask=df["ref_primary_stood"].astype(bool)
    n=int(mask.sum())
    if n<REF_LATENT_MIN_TRAIN:
        raise RuntimeError(f"Only {n} donor seats have an observed principal Reform-family candidate")
    x=_latent_ref_design(donor)
    names=list(x.columns)
    model=Pipeline([("scale",StandardScaler()),("ridge",Ridge(alpha=REF_LATENT_RIDGE_ALPHA))])
    y=np.log1p(df.loc[mask,"ref"].astype(float).clip(lower=0.0))
    model.fit(x.loc[mask],y)
    fitted=np.expm1(model.predict(x.loc[mask]))
    mae=float(np.mean(np.abs(fitted-df.loc[mask,"ref"].to_numpy(float))))
    return model,names,{
        "donor_year":donor["year"],"training_seats":n,"ridge_alpha":REF_LATENT_RIDGE_ALPHA,
        "in_sample_mae_pp":mae,"uses_2024":False,"parameter_tuning":False,
    }

def attach_ref_latent(election:dict[str,Any],model,names:list[str],donor_meta:dict[str,Any])->dict[str,Any]:
    """Attach a latent geographic prior; do not change any observed vote share."""
    out=dict(election); frame=election["frame"].copy()
    x=_latent_ref_design(election,names)
    pred=np.expm1(model.predict(x))
    # Fixed, broad plausibility bounds; final national target is still imposed by raking.
    pred=np.clip(pred,0.25,35.0)
    stood=frame["ref_primary_stood"].astype(bool).to_numpy()
    observed=frame["ref"].to_numpy(float)
    # Keep the canonical model safe: attaching the donor NEVER changes the
    # baseline geography by itself. Experimental geography is applied only to
    # explicit sweep copies below.
    frame["ref_latent_share"]=pred
    frame["ref_latent_raw_share"]=pred
    frame["ref_geo_share"]=observed
    coverage=float(np.mean(stood))
    frame["ref_primary_coverage"]=coverage
    out["frame"]=frame
    out["ref_latent_meta"]={
        **donor_meta,
        "target_base_year":election.get("year"),
        "principal_candidate_source":election.get("ref_primary_source"),
        "principal_stood_count":int(np.sum(stood)),
        "principal_coverage":coverage,
        "imputed_seats":int(np.sum(~stood)),
        "mean_latent_imputed_share_pp":float(np.mean(pred[~stood])) if np.any(~stood) else None,
        "observed_national_share_unchanged":True,
    }
    return out

def ref_latent_activation(row:pd.Series,nat_base:dict[str,float],nat_target:dict[str,float])->float:
    """Pre-specified activation based only on baseline coverage and national swing."""
    coverage=float(row.get("ref_primary_coverage",1.0))
    rise=max(0.0,float(nat_target.get("ref",0.0))-float(nat_base.get("ref",0.0)))
    coverage_need=clamp(
        (REF_LATENT_COVERAGE_ZERO-coverage)/max(1e-9,REF_LATENT_COVERAGE_ZERO-REF_LATENT_COVERAGE_FULL),
        0.0,1.0
    )
    rise_need=clamp(
        (rise-REF_LATENT_RISE_ZERO)/max(1e-9,REF_LATENT_RISE_FULL-REF_LATENT_RISE_ZERO),
        0.0,1.0
    )
    return coverage_need*rise_need

def effective_ref_share(row:pd.Series,nat_base:dict[str,float],nat_target:dict[str,float])->float:
    observed=float(row.get("ref",0.0))
    if "ref_geo_share" not in row.index:
        return observed
    a=ref_latent_activation(row,nat_base,nat_target)
    geo=float(row.get("ref_geo_share",observed))
    return observed+a*(geo-observed)

def ref_latent_audit(election:dict[str,Any],target:dict[str,float])->dict[str,Any]:
    df=election["frame"]; base=nat_shares(election)
    acts=[ref_latent_activation(row,base,target) for _,row in df.iterrows()]
    eff=[effective_ref_share(row,base,target) for _,row in df.iterrows()]
    return {
        "base_year":election.get("year"),
        "national_ref_base":base.get("ref"),"national_ref_target":target.get("ref"),
        "national_ref_rise_pp":float(target.get("ref",0.0)-base.get("ref",0.0)),
        "principal_coverage":float(df.get("ref_primary_coverage",pd.Series([1.0])).iloc[0]),
        "activation":float(acts[0]) if acts else 0.0,
        "imputed_seats":int((~df["ref_primary_stood"].astype(bool)).sum()),
        "mean_effective_ref_prior_pp":float(np.mean(eff)),
        "observed_national_share_unchanged":True,
        "target_enforced_by_raking":True,
    }

def fit_ref_2019_calibrator(election:dict[str,Any])->tuple[dict[str,Any],dict[str,Any]]:
    """Calibrate the 2015 UKIP latent score to observed 2019 Brexit support.

    Only constituencies where the principal Reform-family vehicle actually stood
    are used. This is a pre-2024 missing-data calibration, not a 2024 fit.
    """
    out=dict(election); frame=election["frame"].copy()
    if "ref_latent_share" not in frame:
        raise RuntimeError("Latent Reform donor must be attached before 2019 calibration")
    stood=frame["ref_primary_stood"].astype(bool)
    if int(stood.sum())<200:
        raise RuntimeError(f"Too few observed 2019 Brexit seats for calibration: {int(stood.sum())}")

    x=pd.DataFrame(index=frame.index)
    x["latent_log"]=np.log1p(frame["ref_latent_share"].astype(float).clip(lower=0.0))
    for p in ("con","lab","ld","green"):
        x[f"share_{p}"]=frame[p].astype(float)/100.0
    x["leave"]=frame.get("demo_leave",pd.Series(0.0,index=frame.index)).astype(float)
    x["winner_con"]=(frame["actual_winner"].astype(str)=="con").astype(float)
    x["second_con"]=(frame["actual_second"].astype(str)=="con").astype(float)
    x=x.replace([np.inf,-np.inf],0.0).fillna(0.0)

    model=Pipeline([
        ("scale",StandardScaler()),
        ("ridge",Ridge(alpha=REF_CALIBRATION_RIDGE_ALPHA))
    ])
    y=np.log1p(frame.loc[stood,"ref"].astype(float).clip(lower=0.0))
    model.fit(x.loc[stood],y)
    pred=np.expm1(model.predict(x))
    pred=np.clip(pred,0.05,35.0)
    fitted=pred[stood.to_numpy()]
    actual=frame.loc[stood,"ref"].to_numpy(float)
    frame["ref_calibrated_share"]=pred
    out["frame"]=frame
    meta={
        "base_year":election.get("year"),
        "training_seats":int(stood.sum()),
        "ridge_alpha":REF_CALIBRATION_RIDGE_ALPHA,
        "in_sample_mae_pp":float(np.mean(np.abs(fitted-actual))),
        "uses_2024":False,
        "parameter_tuning":False,
        "features":list(x.columns),
    }
    out["ref_2019_calibration_meta"]=meta
    return out,meta


def make_ref_geo_variant(
    election:dict[str,Any],mode:str,strength_scale:float,normalize_swing_base:bool=False
)->dict[str,Any]:
    """Return a copy with an explicit Reform geography experiment.

    `strength_scale` multiplies the pre-specified coverage/rise activation. The
    sweep is diagnostic-only; no value is selected for live use.
    """
    out=dict(election); frame=election["frame"].copy()
    observed=frame["ref"].astype(float).to_numpy()
    stood=frame["ref_primary_stood"].astype(bool).to_numpy()
    winner=frame["actual_winner"].astype(str).to_numpy()
    raw=frame.get("ref_latent_raw_share",frame.get("ref_latent_share",frame["ref"])).astype(float).to_numpy()
    calibrated=frame.get("ref_calibrated_share",frame["ref"]).astype(float).to_numpy()

    if mode=="baseline":
        candidate=observed.copy()
    elif mode=="raw_all":
        candidate=np.where(~stood,raw,observed)
    elif mode=="calibrated_all":
        candidate=np.where(~stood,calibrated,observed)
    elif mode=="calibrated_con":
        candidate=np.where((~stood)&(winner=="con"),calibrated,observed)
    else:
        raise ValueError(f"Unknown Reform geography sweep mode: {mode}")

    scale=max(0.0,float(strength_scale))
    geo=observed+scale*(candidate-observed)
    frame["ref_geo_share"]=np.clip(geo,0.0,35.0)
    pseudo_nat=None
    if normalize_swing_base and mode!="baseline":
        w=frame["weight"].to_numpy(float)
        den=float(w.sum()) or 1.0
        pseudo_nat=float(np.sum(np.asarray(candidate,float)*w)/den)
        frame["ref_swing_base_nat"]=pseudo_nat
    frame["ref_sweep_mode"]=mode
    frame["ref_sweep_strength_scale"]=scale
    frame["ref_sweep_normalize_swing_base"]=bool(normalize_swing_base)
    out["frame"]=frame
    out["ref_sweep_variant"]={
        "mode":mode,"strength_scale":scale,
        "normalize_swing_base":bool(normalize_swing_base),
        "counterfactual_ref_national_base":pseudo_nat,
    }
    return out


def reform_confusion_summary(rows:pd.DataFrame,actual:dict[str,Any],base:dict[str,Any])->dict[str,Any]:
    tp=fp=fn=tn=0
    fp_best_nonref_correct=0
    for idx,actual_row in actual["frame"].iterrows():
        base_row=base["frame"].loc[idx]
        pw=predicted_winner(rows.loc[idx],base_row)
        rw=str(actual_row["actual_winner"])
        pred_ref=(pw=="ref"); real_ref=(rw=="ref")
        if pred_ref and real_ref: tp+=1
        elif pred_ref and not real_ref:
            fp+=1
            parties=[p for p in competitive_parties(base_row) if p!="ref"]
            best=max(parties,key=lambda p:float(rows.at[idx,p])) if parties else None
            fp_best_nonref_correct+=int(best==rw)
        elif (not pred_ref) and real_ref: fn+=1
        else: tn+=1
    return {
        "true_positive":tp,"false_positive":fp,"false_negative":fn,"true_negative":tn,
        "precision":tp/(tp+fp) if tp+fp else None,
        "recall":tp/(tp+fn) if tp+fn else None,
        "false_positives_recoverable_by_best_nonref":fp_best_nonref_correct,
    }


def evaluate_ref_structural_sweep(
    master_base:dict[str,Any],actual:dict[str,Any],target:dict[str,float],
    models_hold:dict[str,Any],names_hold:dict[str,list[str]],selected_spec:dict[str,Any],
    history:list[dict[str,Any]],training_transitions:list[dict[str,Any]],
    selected_party_strengths:dict[str,float],selected_routing:dict[str,float],
    validation:dict[str,Any],validation_base:dict[str,Any],holdout_base:dict[str,Any]
)->dict[str,Any]:
    specs=[
        {"id":"baseline_v0910","mode":"baseline","strength_scale":0.0},
        {"id":"raw_latent_v0912","mode":"raw_all","strength_scale":1.0},
        {"id":"calibrated_all_half","mode":"calibrated_all","strength_scale":0.5},
        {"id":"calibrated_all_current","mode":"calibrated_all","strength_scale":1.0},
        {"id":"calibrated_all_strong","mode":"calibrated_all","strength_scale":1.5},
        {"id":"calibrated_con_half","mode":"calibrated_con","strength_scale":0.5},
        {"id":"calibrated_con_current","mode":"calibrated_con","strength_scale":1.0},
        {"id":"calibrated_con_strong","mode":"calibrated_con","strength_scale":1.5},
        {"id":"calibrated_all_norm_current","mode":"calibrated_all","strength_scale":1.0,"normalize_swing_base":True},
        {"id":"calibrated_con_norm_current","mode":"calibrated_con","strength_scale":1.0,"normalize_swing_base":True},
        {"id":"calibrated_con_norm_strong","mode":"calibrated_con","strength_scale":1.5,"normalize_swing_base":True},
    ]
    rows_out=[]
    baseline_metrics=None
    for spec in specs:
        base=make_ref_geo_variant(
            master_base,spec["mode"],spec["strength_scale"],
            bool(spec.get("normalize_swing_base",False))
        )
        raw=predict_transition(base,target,models_hold,names_hold,selected_spec)
        share_only=evaluate_rows(raw,actual,base)
        pre,disp,scores=apply_party_calibration(
            raw,base,target,history,training_transitions,selected_party_strengths
        )
        routed,routing_audit=route_incumbent_collapse(
            pre,base,target,
            selected_routing["route_strength"],selected_routing["unwind_strength"]
        )
        metrics=evaluate_rows(routed,actual,base)
        gate_ok,gate_reasons=approval_gate(validation,metrics,validation_base,holdout_base)
        rec={
            **spec,
            "activation":ref_latent_audit(base,target).get("activation"),
            "counterfactual_ref_national_base":base.get("ref_sweep_variant",{}).get("counterfactual_ref_national_base"),
            "metrics":metrics,
            "share_only":share_only,
            "reform":reform_confusion_summary(routed,actual,base),
            "candidate_gate_passed":gate_ok,
            "gate_failures":gate_reasons,
            "routing":routing_audit,
        }
        rows_out.append(rec)
        if spec["id"]=="baseline_v0910": baseline_metrics=metrics

    if baseline_metrics is None:
        raise RuntimeError("Structural sweep did not produce baseline_v0910")
    for rec in rows_out:
        m=rec["metrics"]
        rec["delta_vs_baseline"]={
            "correct_winners":int(m["correct_winners"]-baseline_metrics["correct_winners"]),
            "accuracy_pp":float((m["winner_accuracy"]-baseline_metrics["winner_accuracy"])*100.0),
            "seat_abs_error":int(m["seat_abs_error_sum"]-baseline_metrics["seat_abs_error_sum"]),
            "reform_seats":int(m["predicted_seats"]["ref"]-baseline_metrics["predicted_seats"]["ref"]),
        }
    ranked=sorted(
        rows_out,
        key=lambda r:(r["metrics"]["correct_winners"],-r["metrics"]["seat_abs_error_sum"],-(r["metrics"]["share_mae"] or 999)),
        reverse=True,
    )
    return {
        "version":"uk-v0917-error-audit",
        "status":"ok",
        "generated_at":utcnow().isoformat(),
        "diagnostic_only":True,
        "used_for_parameter_selection":False,
        "changes_production_model":False,
        "selection_policy":"No sweep variant is selected or promoted from the 2024 development benchmark.",
        "benchmark":"2019_notional_to_2024",
        "variants":rows_out,
        "development_ranking":[r["id"] for r in ranked],
        "best_development_variant":ranked[0]["id"],
        "passing_variants":[r["id"] for r in rows_out if r["candidate_gate_passed"]],
    }

def row_context(row:pd.Series,nat_base:dict[str,float],nat_target:dict[str,float],party:str,demo_cols:list[str])->dict[str,float]:
    local={p:float(row[p])/100.0 for p in PARTIES}
    local["ref"]=effective_ref_share(row,nat_base,nat_target)/100.0
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
    # Isolation rule: latent-prior metadata is deliberately NOT added
    # as ML features. When activation is zero, the residual/contest models must
    # have exactly the same feature space as v0.9.10. The latent layer changes
    # geography only through local["ref"] / base_prediction when activated.
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
            local_value=effective_ref_share(row,base_nat,target_nat) if p=="ref" else float(row[p])
            b=max(local_value,FLOOR_MAIN if p in {"lab","con","ref","ld","green"} else FLOOR_SMALL)
            if p=="ref":
                # Experimental sweep copies may supply a pre-2024 estimate of
                # Reform's full-contestation 2019 national base. Canonical
                # elections have no such column and remain bit-for-bit unchanged.
                bn=max(.05,float(row.get("ref_swing_base_nat",base_nat[p])))
            else:
                bn=max(.05,base_nat[p])
            tn=max(.05,target_nat[p])
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


def contest_feature_record(
    row:pd.Series,
    nat_base:dict[str,float],
    nat_target:dict[str,float],
    swing_row:pd.Series,
    party:str,
    demo_cols:list[str]
)->dict[str,float]:
    """Party-seat features for the FPTP contestability layer.

    Everything here is knowable from the baseline election, demographics and
    the national target. The future election's local result is never a feature.
    """
    f=row_context(row,nat_base,nat_target,party,demo_cols)
    local={p:float(row[p])/100.0 for p in PARTIES}
    local["ref"]=effective_ref_share(row,nat_base,nat_target)/100.0
    allowed_main=[p for p in MAIN_PARTIES if allowed(p,str(row["country"]))]
    ordered=sorted(allowed_main,key=lambda p:local[p],reverse=True)

    f["swing_share"]=float(swing_row.get(party,0.0))/100.0
    f["local_party_share"]=local.get(party,0.0)
    f["target_party_share"]=float(nat_target.get(party,0.0))/100.0
    f["base_party_share"]=float(nat_base.get(party,0.0))/100.0
    f["national_change_party"]=(float(nat_target.get(party,0.0))-float(nat_base.get(party,0.0)))/100.0

    top1=local[ordered[0]] if ordered else 0.0
    top2=local[ordered[1]] if len(ordered)>1 else 0.0
    f["baseline_top1"]=top1
    f["baseline_top2"]=top2
    f["baseline_top2_sum"]=top1+top2
    f["baseline_fragmentation"]=1.0-sum(local[p]**2 for p in allowed_main)
    f["distance_to_top"]=local.get(party,0.0)-top1
    f["distance_to_second"]=local.get(party,0.0)-top2

    winner=str(row.get("actual_winner") or "")
    second=str(row.get("actual_second") or "")
    f["incumbent_party_proxy"]=1.0 if winner==party else 0.0
    f["runnerup_party_proxy"]=1.0 if second==party else 0.0
    f["challenger_to_con"]=1.0 if winner=="con" and party!="con" else 0.0
    f["challenger_to_lab"]=1.0 if winner=="lab" and party!="lab" else 0.0
    f["ld_target_con"]=1.0 if party=="ld" and winner=="con" and second=="ld" else 0.0
    f["lab_target_con"]=1.0 if party=="lab" and winner=="con" and second=="lab" else 0.0
    f["ref_target_con"]=1.0 if party=="ref" and winner=="con" else 0.0

    # Party identity must be explicit because one binary classifier is trained
    # over all party-seat pairs.
    for p in PARTIES:
        f[f"party_{p}"]=1.0 if p==party else 0.0

    # Extra interactions for the 2015-UKIP / 2024-Reform analogue and
    # Labour-vs-LibDem tactical targeting of Conservative seats.
    con_drop=max(0.0,(nat_base["con"]-nat_target["con"])/100.0)
    ref_rise=max(0.0,(nat_target["ref"]-nat_base["ref"])/100.0)
    ld_rise=max(0.0,(nat_target["ld"]-nat_base["ld"])/100.0)
    leave=float(row.get("demo_leave",0.0))
    density=float(row.get("demo_density",0.0))
    old=float(row.get("demo_old",0.0))
    owner=float(row.get("demo_owner",0.0))

    f["ref_leave_affinity"]=1.0 if party=="ref" else 0.0
    f["ref_leave_affinity"]*=leave*ref_rise
    f["ref_lowdensity_affinity"]=(1.0 if party=="ref" else 0.0)*(-density)*ref_rise
    f["ref_old_affinity"]=(1.0 if party=="ref" else 0.0)*old*ref_rise
    f["ref_owner_affinity"]=(1.0 if party=="ref" else 0.0)*owner*ref_rise
    f["ref_concollapse_affinity"]=(1.0 if party=="ref" else 0.0)*local["con"]*con_drop

    f["ld_concollapse_targeting"]=(1.0 if party=="ld" else 0.0)*local["ld"]*con_drop
    f["ld_runnerup_x_condrop"]=(1.0 if party=="ld" and second=="ld" else 0.0)*con_drop
    f["lab_runnerup_x_condrop"]=(1.0 if party=="lab" and second=="lab" else 0.0)*con_drop
    f["ld_rise_x_local"]=(1.0 if party=="ld" else 0.0)*local["ld"]*ld_rise

    return f


def contest_matrix(
    election:dict[str,Any],
    target_nat:dict[str,float],
    feature_names:list[str]|None=None
)->tuple[pd.DataFrame,list[tuple[Any,str]]]:
    df=election["frame"]
    nat_base=nat_shares(election)
    demo_cols=[c for c in df.columns if str(c).startswith("demo_")]
    swing=base_prediction(election,target_nat)
    records=[]
    keys=[]

    for idx,row in df.iterrows():
        parties=competitive_parties(row)
        for p in parties:
            records.append(
                contest_feature_record(row,nat_base,target_nat,swing.loc[idx],p,demo_cols)
            )
            keys.append((idx,p))

    x=pd.DataFrame(records)
    if feature_names is not None:
        for c in feature_names:
            if c not in x:x[c]=0.0
        x=x[feature_names]
    return x.replace([np.inf,-np.inf],0).fillna(0.0),keys


def contest_training_data(transitions:list[dict[str,Any]],feature_names:list[str]|None=None):
    xs=[];ys=[]
    all_keys=[]
    for tr in transitions:
        x,keys=contest_matrix(tr["base"],tr["target"],feature_names)
        actual=tr["actual"]["frame"]
        y=np.asarray([1 if str(actual.loc[idx,"actual_winner"])==p else 0 for idx,p in keys],dtype=int)
        xs.append(x);ys.append(y);all_keys.extend(keys)

    if feature_names is None:
        all_cols=sorted(set().union(*(set(x.columns) for x in xs)))
    else:
        all_cols=list(feature_names)

    xcat=pd.concat(
        [x.reindex(columns=all_cols,fill_value=0.0) for x in xs],
        axis=0,ignore_index=True
    )
    ycat=np.concatenate(ys) if ys else np.array([],dtype=int)
    return xcat,ycat,all_cols,all_keys


def make_contest_estimator(spec:dict[str,Any]):
    if spec["kind"]=="logit":
        return Pipeline([
            ("scale",StandardScaler()),
            ("logit",LogisticRegression(
                C=float(spec["C"]),
                class_weight="balanced",
                max_iter=1600,
                solver="lbfgs",
                random_state=202697,
            ))
        ])
    if spec["kind"]=="hgb":
        return HistGradientBoostingClassifier(
            learning_rate=.05,
            max_iter=130,
            max_leaf_nodes=15,
            max_depth=int(spec["depth"]),
            min_samples_leaf=int(spec["leaf"]),
            l2_regularization=float(spec["l2"]),
            random_state=202697,
        )
    raise ValueError(spec["kind"])


def train_contest_model(transitions:list[dict[str,Any]],spec:dict[str,Any]):
    if spec["kind"]=="none":
        return None,[]
    x,y,names,_=contest_training_data(transitions)
    if len(np.unique(y))<2:
        raise RuntimeError("Contestability classifier training has only one class")
    model=make_contest_estimator(spec)
    if spec["kind"]=="hgb":
        # Roughly equal total mass for winners and non-winners.
        pos=max(1,int(y.sum()));neg=max(1,int((1-y).sum()))
        pw=neg/pos
        sw=np.where(y==1,pw,1.0)
        model.fit(x,y,sample_weight=sw)
    else:
        model.fit(x,y)
    return model,names


def predict_contest_scores(
    base:dict[str,Any],
    target:dict[str,float],
    model,
    feature_names:list[str]
)->pd.DataFrame:
    df=base["frame"]
    scores=pd.DataFrame(0.0,index=df.index,columns=PARTIES)
    if model is None:
        return scores
    x,keys=contest_matrix(base,target,feature_names)
    probs=model.predict_proba(x)[:,1]
    for (idx,p),prob in zip(keys,probs):
        scores.at[idx,p]=clamp(float(prob),1e-6,1-1e-6)
    return scores


def calibrate_with_contestability(
    rows:pd.DataFrame,
    contest_scores:pd.DataFrame,
    base:dict[str,Any],
    target:dict[str,float],
    strength:float
)->pd.DataFrame:
    """Redistribute local shares using FPTP win-priors, then rake back nationally.

    Strength is chosen on the 2017 internal test only. The operation preserves
    national party targets after raking; it changes only territorial efficiency.
    """
    if strength<=0:
        return rows.copy()

    out=rows.copy().astype(float)
    for idx,row in base["frame"].iterrows():
        parties=competitive_parties(row)
        share_sum=sum(max(.01,float(out.at[idx,p])) for p in parties) or 1.0
        prob_sum=sum(max(1e-6,float(contest_scores.at[idx,p])) for p in parties) or 1.0

        factors={}
        for p in parties:
            share_prob=max(.002,float(out.at[idx,p])/share_sum)
            contest_prob=max(.002,float(contest_scores.at[idx,p])/prob_sum)
            ratio=contest_prob/share_prob
            factors[p]=clamp(ratio**strength,.60,1.65)

        vals={}
        country=str(row["country"])
        for p in PARTIES:
            if not allowed(p,country):
                vals[p]=0.0
            elif p in factors:
                vals[p]=max(.0001,float(out.at[idx,p])*factors[p])
            else:
                vals[p]=max(.0001,float(out.at[idx,p]))
        s=sum(vals.values()) or 1.0
        for p in PARTIES:
            out.at[idx,p]=vals[p]/s*100.0

    return rake(out,base,target)


def tune_contest_spec(
    tr10_15:dict[str,Any],
    tr15_17:dict[str,Any],
    share_spec:dict[str,Any]
):
    # The share model and the contestability layer are both selected without
    # seeing the 2019 validation or the 2024 holdout.
    share_models,share_names=train_models([tr10_15],share_spec)
    raw_rows=predict_transition(
        tr15_17["base"],tr15_17["target"],share_models,share_names,share_spec
    )

    candidates=[]
    for spec in CONTEST_SPECS:
        if spec["kind"]=="none":
            rows=raw_rows
        else:
            model,names=train_contest_model([tr10_15],spec)
            scores=predict_contest_scores(tr15_17["base"],tr15_17["target"],model,names)
            rows=calibrate_with_contestability(
                raw_rows,scores,tr15_17["base"],tr15_17["target"],float(spec["strength"])
            )
        metrics=evaluate_rows(rows,tr15_17["actual"],tr15_17["base"])
        candidates.append({"spec":spec,"metrics":metrics})

    candidates.sort(key=lambda x:score_tuple(x["metrics"]),reverse=True)
    return candidates[0]["spec"],candidates


def apply_contest_layer(
    raw_rows:pd.DataFrame,
    base:dict[str,Any],
    target:dict[str,float],
    transitions:list[dict[str,Any]],
    contest_spec:dict[str,Any]
):
    if contest_spec["kind"]=="none":
        return raw_rows.copy(),None
    model,names=train_contest_model(transitions,contest_spec)
    scores=predict_contest_scores(base,target,model,names)
    rows=calibrate_with_contestability(
        raw_rows,scores,base,target,float(contest_spec["strength"])
    )
    return rows,scores


def _eligible_party_shares(election:dict[str,Any],party:str)->np.ndarray:
    vals=[
        float(row[party])
        for _,row in election["frame"].iterrows()
        if allowed(party,str(row["country"]))
    ]
    return np.asarray(vals,dtype=float)



def national_scenario_metrics(
    base:dict[str,Any],
    target:dict[str,float]
)->dict[str,Any]:
    base_nat=nat_shares(base)
    deltas={p:float(target.get(p,0.0))-float(base_nat.get(p,0.0)) for p in PARTIES}
    turnover=.5*sum(abs(v) for v in deltas.values())

    if SCENARIO_TURNOVER_HIGH<=SCENARIO_TURNOVER_LOW:
        system_activation=1.0
    else:
        system_activation=clamp(
            (turnover-SCENARIO_TURNOVER_LOW)/
            (SCENARIO_TURNOVER_HIGH-SCENARIO_TURNOVER_LOW),
            0.0,1.0
        )

    con_drop=max(0.0,-deltas["con"])
    ref_rise=max(0.0,deltas["ref"])
    return {
        "base_national":base_nat,
        "target_national":{p:float(target.get(p,0.0)) for p in PARTIES},
        "deltas":deltas,
        "turnover":float(turnover),
        "system_activation":float(system_activation),
        "con_drop":float(con_drop),
        "ref_rise":float(ref_rise),
    }


def party_scenario_activation(
    base:dict[str,Any],
    target:dict[str,float],
    party:str,
    metrics:dict[str,Any]|None=None
)->float:
    """How much of the structural calibration should be active in this scenario.

    No election outcome is used: only baseline national shares and the target
    national vote vector.  Low-turnover elections stay near the raw share model;
    major realignments allow the territorial/FPTP corrections to engage.
    """
    m=metrics or national_scenario_metrics(base,target)
    system=float(m["system_activation"])
    own=clamp(
        abs(float(m["deltas"].get(party,0.0)))/SCENARIO_OWN_CHANGE_FULL,
        0.0,1.0
    )
    activation=0.70*system+0.30*own

    con_collapse=clamp(float(m["con_drop"])/SCENARIO_CON_DROP_FULL,0.0,1.0)
    ref_surge=clamp(float(m["ref_rise"])/SCENARIO_REF_RISE_FULL,0.0,1.0)

    if party=="ref":
        # Reform/UKIP geography matters most when it is surging and/or taking
        # votes in a Conservative-collapse environment.
        activation=max(activation,ref_surge,0.90*con_collapse)
    elif party in {"lab","ld"}:
        # Tactical/efficient anti-Conservative geography should not be applied
        # with the same force when Conservative support is stable.
        activation=max(activation,0.85*con_collapse)
    elif party=="con":
        activation=max(activation,con_collapse)

    return clamp(float(activation),0.0,1.0)


def historical_party_dispersion(
    history:list[dict[str,Any]],
    target:dict[str,float]
)->dict[str,dict[str,Any]]:
    """Estimate party-specific geographic dispersion using PRIOR elections only."""
    profile={}
    for p in PARTIES:
        obs=[]
        for order,election in enumerate(history):
            vals=_eligible_party_shares(election,p)
            if len(vals)<20:
                continue
            mean=float(np.mean(vals))
            sd=float(np.std(vals))
            nat=float(nat_shares(election).get(p,0.0))
            if mean<=0.02:
                continue
            rel=sd/max(0.35,mean)
            dist=abs(math.log((nat+0.50)/(float(target.get(p,0.0))+0.50)))
            similarity=math.exp(-dist/DISPERSION_SIMILARITY_TAU)
            recency=1.0+0.12*order
            w=similarity*recency
            obs.append((rel,w,nat,election["year"]))
        if not obs:
            profile[p]={"relative_sd":1.0,"observations":0,"history":[]}
            continue
        den=sum(x[1] for x in obs) or 1.0
        rel=sum(x[0]*x[1] for x in obs)/den
        profile[p]={
            "relative_sd":float(rel),
            "observations":len(obs),
            "history":[
                {"year":year,"national_share":nat,"weight":w,"relative_sd":r}
                for r,w,nat,year in obs
            ],
        }
    return profile


def calibrate_party_dispersion(
    rows:pd.DataFrame,
    base:dict[str,Any],
    target:dict[str,float],
    history:list[dict[str,Any]]
)->tuple[pd.DataFrame,dict[str,Any]]:
    """Party-specific dispersion, attenuated by the national swing scenario."""
    out=rows.copy().astype(float)
    profile=historical_party_dispersion(history,target)
    scenario=national_scenario_metrics(base,target)
    meta={"_scenario":scenario}

    for p in PARTIES:
        indexes=[
            idx for idx,row in base["frame"].iterrows()
            if allowed(p,str(row["country"]))
        ]
        if len(indexes)<20:
            meta[p]={"beta":1.0,"activation":0.0,"reason":"too_few_seats"}
            continue

        vals=np.asarray([float(out.at[idx,p]) for idx in indexes],dtype=float)
        mean=float(np.mean(vals))
        sd=float(np.std(vals))
        desired_rel=float(profile.get(p,{}).get("relative_sd",1.0))
        desired_sd=desired_rel*max(0.35,mean)
        raw_beta=desired_sd/max(0.05,sd)
        lo,hi=DISPERSION_BOUNDS[p]
        structural_beta=clamp(raw_beta,lo,hi)

        if float(target.get(p,0.0))<0.45:
            structural_beta=1.0

        activation=party_scenario_activation(base,target,p,scenario)
        # Interpolate toward "do nothing" in stable elections.
        beta=1.0+activation*(structural_beta-1.0)

        adjusted=np.maximum(mean+beta*(vals-mean),0.0001)
        for idx,v in zip(indexes,adjusted):
            out.at[idx,p]=float(v)

        meta[p]={
            "beta":float(beta),
            "structural_beta":float(structural_beta),
            "raw_beta":float(raw_beta),
            "activation":float(activation),
            "current_mean":mean,
            "current_sd":sd,
            "target_relative_sd":desired_rel,
            "desired_sd":desired_sd,
            "bounds":[lo,hi],
            "history":profile.get(p,{}).get("history",[]),
        }

    for idx,row in base["frame"].iterrows():
        country=str(row["country"])
        vals={
            p:(max(.0001,float(out.at[idx,p])) if allowed(p,country) else 0.0)
            for p in PARTIES
        }
        den=sum(vals.values()) or 1.0
        for p in PARTIES:
            out.at[idx,p]=vals[p]/den*100.0

    return rake(out,base,target),meta


def calibrate_with_party_strengths(
    rows:pd.DataFrame,
    contest_scores:pd.DataFrame,
    base:dict[str,Any],
    target:dict[str,float],
    strengths:dict[str,float]
)->pd.DataFrame:
    out=rows.copy().astype(float)
    scenario=national_scenario_metrics(base,target)
    effective_strengths={
        p:float(strengths.get(p,0.0))*party_scenario_activation(
            base,target,p,scenario
        )
        for p in PARTIES
    }
    for idx,row in base["frame"].iterrows():
        parties=competitive_parties(row)
        share_sum=sum(max(.01,float(out.at[idx,p])) for p in parties) or 1.0
        prob_sum=sum(max(1e-6,float(contest_scores.at[idx,p])) for p in parties) or 1.0

        factors={}
        for p in parties:
            strength=float(effective_strengths.get(p,0.0))
            if strength<=0:
                factors[p]=1.0
                continue
            share_prob=max(.002,float(out.at[idx,p])/share_sum)
            contest_prob=max(.002,float(contest_scores.at[idx,p])/prob_sum)
            factors[p]=clamp((contest_prob/share_prob)**strength,.55,1.80)

        country=str(row["country"])
        vals={}
        for p in PARTIES:
            vals[p]=(
                max(.0001,float(out.at[idx,p])*factors.get(p,1.0))
                if allowed(p,country) else 0.0
            )
        den=sum(vals.values()) or 1.0
        for p in PARTIES:
            out.at[idx,p]=vals[p]/den*100.0

    return rake(out,base,target)


def party_winner_loss(
    rows:pd.DataFrame,
    actual:dict[str,Any],
    base:dict[str,Any],
    party:str
)->tuple[int,int,int]:
    pred=0;real=0;mistakes=0
    for idx,row in actual["frame"].iterrows():
        pw=predicted_winner(rows.loc[idx],base["frame"].loc[idx])
        rw=str(row["actual_winner"])
        pred+=int(pw==party);real+=int(rw==party)
        mistakes+=int((pw==party)!=(rw==party))
    return mistakes,abs(pred-real),pred


def tune_party_strengths(
    raw_rows:pd.DataFrame,
    base:dict[str,Any],
    actual:dict[str,Any],
    target:dict[str,float],
    training_transitions:list[dict[str,Any]]
)->tuple[dict[str,float],dict[str,Any],pd.DataFrame]:
    """Select party-specific FPTP strengths using the 2017 development election."""
    model,names=train_contest_model(training_transitions,PARTY_CONTEST_BASE_SPEC)
    scores=predict_contest_scores(base,target,model,names)

    chosen={};audit={}
    zero={p:0.0 for p in PARTIES}

    for p in PARTIES:
        candidates=[]
        for strength in PARTY_STRENGTH_GRID[p]:
            trial=dict(zero);trial[p]=float(strength)
            candidate=calibrate_with_party_strengths(
                raw_rows,scores,base,target,trial
            )
            mistakes,seat_err,pred=party_winner_loss(candidate,actual,base,p)
            candidates.append({
                "strength":float(strength),
                "mistakes":int(mistakes),
                "seat_error":int(seat_err),
                "predicted_seats":int(pred),
            })
        candidates.sort(key=lambda x:(x["mistakes"],x["seat_error"],x["strength"]))
        chosen[p]=float(candidates[0]["strength"])
        audit[p]=candidates

    global_candidates=[]
    for scale in (0.0,0.50,0.75,1.00):
        strengths={p:chosen[p]*scale for p in PARTIES}
        candidate=calibrate_with_party_strengths(
            raw_rows,scores,base,target,strengths
        )
        metrics=evaluate_rows(candidate,actual,base)
        global_candidates.append({
            "scale":scale,"metrics":metrics,"strengths":strengths
        })

    global_candidates.sort(key=lambda x:score_tuple(x["metrics"]),reverse=True)
    selected=global_candidates[0]
    return selected["strengths"],{
        "per_party_candidates":audit,
        "unscaled_strengths":chosen,
        "global_candidates":[
            {
                "scale":x["scale"],
                "winner_accuracy":x["metrics"]["winner_accuracy"],
                "correct_winners":x["metrics"]["correct_winners"],
                "seat_abs_error_sum":x["metrics"]["seat_abs_error_sum"],
                "strengths":x["strengths"],
            } for x in global_candidates
        ],
        "selected_scale":selected["scale"],
        "development_scenario":national_scenario_metrics(base,target),
        "effective_selected_strengths":{
            p:selected["strengths"].get(p,0.0)*party_scenario_activation(
                base,target,p,national_scenario_metrics(base,target)
            )
            for p in PARTIES
        },
    },scores


def apply_party_calibration(
    raw_rows:pd.DataFrame,
    base:dict[str,Any],
    target:dict[str,float],
    history:list[dict[str,Any]],
    training_transitions:list[dict[str,Any]],
    strengths:dict[str,float]
)->tuple[pd.DataFrame,dict[str,Any],pd.DataFrame|None]:
    dispersed,dispersion_meta=calibrate_party_dispersion(
        raw_rows,base,target,history
    )
    if not any(float(v)>0 for v in strengths.values()):
        return dispersed,dispersion_meta,None
    model,names=train_contest_model(training_transitions,PARTY_CONTEST_BASE_SPEC)
    scores=predict_contest_scores(base,target,model,names)
    calibrated=calibrate_with_party_strengths(
        dispersed,scores,base,target,strengths
    )
    return calibrated,dispersion_meta,scores


def incumbent_decline_profile(
    base:dict[str,Any],
    target:dict[str,float]
)->dict[str,dict[str,float]]:
    base_nat=nat_shares(base)
    out={}
    for p in PARTIES:
        b=float(base_nat.get(p,0.0))
        t=float(target.get(p,0.0))
        drop=max(0.0,b-t)
        relative=drop/max(0.50,b)
        activation=clamp(
            (relative-INCUMBENT_DECLINE_REL_LOW)/
            max(1e-9,INCUMBENT_DECLINE_REL_FULL-INCUMBENT_DECLINE_REL_LOW),
            0.0,1.0
        )
        out[p]={
            "base_share":b,
            "target_share":t,
            "absolute_drop":drop,
            "relative_drop":relative,
            "activation":activation,
        }
    return out


def route_incumbent_collapse(
    rows:pd.DataFrame,
    base:dict[str,Any],
    target:dict[str,float],
    route_strength:float,
    unwind_strength:float
)->tuple[pd.DataFrame,dict[str,Any]]:
    """Concentrate opposition around the established runner-up in collapse seats.

    Uses only baseline winner/runner-up plus national base/target shares.
    No future constituency winner or future local share is consulted.

    1) Challenger routing:
       part of the vote held by third/fourth challengers is shifted to the
       baseline runner-up.
    2) Incumbent unwind:
       part of the incumbent's residual predicted lead over the runner-up is
       shifted to that runner-up.

    Final raking restores national party vote targets, so the layer primarily
    alters territorial efficiency rather than aggregate support.
    """
    out=rows.copy().astype(float)
    decline=incumbent_decline_profile(base,target)
    audit={
        "route_strength":float(route_strength),
        "unwind_strength":float(unwind_strength),
        "decline_profile":decline,
        "affected_seats":0,
        "by_incumbent":defaultdict(lambda:{
            "seats":0,"routed_vote":0.0,"unwound_vote":0.0,
            "runnerups":Counter()
        }),
    }

    for idx,row in base["frame"].iterrows():
        incumbent=str(row.get("actual_winner") or "")
        runner=str(row.get("actual_second") or "")
        if incumbent not in PARTIES or runner not in PARTIES:
            continue
        if incumbent==runner:
            continue

        activation=float(decline.get(incumbent,{}).get("activation",0.0))
        if activation<=0:
            continue

        candidates=competitive_parties(row)
        if incumbent not in candidates or runner not in candidates:
            continue

        effective_route=float(route_strength)*activation
        effective_unwind=float(unwind_strength)*activation
        if effective_route<=0 and effective_unwind<=0:
            continue

        audit["affected_seats"]+=1
        a=audit["by_incumbent"][incumbent]
        a["seats"]+=1
        a["runnerups"][runner]+=1

        # A. consolidate weaker challengers into the established runner-up.
        donor_parties=[
            p for p in candidates
            if p not in {incumbent,runner}
        ]
        donor_pool=sum(max(0.0,float(out.at[idx,p])) for p in donor_parties)
        routed=effective_route*donor_pool
        if routed>0 and donor_pool>0:
            for p in donor_parties:
                share=max(0.0,float(out.at[idx,p]))
                out.at[idx,p]=max(0.0001,share-routed*(share/donor_pool))
            out.at[idx,runner]=float(out.at[idx,runner])+routed
            a["routed_vote"]+=float(routed)

        # B. unwind part of a residual local incumbent advantage.
        inc=float(out.at[idx,incumbent])
        run=float(out.at[idx,runner])
        gap=max(0.0,inc-run)
        # Moving half the gap would make the seat tied; strength=1 would erase
        # the full margin. Our development grid deliberately stops at 0.60.
        unwind=effective_unwind*gap*0.50
        if unwind>0:
            unwind=min(unwind,max(0.0,inc-0.0001))
            out.at[idx,incumbent]=inc-unwind
            out.at[idx,runner]=run+unwind
            a["unwound_vote"]+=float(unwind)

        # Row normalization before global raking.
        country=str(row["country"])
        vals={
            p:(max(.0001,float(out.at[idx,p])) if allowed(p,country) else 0.0)
            for p in PARTIES
        }
        den=sum(vals.values()) or 1.0
        for p in PARTIES:
            out.at[idx,p]=vals[p]/den*100.0

    # JSON-safe audit.
    audit["by_incumbent"]={
        p:{
            "seats":v["seats"],
            "routed_vote":v["routed_vote"],
            "unwound_vote":v["unwound_vote"],
            "runnerups":dict(v["runnerups"]),
        }
        for p,v in audit["by_incumbent"].items()
    }
    return rake(out,base,target),audit


def tune_incumbent_routing(
    rows:pd.DataFrame,
    base:dict[str,Any],
    actual:dict[str,Any],
    target:dict[str,float]
)->tuple[dict[str,float],dict[str,Any],pd.DataFrame]:
    """Select routing/unwind strengths on the 2017 development election only."""
    candidates=[]
    for route_strength in ROUTING_STRENGTH_GRID:
        for unwind_strength in UNWIND_STRENGTH_GRID:
            candidate,audit=route_incumbent_collapse(
                rows,base,target,route_strength,unwind_strength
            )
            metrics=evaluate_rows(candidate,actual,base)

            # Extra Scotland diagnostic: 2015->2017 is the historical incumbent-
            # collapse training analogue used by this layer.
            sc=metrics.get("regional_accuracy",{}).get("scotland",{})
            candidates.append({
                "route_strength":float(route_strength),
                "unwind_strength":float(unwind_strength),
                "metrics":metrics,
                "scotland_accuracy":sc.get("accuracy"),
                "audit":audit,
            })

    # Overall constituency accuracy remains the primary objective. Seat error
    # and Scotland accuracy only break ties.
    candidates.sort(
        key=lambda x:(
            x["metrics"]["correct_winners"],
            -x["metrics"]["seat_abs_error_sum"],
            x["scotland_accuracy"] if x["scotland_accuracy"] is not None else -1,
            -x["route_strength"],
            -x["unwind_strength"],
        ),
        reverse=True
    )
    best=candidates[0]
    selected={
        "route_strength":best["route_strength"],
        "unwind_strength":best["unwind_strength"],
    }
    summary=[
        {
            "route_strength":x["route_strength"],
            "unwind_strength":x["unwind_strength"],
            "winner_accuracy":x["metrics"]["winner_accuracy"],
            "correct_winners":x["metrics"]["correct_winners"],
            "seat_abs_error_sum":x["metrics"]["seat_abs_error_sum"],
            "scotland_accuracy":x["scotland_accuracy"],
            "predicted_seats":x["metrics"]["predicted_seats"],
        }
        for x in candidates
    ]
    final_rows,final_audit=route_incumbent_collapse(
        rows,base,target,selected["route_strength"],selected["unwind_strength"]
    )
    return selected,{
        "selected":selected,
        "candidates":summary,
        "selected_audit":final_audit,
        "selection_election":"2015_to_2017",
    },final_rows


def country_accuracy(
    rows:pd.DataFrame,
    actual:dict[str,Any],
    base:dict[str,Any],
    country:str
)->dict[str,Any]:
    total=0;correct=0;pred=Counter();real=Counter()
    for idx,row in actual["frame"].iterrows():
        if str(row["country"])!=country:
            continue
        total+=1
        pw=predicted_winner(rows.loc[idx],base["frame"].loc[idx])
        rw=str(row["actual_winner"])
        pred[pw]+=1;real[rw]+=1
        correct+=int(pw==rw)
    return {
        "country":country,
        "n":total,
        "correct":correct,
        "accuracy":correct/total if total else None,
        "predicted_seats":dict(pred),
        "actual_seats":dict(real),
    }


def _finite(value:Any)->float|None:
    try:
        number=float(value)
    except (TypeError,ValueError):
        return None
    return number if math.isfinite(number) else None


def _feature_summary(records:list[dict[str,Any]],features:list[str])->dict[str,Any]:
    out={}
    for feature in features:
        values=[
            float(record["features"][feature])
            for record in records
            if _finite(record.get("features",{}).get(feature)) is not None
        ]
        if not values:
            continue
        arr=np.asarray(values,dtype=float)
        out[feature]={
            "n":int(len(arr)),
            "mean":float(arr.mean()),
            "median":float(np.median(arr)),
            "q25":float(np.quantile(arr,.25)),
            "q75":float(np.quantile(arr,.75)),
        }
    return out


def _feature_separation(
    left:list[dict[str,Any]],
    right:list[dict[str,Any]],
    features:list[str],
    left_label:str,
    right_label:str,
)->dict[str,Any]:
    rows=[]
    for feature in features:
        a=np.asarray([
            float(record["features"][feature])
            for record in left
            if _finite(record.get("features",{}).get(feature)) is not None
        ],dtype=float)
        b=np.asarray([
            float(record["features"][feature])
            for record in right
            if _finite(record.get("features",{}).get(feature)) is not None
        ],dtype=float)
        if not len(a) or not len(b):
            continue
        va=float(a.var(ddof=1)) if len(a)>1 else 0.0
        vb=float(b.var(ddof=1)) if len(b)>1 else 0.0
        pooled=math.sqrt(max(0.0,(va+vb)/2.0))
        difference=float(a.mean()-b.mean())
        smd=(difference/pooled) if pooled>1e-12 else None
        rows.append({
            "feature":feature,
            "left_mean":float(a.mean()),
            "right_mean":float(b.mean()),
            "difference":difference,
            "standardized_mean_difference":smd,
            "abs_standardized_mean_difference":abs(smd) if smd is not None else None,
            "left_n":int(len(a)),
            "right_n":int(len(b)),
        })
    rows.sort(
        key=lambda row:(
            row["abs_standardized_mean_difference"]
            if row["abs_standardized_mean_difference"] is not None else -1.0,
            abs(row["difference"]),
        ),
        reverse=True,
    )
    return {
        "left":left_label,
        "right":right_label,
        "warning":"Exploratory 2024 comparison only; it is not a fitted rule and does not update model parameters.",
        "features":rows,
    }


def build_reform_diagnostics(
    rows:pd.DataFrame,
    actual:dict[str,Any],
    base:dict[str,Any],
    contest_scores:pd.DataFrame|None,
)->dict[str,Any]:
    """Describe Reform winner errors without fitting anything to 2024."""
    actual_df=actual["frame"]
    base_df=base["frame"]
    if not rows.index.equals(actual_df.index) or not rows.index.equals(base_df.index):
        raise RuntimeError("Reform diagnostic indexes do not align")

    demo_columns=list(actual.get("demo_columns",[]))
    # Keep ex-ante predictors separate from realised 2024 outcomes.  The
    # predictor set may be inspected when formulating a future hypothesis;
    # observed Reform share and forecast error are outcome diagnostics only
    # and must never rank candidate predictors or select a correction.
    predictor_feature_names=[
        "baseline_ref_share","baseline_con_share","baseline_lab_share",
        "baseline_ld_share","baseline_green_share","baseline_turnout",
        "baseline_winner_margin","predicted_ref_share",
        "predicted_best_non_ref_share","predicted_ref_margin",
        "predicted_ref_rank","contestability_ref","ref_primary_stood",
        "ref_latent_share","ref_calibrated_share","ref_geo_share","ref_latent_activation",
        *[column.replace("demo_","") for column in demo_columns],
    ]
    outcome_feature_names=["actual_ref_share","ref_share_error"]
    all_feature_names=predictor_feature_names+outcome_feature_names
    base_nat=nat_shares(base)
    actual_nat=nat_shares(actual)
    records=[]
    binary=Counter()
    cohorts=Counter()
    false_positive_actual=Counter()
    false_positive_regions=Counter()

    for idx,actual_row in actual_df.iterrows():
        base_row=base_df.loc[idx]
        predicted_row=rows.loc[idx]
        candidates=competitive_parties(base_row)
        predicted_order=sorted(
            candidates,key=lambda party:float(predicted_row[party]),reverse=True
        )
        predicted=predicted_order[0]
        observed=str(actual_row["actual_winner"])
        predicted_ref=(predicted=="ref")
        observed_ref=(observed=="ref")
        if predicted_ref and observed_ref:
            binary_label="true_positive";cohort="true_positive"
        elif predicted_ref and not observed_ref:
            binary_label="false_positive";cohort="false_positive"
        elif not predicted_ref and observed_ref:
            binary_label="false_negative";cohort="false_negative"
        else:
            binary_label="true_negative"
            cohort="correct_non_reform" if predicted==observed else "other_winner_error"
        binary[binary_label]+=1
        cohorts[cohort]+=1
        if cohort=="false_positive":
            false_positive_actual[observed]+=1
            false_positive_regions[str(actual_row["region"])]+=1

        non_ref=[party for party in candidates if party!="ref"]
        best_non_ref=max(non_ref,key=lambda party:float(predicted_row[party]))
        base_winner=str(base_row.get("actual_winner") or "")
        base_second=str(base_row.get("actual_second") or "")
        if base_second not in candidates or base_second==base_winner:
            base_second=max(
                (party for party in candidates if party!=base_winner),
                key=lambda party:float(base_row[party]),
            )
        contestability=None
        if contest_scores is not None and "ref" in contest_scores.columns:
            contestability=_finite(contest_scores.at[idx,"ref"])

        features={
            "baseline_ref_share":float(base_row["ref"]),
            "baseline_con_share":float(base_row["con"]),
            "baseline_lab_share":float(base_row["lab"]),
            "baseline_ld_share":float(base_row["ld"]),
            "baseline_green_share":float(base_row["green"]),
            "baseline_turnout":float(base_row.get("turnout",0.0)),
            "baseline_winner_margin":float(base_row[base_winner])-float(base_row[base_second]),
            "predicted_ref_share":float(predicted_row["ref"]),
            "predicted_best_non_ref_share":float(predicted_row[best_non_ref]),
            "predicted_ref_margin":float(predicted_row["ref"])-float(predicted_row[best_non_ref]),
            "predicted_ref_rank":float(predicted_order.index("ref")+1),
            "ref_primary_stood":1.0 if bool(base_row.get("ref_primary_stood",False)) else 0.0,
            "ref_latent_share":float(base_row.get("ref_latent_share",base_row.get("ref",0.0))),
            "ref_calibrated_share":float(base_row.get("ref_calibrated_share",base_row.get("ref",0.0))),
            "ref_geo_share":float(base_row.get("ref_geo_share",base_row.get("ref",0.0))),
            "ref_latent_activation":ref_latent_activation(base_row,base_nat,actual_nat),
            "actual_ref_share":float(actual_row["ref"]),
            "ref_share_error":float(predicted_row["ref"])-float(actual_row["ref"]),
            "contestability_ref":contestability,
        }
        for column in demo_columns:
            features[column.replace("demo_","")]=_finite(actual_row.get(column))

        records.append({
            "id":str(actual_row["id"]),
            "name":str(actual_row["name"]),
            "country":str(actual_row["country"]),
            "region":str(actual_row["region"]),
            "cohort":cohort,
            "binary_ref_classification":binary_label,
            "predicted_winner":predicted,
            "actual_winner":observed,
            "baseline_winner":base_winner,
            "baseline_second":base_second,
            "predicted_best_non_ref":best_non_ref,
            "predicted_shares":{
                party:round(float(predicted_row[party]),6) for party in PARTIES
            },
            "actual_shares":{
                party:round(float(actual_row[party]),6) for party in PARTIES
            },
            "features":features,
        })

    tp=int(binary["true_positive"]);fp=int(binary["false_positive"])
    fn=int(binary["false_negative"]);tn=int(binary["true_negative"])
    groups={
        label:[record for record in records if record["cohort"]==label]
        for label in (
            "true_positive","false_positive","false_negative",
            "correct_non_reform","other_winner_error"
        )
    }
    # Only ex-ante/predicted features enter the ranked comparisons.  Realised
    # 2024 Reform share and prediction error remain visible below as outcomes,
    # but cannot appear in the predictor ranking.
    comparisons=[
        _feature_separation(
            groups["false_positive"],groups["true_positive"],predictor_feature_names,
            "false_positive","true_positive"
        ),
        _feature_separation(
            groups["false_positive"],groups["correct_non_reform"],predictor_feature_names,
            "false_positive","correct_non_reform"
        ),
        _feature_separation(
            groups["false_positive"],groups["false_negative"],predictor_feature_names,
            "false_positive","false_negative"
        ),
    ]
    outcome_comparisons=[
        _feature_separation(
            groups["false_positive"],groups["true_positive"],outcome_feature_names,
            "false_positive","true_positive"
        ),
        _feature_separation(
            groups["false_positive"],groups["correct_non_reform"],outcome_feature_names,
            "false_positive","correct_non_reform"
        ),
        _feature_separation(
            groups["false_positive"],groups["false_negative"],outcome_feature_names,
            "false_positive","false_negative"
        ),
    ]
    predicted_ref=tp+fp
    actual_ref=tp+fn
    if tp+fp+fn+tn!=632:
        raise RuntimeError("Reform diagnostic does not cover all 632 GB seats")

    return {
        "version":"uk-v0917-error-audit",
        "status":"ok",
        "generated_at":utcnow().isoformat(),
        "diagnostic_only":True,
        "used_for_parameter_selection":False,
        "changes_production_model":False,
        "source_model":"uk-v0917-error-audit",
        "benchmark":"2019_notional_to_2024",
        "benchmark_role":"development_diagnostic_not_pristine_holdout",
        "interpretation_warning":(
            "The 2024 labels are inspected only to describe failure modes. "
            "No threshold, coefficient, feature set or approval decision is selected from this report."
        ),
        "binary_confusion":{
            "true_positive":tp,"false_positive":fp,
            "false_negative":fn,"true_negative":tn,
            "total":632,
        },
        "counts":{
            "predicted_reform_wins":predicted_ref,
            "actual_reform_wins":actual_ref,
            "precision":tp/predicted_ref if predicted_ref else None,
            "recall":tp/actual_ref if actual_ref else None,
            "cohorts":{label:int(count) for label,count in sorted(cohorts.items())},
            "false_positive_actual_winners":dict(false_positive_actual),
            "false_positive_regions":dict(false_positive_regions),
        },
        "feature_definitions":{
            "demographics":"Within-wave percentile ranks centred on zero.",
            "shares":"Percentage points.",
            "predicted_ref_margin":"Predicted Reform share minus the strongest predicted non-Reform challenger.",
            "ref_share_error":"Predicted Reform share minus observed Reform share.",
            "contestability_ref":"Frozen v0.9.10 contestability score; diagnostic only.",
        },
        "feature_roles":{
            "predictors_ex_ante":predictor_feature_names,
            "outcomes_2024_only":outcome_feature_names,
            "ranking_rule":"feature_comparisons contains predictors_ex_ante only; outcomes_2024_only are excluded from predictor ranking and parameter selection.",
        },
        "cohort_summaries":{
            label:{
                "count":len(group),
                "predictors":_feature_summary(group,predictor_feature_names),
                "outcomes_2024":_feature_summary(group,outcome_feature_names),
                "all_features":_feature_summary(group,all_feature_names),
            }
            for label,group in groups.items()
        },
        "feature_comparisons":comparisons,
        "outcome_diagnostics_2024":outcome_comparisons,
        "reform_cases":[
            record for record in records
            if record["binary_ref_classification"]!="true_negative"
        ],
        "false_positive_seats":groups["false_positive"],
        "parameter_updates":{},
    }

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

def live_projection(
    current:dict[str,Any],
    target:dict[str,float],
    rows:pd.DataFrame,
    contest_scores:pd.DataFrame|None,
    contest_spec:dict[str,Any]
)->dict[str,Any]:
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
            "contestability":{
                p:round(float(contest_scores.at[idx,p]),6)
                for p in competitive_parties(row)
            } if contest_scores is not None else None,
        })
    return {
        "seats":seats,
        "totals":{p:int(totals[p]) for p in PARTIES},
        "other_rule":"Aggregate Other share is not treated as a single candidate; Other can win only if winner/runner-up in the 2024 baseline.",
        "contestability_spec":contest_spec,
    }



def experimental_rake(rows:pd.DataFrame,election:dict[str,Any],target:dict[str,float])->pd.DataFrame:
    """Vectorised raking helper retained for historical shadow experiments."""
    target=normalize_target(target);df=election["frame"]
    arr=rows.loc[:,PARTIES].to_numpy(dtype=float,copy=True)
    w=df["weight"].to_numpy(dtype=float);den=float(w.sum()) or 1.0
    mask=np.zeros_like(arr,dtype=bool)
    countries=df["country"].astype(str).tolist()
    for j,p in enumerate(PARTIES):
        mask[:,j]=np.asarray([allowed(p,c) for c in countries],dtype=bool)
    arr=np.maximum(arr,0.0001);arr[~mask]=0.0
    targ=np.asarray([target[p] for p in PARTIES],dtype=float)
    for _ in range(35):
        cur=np.sum(arr*w[:,None],axis=0)/den
        if float(np.max(np.abs(cur-targ)))<0.01:break
        mult=np.clip(targ/np.maximum(.01,cur),.35,3.0)
        arr*=mult[None,:];arr[~mask]=0.0
        rowsum=arr.sum(axis=1);rowsum=np.where(rowsum>0,rowsum,1.0)
        arr=arr/rowsum[:,None]*100.0;arr[~mask]=0.0
    return pd.DataFrame(arr,index=rows.index,columns=PARTIES)


def _baseline_margin(row:pd.Series)->float:
    winner=str(row.get("actual_winner") or "")
    second=str(row.get("actual_second") or "")
    if winner in PARTIES and second in PARTIES:
        return max(0.0,float(row.get(winner,0.0))-float(row.get(second,0.0)))
    vals=sorted((float(row.get(p,0.0)) for p in competitive_parties(row)),reverse=True)
    return max(0.0,vals[0]-vals[1]) if len(vals)>1 else 0.0


def _margin_band(margin:float)->str:
    if margin<2.0:return "lt2"
    if margin<5.0:return "2to5"
    if margin<10.0:return "5to10"
    if margin<20.0:return "10to20"
    return "ge20"


def _competition_key(row:pd.Series)->str:
    return "|".join((
        str(row.get("region") or "unknown"),
        str(row.get("actual_winner") or "other"),
        str(row.get("actual_second") or "other"),
        _margin_band(_baseline_margin(row)),
    ))


def _ols_slope(x:np.ndarray,y:np.ndarray)->float|None:
    if len(x)<12:return None
    xc=x-float(np.mean(x));yc=y-float(np.mean(y))
    den=float(np.dot(xc,xc))
    if den<1e-8:return None
    return float(np.dot(xc,yc)/den)


def _gradient_observation(transition:dict[str,Any],party:str)->dict[str,Any]|None:
    base=transition["base"];actual=transition["actual"]
    indexes=[
        idx for idx,row in base["frame"].iterrows()
        if allowed(party,str(row["country"]))
    ]
    if len(indexes)<20:return None
    x=np.asarray([float(base["frame"].at[idx,party]) for idx in indexes],dtype=float)
    y=np.asarray([float(actual["frame"].at[idx,party]) for idx in indexes],dtype=float)
    slope=_ols_slope(x,y)
    if slope is None:return None
    bn=float(nat_shares(base).get(party,0.0));tn=float(nat_shares(actual).get(party,0.0))
    return {
        "base_year":str(base.get("year")),"target_year":str(actual.get("year")),
        "slope":float(slope),"base_nat":bn,"target_nat":tn,"n":len(indexes),
        "log_swing":math.log((tn+0.50)/(bn+0.50)),
    }


def historical_gradient_target(
    history:list[dict[str,Any]],target:dict[str,float],base:dict[str,Any],party:str
)->dict[str,Any]:
    observations=[]
    current_log=math.log((float(target.get(party,0.0))+0.50)/(float(nat_shares(base).get(party,0.0))+0.50))
    for order,tr in enumerate(history):
        obs=_gradient_observation(tr,party)
        if obs is None:continue
        distance=abs(float(obs["log_swing"])-current_log)
        similarity=math.exp(-distance/REGRADE_SIMILARITY_TAU)
        recency=1.0+0.18*order
        w=similarity*recency
        obs=dict(obs);obs["weight"]=w;observations.append(obs)
    if not observations:
        return {"desired_slope":None,"observations":[],"current_log_swing":current_log}
    den=sum(float(x["weight"]) for x in observations) or 1.0
    desired=sum(float(x["slope"])*float(x["weight"]) for x in observations)/den
    return {"desired_slope":float(desired),"observations":observations,"current_log_swing":current_log}


def apply_regradient(
    rows:pd.DataFrame,base:dict[str,Any],target:dict[str,float],
    history:list[dict[str,Any]],strength:float
)->tuple[pd.DataFrame,dict[str,Any]]:
    """Adjust only the baseline-aligned slope, then re-rake to national shares.

    This is deliberately different from v0.9.x dispersion calibration: the old
    layer rescales *all* cross-seat variance; this one changes only the component
    correlated with the previous election's local party strength, mirroring the
    attenuation/regradient concern described by public 2024 MRP practitioners.
    """
    strength=float(strength)
    if strength<=1e-12:
        return rows.copy().astype(float),{"strength":0.0,"parties":{},"national_target_preserved":True}
    out=rows.copy().astype(float);meta={"strength":strength,"parties":{},"national_target_preserved":True}
    df=base["frame"]
    for p in REGRADE_PARTIES:
        indexes=[idx for idx,row in df.iterrows() if allowed(p,str(row["country"]))]
        if len(indexes)<20 or float(target.get(p,0.0))<0.45:
            meta["parties"][p]={"applied":False,"reason":"too_few_seats_or_tiny_target"};continue
        x=np.asarray([float(df.at[idx,p]) for idx in indexes],dtype=float)
        y=np.asarray([float(out.at[idx,p]) for idx in indexes],dtype=float)
        current=_ols_slope(x,y)
        hist=historical_gradient_target(history,target,base,p)
        desired=hist.get("desired_slope")
        if current is None or desired is None:
            meta["parties"][p]={"applied":False,"reason":"slope_unavailable","history":hist};continue
        delta=clamp(float(desired)-float(current),-REGRADE_MAX_DELTA_SLOPE,REGRADE_MAX_DELTA_SLOPE)
        centre=float(np.mean(x))
        raw=np.clip(strength*delta*(x-centre),-REGRADE_MAX_SEAT_SHIFT,REGRADE_MAX_SEAT_SHIFT)
        for idx,d in zip(indexes,raw):out.at[idx,p]=max(.0001,float(out.at[idx,p])+float(d))
        meta["parties"][p]={
            "applied":True,"current_slope":float(current),"desired_slope":float(desired),
            "delta_slope":float(delta),"max_abs_pre_rake_shift":float(np.max(np.abs(raw))) if len(raw) else 0.0,
            "history":hist,
        }
    # Per-seat simplex, then preserve exact national target through the existing rake.
    for idx,row in df.iterrows():
        vals={p:(max(.0001,float(out.at[idx,p])) if allowed(p,str(row["country"])) else 0.0) for p in PARTIES}
        den=sum(vals.values()) or 1.0
        for p in PARTIES:out.at[idx,p]=vals[p]/den*100.0
    return experimental_rake(out,base,target),meta


def build_place_residual_profile(
    predicted:pd.DataFrame,actual:dict[str,Any],base:dict[str,Any]
)->dict[str,Any]:
    """Learn *prior-election* residual place/competition effects only.

    The profile is transportable across boundary changes because keys are
    region + prior winner + prior runner-up + prior-margin band, rather than
    constituency identity.  This is a deliberately low-dimensional proxy for
    the spatial/context effects found in the academic literature; it is not an
    ICAR adjacency model and is labelled accordingly in the output.
    """
    if not actual["frame"].index.equals(base["frame"].index):
        raise RuntimeError("place residual profile requires aligned base/actual rows")
    region_vals=defaultdict(list);comp_vals=defaultdict(list);global_vals=defaultdict(list)
    for idx,arow in actual["frame"].iterrows():
        brow=base["frame"].loc[idx];region=str(brow["region"]);ckey=_competition_key(brow)
        for p in PARTIES:
            if not allowed(p,str(arow["country"])):continue
            resid=float(arow[p])-float(predicted.at[idx,p])
            global_vals[p].append(resid);region_vals[(region,p)].append(resid);comp_vals[(ckey,p)].append(resid)
    global_mean={p:(float(np.mean(v)) if v else 0.0) for p,v in global_vals.items()}
    region_effect={};region_counts={}
    for (r,p),vals in region_vals.items():
        n=len(vals);raw=float(np.mean(vals))-global_mean.get(p,0.0);shrink=n/(n+PLACE_REGION_PRIOR_N)
        region_effect[f"{r}|{p}"]=float(raw*shrink);region_counts[f"{r}|{p}"]=n
    comp_effect={};comp_counts={}
    for (ck,p),vals in comp_vals.items():
        n=len(vals);r=ck.split("|",1)[0]
        raw=float(np.mean(vals))-global_mean.get(p,0.0)-region_effect.get(f"{r}|{p}",0.0)
        shrink=n/(n+PLACE_COMP_PRIOR_N)
        comp_effect[f"{ck}|{p}"]=float(raw*shrink);comp_counts[f"{ck}|{p}"]=n
    return {
        "source_prediction_year":str(base.get("year")),"source_actual_year":str(actual.get("year")),
        "global_mean":global_mean,"region_effect":region_effect,"region_counts":region_counts,
        "competition_effect":comp_effect,"competition_counts":comp_counts,
        "competition_key":"region|baseline_winner|baseline_second|baseline_margin_band",
        "uses_target_election_labels_only_after_that_election":True,
    }


def apply_place_residual(
    rows:pd.DataFrame,base:dict[str,Any],target:dict[str,float],profile:dict[str,Any],
    region_strength:float,competition_strength:float
)->tuple[pd.DataFrame,dict[str,Any]]:
    rs=float(region_strength);cs=float(competition_strength)
    if rs<=1e-12 and cs<=1e-12:
        return rows.copy().astype(float),{"region_strength":0.0,"competition_strength":0.0,"national_target_preserved":True,"mean_abs_shift":0.0}
    out=rows.copy().astype(float);shifts=[];df=base["frame"]
    reff=profile.get("region_effect",{});ceff=profile.get("competition_effect",{})
    for idx,brow in df.iterrows():
        r=str(brow["region"]);ck=_competition_key(brow)
        for p in PARTIES:
            if not allowed(p,str(brow["country"])):continue
            d=rs*float(reff.get(f"{r}|{p}",0.0))+cs*float(ceff.get(f"{ck}|{p}",0.0))
            d=clamp(d,-PLACE_MAX_SEAT_SHIFT,PLACE_MAX_SEAT_SHIFT)
            out.at[idx,p]=max(.0001,float(out.at[idx,p])+d);shifts.append(abs(d))
        vals={p:(max(.0001,float(out.at[idx,p])) if allowed(p,str(brow["country"])) else 0.0) for p in PARTIES}
        den=sum(vals.values()) or 1.0
        for p in PARTIES:out.at[idx,p]=vals[p]/den*100.0
    return experimental_rake(out,base,target),{
        "region_strength":rs,"competition_strength":cs,"national_target_preserved":True,
        "mean_abs_shift":float(np.mean(shifts)) if shifts else 0.0,"profile_source":{
            "prediction_year":profile.get("source_prediction_year"),"actual_year":profile.get("source_actual_year")
        }
    }


def build_error_structure(rows:pd.DataFrame,actual:dict[str,Any],base:dict[str,Any])->dict[str,Any]:
    pairs=Counter();regions=defaultdict(lambda:{"n":0,"wrong":0});margin_bins=defaultdict(lambda:{"n":0,"wrong":0});wrong=[]
    for idx,arow in actual["frame"].iterrows():
        brow=base["frame"].loc[idx];pw=predicted_winner(rows.loc[idx],brow);rw=str(arow["actual_winner"])
        ordered=sorted(((p,float(rows.at[idx,p])) for p in competitive_parties(brow)),key=lambda x:x[1],reverse=True)
        pmargin=(ordered[0][1]-ordered[1][1]) if len(ordered)>1 else 100.0
        mb=_margin_band(pmargin);r=str(arow["region"]);regions[r]["n"]+=1;margin_bins[mb]["n"]+=1
        if pw!=rw:
            pairs[(pw,rw)]+=1;regions[r]["wrong"]+=1;margin_bins[mb]["wrong"]+=1
            wrong.append({
                "id":str(arow["id"]),"name":str(arow["name"]),"country":str(arow["country"]),"region":r,
                "predicted_winner":pw,"actual_winner":rw,"predicted_margin":float(pmargin),
                "baseline_winner":str(brow.get("actual_winner") or ""),"baseline_second":str(brow.get("actual_second") or ""),
                "baseline_margin":float(_baseline_margin(brow)),"competition_key":_competition_key(brow),
                "predicted_top3":[{"party":p,"share":v} for p,v in ordered[:3]],
                "actual_shares":{p:float(arow[p]) for p in PARTIES if allowed(p,str(arow["country"]))},
            })
    pair_rows=[{"predicted":a,"actual":b,"count":int(n)} for (a,b),n in pairs.most_common()]
    return {
        "version":"uk-v0917-error-audit","status":"ok","generated_at":utcnow().isoformat(),
        "canonical_candidate":"frozen_v0910_equivalent","total_seats":len(actual["frame"]),"wrong_seats":len(wrong),
        "correct_seats":len(actual["frame"])-len(wrong),"confusion_pairs":pair_rows,
        "regions":{r:{**v,"accuracy":1.0-v["wrong"]/v["n"] if v["n"] else None} for r,v in sorted(regions.items())},
        "predicted_margin_bands":{b:{**v,"error_rate":v["wrong"]/v["n"] if v["n"] else None} for b,v in sorted(margin_bins.items())},
        "largest_error_pair":pair_rows[0] if pair_rows else None,"wrong_constituencies":wrong,
    }




def _row_winner_and_margin(rows:pd.DataFrame,idx:Any,brow:pd.Series)->tuple[str,float,list[tuple[str,float]]]:
    ordered=sorted(
        ((p,float(rows.at[idx,p])) for p in competitive_parties(brow)),
        key=lambda x:x[1],reverse=True
    )
    winner=ordered[0][0] if ordered else "other"
    margin=float(ordered[0][1]-ordered[1][1]) if len(ordered)>1 else 100.0
    return winner,margin,ordered


def _actual_winner_margin(arow:pd.Series)->float:
    vals=sorted(
        (float(arow[p]) for p in PARTIES if allowed(p,str(arow["country"]))),
        reverse=True
    )
    return float(vals[0]-vals[1]) if len(vals)>1 else 100.0


def build_remaining_error_audit(
    reference_rows:pd.DataFrame,actual:dict[str,Any],base:dict[str,Any],
    canonical_rows:pd.DataFrame,local_profile:dict[str,Any]
)->dict[str,Any]:
    """Describe the residual 2024 errors of the frozen v0.9.15 reference.

    This function is deliberately diagnostic.  It may inspect realised 2024 labels and
    vote shares, but nothing returned here is allowed to select parameters or alter the
    live/canonical candidate.
    """
    pairs=Counter();pair_regions=Counter();regions=defaultdict(lambda:{"n":0,"wrong":0})
    margin_bins=defaultdict(lambda:{"n":0,"wrong":0});baseline_winners=Counter()
    actual_error_winners=Counter();predicted_error_winners=Counter();impact=Counter()
    wrong=[];all_records=[]
    share_error_all=defaultdict(list);share_error_wrong=defaultdict(list)

    for idx,arow in actual["frame"].iterrows():
        brow=base["frame"].loc[idx]
        pw,pmargin,ordered=_row_winner_and_margin(reference_rows,idx,brow)
        cw,cmargin,_=_row_winner_and_margin(canonical_rows,idx,brow)
        rw=str(arow["actual_winner"])
        region=str(arow["region"]);mb=_margin_band(pmargin)
        correct=(pw==rw);canonical_correct=(cw==rw)
        regions[region]["n"]+=1;margin_bins[mb]["n"]+=1
        if canonical_correct and correct:impact_label="unchanged_correct"
        elif (not canonical_correct) and correct:impact_label="fixed_by_local_strength"
        elif canonical_correct and (not correct):impact_label="broken_by_local_strength"
        elif cw!=pw:impact_label="changed_but_still_wrong"
        else:impact_label="unchanged_wrong"
        impact[impact_label]+=1

        lp=local_profile.get("seats",{}).get(str(idx)) or {}
        adv=lp.get("advantage",{}) if isinstance(lp,dict) else {}
        share_errors={}
        for p in PARTIES:
            if not allowed(p,str(arow["country"])):continue
            err=float(reference_rows.at[idx,p])-float(arow[p])
            share_errors[p]=err;share_error_all[p].append(err)
            if not correct:share_error_wrong[p].append(err)

        record={
            "id":str(arow["id"]),"name":str(arow["name"]),"country":str(arow["country"]),"region":region,
            "predicted_winner":pw,"actual_winner":rw,"canonical_winner":cw,
            "prediction_changed_by_local_strength":bool(pw!=cw),"local_impact":impact_label,
            "predicted_margin":float(pmargin),"canonical_margin":float(cmargin),
            "actual_margin":_actual_winner_margin(arow),"predicted_margin_band":mb,
            "baseline_winner":str(brow.get("actual_winner") or ""),"baseline_second":str(brow.get("actual_second") or ""),
            "baseline_margin":float(_baseline_margin(brow)),"competition_key":_competition_key(brow),
            "predicted_top3":[{"party":p,"share":v} for p,v in ordered[:3]],
            "predicted_shares":{p:float(reference_rows.at[idx,p]) for p in PARTIES if allowed(p,str(arow["country"]))},
            "actual_shares":{p:float(arow[p]) for p in PARTIES if allowed(p,str(arow["country"]))},
            "share_error_pred_minus_actual":share_errors,
            "local_profile":{
                "available":bool(lp),
                "confidence":float(lp.get("confidence") or 0.0) if lp else 0.0,
                "coverage":float(lp.get("coverage") or 0.0) if lp else 0.0,
                "mean_age_years":float(lp.get("mean_age_years") or 0.0) if lp else None,
                "advantage":{p:float(adv.get(p,0.0)) for p in PARTIES if p in adv},
                "actual_minus_predicted_advantage":float(adv.get(rw,0.0)-adv.get(pw,0.0)) if lp else None,
            },
        }
        all_records.append(record)
        if not correct:
            pairs[(pw,rw)]+=1;pair_regions[(pw,rw,region)]+=1
            regions[region]["wrong"]+=1;margin_bins[mb]["wrong"]+=1
            baseline_winners[str(brow.get("actual_winner") or "")]+=1
            actual_error_winners[rw]+=1;predicted_error_winners[pw]+=1
            wrong.append(record)

    pair_rows=[{"predicted":a,"actual":b,"count":int(n)} for (a,b),n in pairs.most_common()]
    pair_region_rows=[
        {"predicted":a,"actual":b,"region":r,"count":int(n)}
        for (a,b,r),n in pair_regions.most_common()
    ]
    correct=len(actual["frame"])-len(wrong)
    if len(actual["frame"])!=632 or correct!=501 or len(wrong)!=131:
        raise RuntimeError(f"v0.9.15 remaining-error audit regression mismatch: correct={correct} wrong={len(wrong)}")

    priority=[]
    for row in pair_rows:
        if row["count"]>=5:
            priority.append({"family":"predicted_to_actual","key":f"{row['predicted']}->{row['actual']}","count":row["count"]})
    for row in pair_region_rows:
        if row["count"]>=5:
            priority.append({"family":"predicted_to_actual_by_region","key":f"{row['predicted']}->{row['actual']}|{row['region']}","count":row["count"]})
    for region,v in regions.items():
        if v["wrong"]>=5:
            priority.append({"family":"region","key":region,"count":int(v["wrong"]),"error_rate":v["wrong"]/v["n"] if v["n"] else None})
    priority.sort(key=lambda x:(-int(x["count"]),str(x["family"]),str(x["key"])))

    def err_summary(vals:dict[str,list[float]])->dict[str,Any]:
        out={}
        for p,items in vals.items():
            arr=np.asarray(items,float)
            if arr.size:
                out[p]={"n":int(arr.size),"mean_bias":float(arr.mean()),"mae":float(np.abs(arr).mean()),
                        "median_bias":float(np.median(arr))}
        return out

    local_available=sum(1 for r in wrong if r["local_profile"]["available"])
    return {
        "version":"uk-v0917-error-audit","status":"ok","generated_at":utcnow().isoformat(),
        "diagnostic_only":True,"shadow_only":True,"used_for_parameter_selection":False,
        "changes_production_model":False,"changes_candidate_model":False,
        "source_candidate":"v0.9.15 reference local_strength=0.25 byelection_strength=0",
        "benchmark":"2019_notional_to_2024","benchmark_role":"development_diagnostic_not_pristine_holdout",
        "interpretation_warning":(
            "2024 outcomes are used only to diagnose the 131 residual errors of the pre-2024-selected v0.9.15 reference. "
            "No rule, coefficient, threshold, feature or promotion decision is selected from this audit."
        ),
        "totals":{"seats":632,"correct":501,"wrong":131,"accuracy":501/632,
                  "target_80pct_correct":506,"minimum_net_recoveries_for_80pct":5},
        "seat_distribution":{
            "predicted":dict(Counter(r["predicted_winner"] for r in all_records)),
            "actual":dict(Counter(r["actual_winner"] for r in all_records)),
        },
        "confusion_pairs":pair_rows,"pair_region_clusters":pair_region_rows,
        "largest_error_pair":pair_rows[0] if pair_rows else None,
        "error_winners":{"predicted":dict(predicted_error_winners),"actual":dict(actual_error_winners)},
        "baseline_winner_among_errors":dict(baseline_winners),
        "regions":{r:{**v,"accuracy":1.0-v["wrong"]/v["n"] if v["n"] else None} for r,v in sorted(regions.items())},
        "predicted_margin_bands":{b:{**v,"error_rate":v["wrong"]/v["n"] if v["n"] else None} for b,v in sorted(margin_bins.items())},
        "local_strength_impact_vs_v0910":{"counts":dict(impact),
            "net_correct_gain":int(impact["fixed_by_local_strength"]-impact["broken_by_local_strength"])},
        "local_profile_on_remaining_errors":{"available":int(local_available),"missing":int(len(wrong)-local_available),
            "mean_confidence":float(np.mean([r["local_profile"]["confidence"] for r in wrong if r["local_profile"]["available"]])) if local_available else None,
            "mean_coverage":float(np.mean([r["local_profile"]["coverage"] for r in wrong if r["local_profile"]["available"]])) if local_available else None},
        "party_share_error":{"all_632":err_summary(share_error_all),"wrong_131":err_summary(share_error_wrong)},
        "priority_families_min5":priority,
        "wrong_constituencies":wrong,
        "local_strength_fixed_seats":[r for r in all_records if r["local_impact"]=="fixed_by_local_strength"],
        "local_strength_broken_seats":[r for r in all_records if r["local_impact"]=="broken_by_local_strength"],
        "next_step_policy":(
            "Use this audit to nominate a small number of hypotheses only. Any new correction inspired by 2024 must be "
            "validated on a historical analogue or a fresh external election before promotion."
        ),
        "parameter_updates":{},
    }


def evaluate_v0915_reference(
    val_rows:pd.DataFrame,hold_rows:pd.DataFrame,e17:dict[str,Any],e19:dict[str,Any],
    e19n:dict[str,Any],e24:dict[str,Any]
)->tuple[dict[str,Any],pd.DataFrame,dict[str,Any]]:
    """Reproduce the frozen v0.9.15 reference without any new tuning."""
    raw19,src19=fetch_dc_local_results(LOCAL_DATES_2019)
    raw24,src24=fetch_dc_local_results(LOCAL_DATES_2024)
    ons19,ons19_meta=fetch_ons_ward_lookup("2019");ons24,ons24_meta=fetch_ons_ward_lookup("2024")
    local19=build_local_advantage_profile(e17,raw19,ons19,"2019-12-12")
    local24=build_local_advantage_profile(e19n,raw24,ons24,"2024-07-04")
    if local19["matched_seats"]<300 or local24["matched_seats"]<300:
        raise RuntimeError(f"Local-strength coverage too low: 2019={local19['matched_seats']} 2024={local24['matched_seats']}")
    target19=nat_shares(e19);target24=nat_shares(e24)
    rows19,meta19=apply_local_election_strength_refined(val_rows,e17,target19,local19,0.25,0.0,None)
    rows24,meta24=apply_local_election_strength_refined(hold_rows,e19n,target24,local24,0.25,0.0,None)
    m19=evaluate_rows(rows19,e19,e17);m24=evaluate_rows(rows24,e24,e19n)
    if m19["correct_winners"]!=585 or m19["seat_abs_error_sum"]!=42:
        raise RuntimeError(f"v0.9.15 reference 2019 regression failed: {m19}")
    if m24["correct_winners"]!=501 or m24["seat_abs_error_sum"]!=166:
        raise RuntimeError(f"v0.9.15 reference 2024 regression failed: {m24}")
    report={
        "version":"uk-v0917-error-audit","status":"ok","generated_at":utcnow().isoformat(),
        "diagnostic_only":True,"shadow_only":True,"uses_2024_for_parameter_selection":False,
        "parameter_selection_election":"2019","reference_parameters":dict(V0915_REFERENCE),
        "method":"frozen v0.9.15 local-authority advantage; local_strength=0.25, confidence_floor=0, no margin cap, by-election strength=0",
        "validation_2019":m19,"benchmark_2024":m24,"meta_2019":meta19,"meta_2024":meta24,
        "coverage":{"local_2019":{k:v for k,v in local19.items() if k!="seats"},
                    "local_2024":{k:v for k,v in local24.items() if k!="seats"}},
        "sources":{"local_2019":src19,"local_2024":src24,"ons_2019":ons19_meta,"ons_2024":ons24_meta},
        "note":"This file reproduces the v0.9.15 reference only; it contains no parameter sweep and cannot promote a model.",
    }
    return report,rows24,local24


def _apply_structural_config(
    canonical:pd.DataFrame,base:dict[str,Any],target:dict[str,float],history:list[dict[str,Any]],
    place_profile:dict[str,Any],gradient_strength:float,region_strength:float,competition_strength:float
)->tuple[pd.DataFrame,dict[str,Any]]:
    a,gmeta=apply_regradient(canonical,base,target,history,gradient_strength)
    b,pmeta=apply_place_residual(a,base,target,place_profile,region_strength,competition_strength)
    return b,{"regradient":gmeta,"place":pmeta}


def evaluate_local_strength_sweep(
    dev_rows:pd.DataFrame,val_rows:pd.DataFrame,hold_rows:pd.DataFrame,
    e15:dict[str,Any],e17:dict[str,Any],e19:dict[str,Any],e19n:dict[str,Any],e24:dict[str,Any],
    t10_15:dict[str,Any],t15_17:dict[str,Any],t17_19:dict[str,Any],
    validation_base_metrics:dict[str,Any],holdout_base_metrics:dict[str,Any]
)->dict[str,Any]:
    """Select all strengths on 2019 only; 2024 is score-only research."""
    target19=nat_shares(e19);target24=nat_shares(e24)
    profile17=build_place_residual_profile(dev_rows,e17,e15)
    candidates=[];val_row_cache={}
    for gs in REGRADE_STRENGTH_GRID:
        regraded,gmeta=apply_regradient(val_rows,e17,target19,[t10_15,t15_17],gs)
        for rs in PLACE_REGION_STRENGTH_GRID:
            for cs in PLACE_COMP_STRENGTH_GRID:
                adjusted,pmeta=apply_place_residual(regraded,e17,target19,profile17,rs,cs)
                metrics=evaluate_rows(adjusted,e19,e17)
                cid=f"g{gs:.2f}_r{rs:.2f}_c{cs:.2f}"
                candidates.append({"id":cid,"gradient_strength":gs,"region_strength":rs,"competition_strength":cs,"validation_2019":metrics,"meta_2019":{"regradient":gmeta,"place":pmeta}})
                val_row_cache[cid]=adjusted
    # Selection is explicitly pre-2024.  Prefer simpler configuration only after metrics tie.
    candidates.sort(key=lambda x:(score_tuple(x["validation_2019"]),-(x["gradient_strength"]+x["region_strength"]+x["competition_strength"])),reverse=True)
    selected=candidates[0]
    selected_id=selected["id"]
    # Roll the residual profile forward using the selected, honestly generated 2019 prediction.
    profile19=build_place_residual_profile(val_row_cache[selected_id],e19,e17)
    selected_hold,selected_meta=_apply_structural_config(
        hold_rows,e19n,target24,[t10_15,t15_17,t17_19],profile19,
        selected["gradient_strength"],selected["region_strength"],selected["competition_strength"]
    )
    selected_2024=evaluate_rows(selected_hold,e24,e19n)

    # Benchmark only the configurations that were already top-ranked on 2019.
    # This avoids a 2024-wide oracle search and keeps the diagnostic bounded to
    # a pre-2024 shortlist.  The first item is the actual selected candidate.
    benchmark_shortlist=[]
    for cand in candidates[:12]:
        cid=cand["id"]
        prof=build_place_residual_profile(val_row_cache[cid],e19,e17)
        hrows,hmeta=_apply_structural_config(
            hold_rows,e19n,target24,[t10_15,t15_17,t17_19],prof,
            cand["gradient_strength"],cand["region_strength"],cand["competition_strength"]
        )
        hm=evaluate_rows(hrows,e24,e19n)
        benchmark_shortlist.append({
            "id":cid,"pre2024_rank":len(benchmark_shortlist)+1,
            "gradient_strength":cand["gradient_strength"],"region_strength":cand["region_strength"],
            "competition_strength":cand["competition_strength"],"validation_2019":cand["validation_2019"],"benchmark_2024":hm,
            "research_gate":bool(hm["correct_winners"]>=506 and hm["seat_abs_error_sum"]<=176),
        })
    baseline19=evaluate_rows(val_rows,e19,e17);baseline24=evaluate_rows(hold_rows,e24,e19n)
    selected_gate=bool(selected_2024["correct_winners"]>=506 and selected_2024["seat_abs_error_sum"]<=176)
    return {
        "version":"uk-v0917-error-audit","status":"ok","generated_at":utcnow().isoformat(),
        "shadow_only":True,"uses_2024_for_parameter_selection":False,"parameter_selection_election":"2019",
        "selection_policy":"grid fixed in source; rank by 2019 correct winners, then seat error, then share MAE; 2024 labels never select strengths",
        "methods":{
            "regradient":"baseline-aligned party slope correction learned from prior elections; national target preserved by raking",
            "place_residual":"rolling prior-election residual by region plus shrunk region/winner/runner-up/margin-band competition cell; no constituency identity",
            "spatial_scope":"low-dimensional place proxy, not a full ICAR adjacency model",
        },
        "baseline":{"validation_2019":baseline19,"benchmark_2024":baseline24},
        "selected_pre2024":{
            "id":selected_id,"gradient_strength":selected["gradient_strength"],"region_strength":selected["region_strength"],
            "competition_strength":selected["competition_strength"],"validation_2019":selected["validation_2019"],
            "benchmark_2024":selected_2024,"research_gate":selected_gate,"meta_2024":selected_meta,
        },
        "pre2024_validation_ranking":[{
            "id":x["id"],"gradient_strength":x["gradient_strength"],"region_strength":x["region_strength"],
            "competition_strength":x["competition_strength"],"validation_2019":x["validation_2019"]
        } for x in candidates[:20]],
        "benchmark_2024_pre2024_shortlist":{
            "candidates":benchmark_shortlist,
            "best_by_2024_diagnostic":max(benchmark_shortlist,key=lambda x:score_tuple(x["benchmark_2024"])),
            "passing_research_gate":[x["id"] for x in benchmark_shortlist if x["research_gate"]],
            "warning":"All candidates in this shortlist were selected/ranked on 2019 before 2024 was inspected; the 2024 comparison is diagnostic only."
        },
        "profiles":{
            "for_2019_from_honest_2017_residuals":profile17,
            "for_2024_from_selected_honest_2019_residuals":profile19,
        },
        "candidate_count":len(candidates),
        "research_gate_definition":"2024 >=506/632 correct AND seat_abs_error_sum <=176; informational only",
    }



def _truthy(v:Any)->bool:
    return str(v or "").strip().lower() in {"1","true","yes","y","t"}


def _authority_key(v:Any)->str:
    k=nkey(v)
    # Organisation labels and ONS LAD names differ mostly by administrative suffixes.
    suffixes=("metropolitanboroughcouncil","citycouncil","boroughcouncil","districtcouncil","countycouncil",
              "council","borough","district")
    changed=True
    while changed:
        changed=False
        for suffix in suffixes:
            if k.endswith(suffix) and len(k)>len(suffix)+3:
                k=k[:-len(suffix)];changed=True;break
    return k


def _place_key(v:Any)->str:
    k=nkey(v).replace("saint","st")
    return k.replace("the","") if k.startswith("the") else k


def _dc_csv(params:list[tuple[str,str]],label:str)->pd.DataFrame:
    headers={"User-Agent":"modello-uk/0.9.17 research; public election data"}
    r=requests.get(DC_EXPORT_URL,params=params,headers=headers,timeout=120)
    r.raise_for_status()
    text=r.text
    if len(text)<100 or "votes_cast" not in text:
        raise RuntimeError(f"Democracy Club {label}: unexpected/empty CSV response ({len(text)} bytes)")
    df=pd.read_csv(io.StringIO(text),low_memory=False)
    if "votes_cast" not in df.columns or "party_name" not in df.columns:
        raise RuntimeError(f"Democracy Club {label}: required result columns missing: {list(df.columns)}")
    return df


def fetch_dc_local_results(dates:tuple[str,...])->tuple[pd.DataFrame,dict[str,Any]]:
    frames=[];meta=[]
    for date in dates:
        params=[("election_date",date),("election_id","^local.*"),("format","csv"),
                ("field_group","results"),("field_group","election")]
        df=_dc_csv(params,f"local {date}")
        df["_requested_date"]=date
        frames.append(df);meta.append({"date":date,"rows":int(len(df))})
    out=pd.concat(frames,ignore_index=True,sort=False)
    return out,{"source":"Democracy Club candidates/results CSV export","url":DC_EXPORT_URL,
                "requested_dates":list(dates),"downloads":meta,"rows":int(len(out))}


def fetch_dc_byelections()->tuple[pd.DataFrame,dict[str,Any]]:
    params=[("election_id","^parl.*"),("by_election","True"),("format","csv"),
            ("field_group","results"),("field_group","election")]
    df=_dc_csv(params,"parliamentary by-elections")
    return df,{"source":"Democracy Club parliamentary by-election CSV export","url":DC_EXPORT_URL,"rows":int(len(df))}


def _aggregate_ballots(df:pd.DataFrame,organisation_field:str|None)->pd.DataFrame:
    work=df.copy()
    work["votes_cast"]=pd.to_numeric(work["votes_cast"],errors="coerce")
    work=work[work["votes_cast"].notna() & (work["votes_cast"]>=0)].copy()
    if "cancelled_poll" in work.columns:
        work=work[~work["cancelled_poll"].map(_truthy)].copy()
    if work.empty:return pd.DataFrame()
    work["_party"]=work["party_name"].map(lambda x:canonical_party_label(x,allow_blank=True))
    work=work[work["_party"].isin(PARTIES)].copy()
    if "ballot_paper_id" not in work.columns:
        raise RuntimeError("Democracy Club results missing ballot_paper_id")
    records=[]
    for ballot,bg in work.groupby("ballot_paper_id",sort=False):
        party_votes=bg.groupby("_party")["votes_cast"].mean().to_dict()
        den=float(sum(party_votes.values()))
        if den<=0:continue
        rec={"ballot_paper_id":str(ballot),"effective_votes":den,
             "election_date":str(bg["election_date"].iloc[0]) if "election_date" in bg else str(bg["_requested_date"].iloc[0])}
        if organisation_field and organisation_field in bg.columns:
            rec["organisation_name"]=str(bg[organisation_field].dropna().iloc[0]) if bg[organisation_field].notna().any() else ""
        if "post_label" in bg.columns:
            rec["post_label"]=str(bg["post_label"].dropna().iloc[0]) if bg["post_label"].notna().any() else ""
        for p in PARTIES:rec[p]=float(party_votes.get(p,0.0))/den*100.0
        records.append(rec)
    return pd.DataFrame(records)


def aggregate_local_profiles(raw:pd.DataFrame)->tuple[dict[str,dict[str,Any]],dict[str,Any]]:
    org_field="organisation_name" if "organisation_name" in raw.columns else None
    ballots=_aggregate_ballots(raw,org_field)
    if ballots.empty or "organisation_name" not in ballots.columns:
        raise RuntimeError("No usable local-election ballots/organisation names from Democracy Club")
    ballots=ballots[ballots["organisation_name"].astype(str).str.len()>0].copy()
    # National contemporaneous benchmark for each local election date removes midterm mood.
    daily_nat={}
    for date,dg in ballots.groupby("election_date"):
        w=dg["effective_votes"].to_numpy(float);den=float(w.sum()) or 1.0
        daily_nat[str(date)]={p:float(np.sum(dg[p].to_numpy(float)*w)/den) for p in PARTIES}
    profiles={};coverage=[]
    for (date,org),g in ballots.groupby(["election_date","organisation_name"]):
        w=g["effective_votes"].to_numpy(float);den=float(w.sum()) or 1.0
        shares={p:float(np.sum(g[p].to_numpy(float)*w)/den) for p in PARTIES}
        key=_authority_key(org)
        if not key:continue
        rec={"authority":str(org),"date":str(date),"wards":int(len(g)),"effective_votes":den,
             "shares":shares,"relative":{p:shares[p]-daily_nat[str(date)].get(p,0.0) for p in PARTIES}}
        old=profiles.get(key)
        if old is None or rec["date"]>old["date"]:profiles[key]=rec
        coverage.append(key)
    return profiles,{"authorities_latest":len(profiles),"ballots":int(len(ballots)),"daily_national":daily_nat,
                     "authority_keys_seen":len(set(coverage))}


def fetch_ons_ward_lookup(year:str)->tuple[list[dict[str,str]],dict[str,Any]]:
    spec=ONS_LOOKUPS[year]
    headers={
        "User-Agent":"modello-uk/0.9.17 research",
        "Accept":"text/csv,application/octet-stream,application/json;q=0.8,*/*;q=0.5",
    }
    failures=[]

    # Primary path: public ArcGIS Hub download API.  ONS/Data.gov.uk publishes
    # these exact item IDs as public CSV resources.  This avoids depending on
    # direct FeatureServer query permissions, which may change independently of
    # the public download status of the dataset.
    for url in spec.get("downloads",()):
        try:
            response=None
            for attempt in range(7):
                response=requests.get(url,headers=headers,timeout=120,allow_redirects=True)
                response.raise_for_status()
                ctype=(response.headers.get("content-type") or "").lower()
                body=response.content
                # Hub can return a small JSON status object while refreshing a
                # cached export.  Poll the same public URL for up to ~30 seconds.
                if "json" in ctype or body.lstrip().startswith(b"{"):
                    try:payload=response.json()
                    except Exception:payload={}
                    status=str(payload.get("status") or "").lower()
                    if status in {"pending","processing","converting","generating"}:
                        if attempt>=6:raise RuntimeError(f"Hub CSV still {status}: {payload}")
                        time.sleep(5);continue
                    raise RuntimeError(f"unexpected Hub JSON response: {payload}")
                frame=pd.read_csv(io.BytesIO(body),dtype=str,encoding="utf-8-sig")
                if spec["pcon"] not in frame.columns or spec["lad"] not in frame.columns:
                    raise RuntimeError(f"CSV missing {spec['pcon']}/{spec['lad']}; columns={list(frame.columns)[:20]}")
                rows=[]
                for pcon,lad in zip(frame[spec["pcon"]],frame[spec["lad"]]):
                    pcon="" if pd.isna(pcon) else str(pcon).strip()
                    lad="" if pd.isna(lad) else str(lad).strip()
                    if pcon and lad:rows.append({"pcon":pcon,"lad":lad})
                if len(rows)<5000:raise RuntimeError(f"lookup CSV unexpectedly small: {len(rows)}")
                return rows,{"source":"ONS Open Geography Portal public Hub CSV","year":year,
                             "url":url,"resolved_url":response.url,"rows":len(rows),
                             "fallbacks_tried":len(failures),"transport":"hub_csv"}
            raise RuntimeError("Hub CSV polling exhausted without data")
        except Exception as exc:
            failures.append({"url":url,"transport":"hub_csv","error":str(exc)})

    # Last-resort compatibility path for any ONS FeatureServer that still permits
    # anonymous REST queries.  A Token Required response is treated as a source
    # failure, not as a model/data result.
    urls=list(spec.get("queries") or ([spec["query"]] if spec.get("query") else []))
    for url in urls:
        try:
            ids=requests.get(url,params={"where":"1=1","returnIdsOnly":"true","f":"json"},headers=headers,timeout=120)
            ids.raise_for_status();ij=ids.json()
            if "error" in ij:raise RuntimeError(str(ij["error"]))
            object_ids=ij.get("objectIds") or []
            if not object_ids:raise RuntimeError(f"returned no object IDs: {ij}")
            rows=[]
            for i in range(0,len(object_ids),800):
                batch=object_ids[i:i+800]
                params={"objectIds":",".join(map(str,batch)),"outFields":f"{spec['pcon']},{spec['lad']}",
                        "returnGeometry":"false","f":"json"}
                r=requests.get(url,params=params,headers=headers,timeout=120);r.raise_for_status();j=r.json()
                if "error" in j:raise RuntimeError(f"lookup error: {j['error']}")
                for feat in j.get("features",[]):
                    a=feat.get("attributes",{});pcon=str(a.get(spec["pcon"]) or "");lad=str(a.get(spec["lad"]) or "")
                    if pcon and lad:rows.append({"pcon":pcon,"lad":lad})
            if len(rows)<5000:raise RuntimeError(f"lookup unexpectedly small: {len(rows)}")
            return rows,{"source":"ONS Open Geography Portal FeatureServer fallback","year":year,
                         "url":url,"rows":len(rows),"fallbacks_tried":len(failures),"transport":"feature_query"}
        except Exception as exc:
            failures.append({"url":url,"transport":"feature_query","error":str(exc)})
    raise RuntimeError(f"ONS {year} lookup unavailable from all configured public downloads/endpoints: {failures}")


def build_local_advantage_profile(base:dict[str,Any],raw_local:pd.DataFrame,lookup_rows:list[dict[str,str]],target_date:str)->dict[str,Any]:
    profiles,agg_meta=aggregate_local_profiles(raw_local)
    by_pcon=defaultdict(Counter)
    for r in lookup_rows:by_pcon[_place_key(r["pcon"])][_authority_key(r["lad"])]+=1
    base_nat=nat_shares(base);target_dt=datetime.fromisoformat(target_date+"T00:00:00+00:00")
    seat_profile={};matched=0;weighted_coverage=[]
    for idx,row in base["frame"].iterrows():
        counts=by_pcon.get(_place_key(row["name"]),Counter());total=sum(counts.values())
        if not total:continue
        rel={p:0.0 for p in PARTIES};used=0.0;conf_num=0.0;date_num=0.0
        for lad,n in counts.items():
            pr=profiles.get(lad)
            if not pr:continue
            wt=float(n);used+=wt
            age=max(0.0,(target_dt-datetime.fromisoformat(pr["date"]+"T00:00:00+00:00")).total_seconds()/31557600.0)
            recency=.5**(age/LOCAL_RECENCY_HALF_LIFE_YEARS)
            ward_conf=min(1.0,math.sqrt(max(1,pr["wards"])/8.0))
            conf_num+=wt*recency*ward_conf;date_num+=wt*age
            for p in PARTIES:rel[p]+=wt*float(pr["relative"].get(p,0.0))
        if used<=0:continue
        for p in PARTIES:rel[p]/=used
        coverage=used/max(1.0,float(total));confidence=coverage*(conf_num/used)
        adv={}
        for p in PARTIES:
            baseline_relative=float(row[p])-float(base_nat[p])
            adv[p]=clamp(rel[p]-baseline_relative,-30.0,30.0)
        seat_profile[str(idx)]={"confidence":float(confidence),"coverage":float(coverage),"advantage":adv,
                                "mean_age_years":float(date_num/used if used else 0.0)}
        matched+=1;weighted_coverage.append(coverage)
    return {"seats":seat_profile,"matched_seats":matched,"total_seats":len(base["frame"]),
            "mean_authority_coverage":float(np.mean(weighted_coverage)) if weighted_coverage else 0.0,
            "aggregation":agg_meta,"target_date":target_date}


def build_byelection_profile(raw:pd.DataFrame,base:dict[str,Any],after_date:str,before_date:str)->dict[str,Any]:
    ballots=_aggregate_ballots(raw,None)
    if ballots.empty:return {"seats":{},"matched_seats":0,"source_ballots":0}
    ballots["_date"]=pd.to_datetime(ballots["election_date"],errors="coerce",utc=True)
    lo=pd.Timestamp(after_date,tz="UTC");hi=pd.Timestamp(before_date,tz="UTC")
    ballots=ballots[(ballots["_date"]>lo)&(ballots["_date"]<hi)].copy()
    base_by_name={_place_key(r["name"]):idx for idx,r in base["frame"].iterrows()}
    hi_dt=datetime.fromisoformat(before_date+"T00:00:00+00:00")
    seats={}
    for _,r in ballots.sort_values("_date").iterrows():
        key=_place_key(r.get("post_label",""));idx=base_by_name.get(key)
        if idx is None:continue
        brow=base["frame"].loc[idx]
        age=max(0.0,(hi_dt-r["_date"].to_pydatetime()).total_seconds()/31557600.0)
        conf=.5**(age/BYELECTION_RECENCY_HALF_LIFE_YEARS)
        delta={p:clamp(float(r[p])-float(brow[p]),-35.0,35.0) for p in PARTIES}
        seats[str(idx)]={"confidence":float(conf),"date":str(r["election_date"]),"post_label":str(r.get("post_label","")),"delta":delta}
    return {"seats":seats,"matched_seats":len(seats),"source_ballots":int(len(ballots)),
            "window":{"after":after_date,"before":before_date}}


def _canonical_margin(rows:pd.DataFrame,idx:Any,brow:pd.Series)->float:
    ordered=sorted((float(rows.at[idx,p]) for p in competitive_parties(brow)),reverse=True)
    return float(ordered[0]-ordered[1]) if len(ordered)>1 else 100.0


def apply_local_election_strength_refined(
    canonical:pd.DataFrame,base:dict[str,Any],target:dict[str,float],local_profile:dict[str,Any],
    local_strength:float,confidence_floor:float,margin_cap:float|None
)->tuple[pd.DataFrame,dict[str,Any]]:
    """Apply only pre-election local-election strength with pre-election reliability gates."""
    strength=float(local_strength);floor=float(confidence_floor)
    cap=None if margin_cap is None else float(margin_cap)
    if strength==0.0:
        return canonical.copy(),{
            "local_strength":0.0,"confidence_floor":floor,"margin_cap":cap,
            "adjusted_seats":0,"eligible_profile_seats":0,"skipped_low_confidence":0,
            "skipped_safe_margin":0,"mean_abs_pre_rake_shift":0.0,
        }
    out=canonical.copy().astype(float);shifts=[];adjusted=0;eligible=0;low_conf=0;safe=0
    for idx,row in base["frame"].iterrows():
        lp=local_profile.get("seats",{}).get(str(idx))
        can_adjust=bool(lp);conf=0.0
        if lp:
            conf=float(lp.get("confidence") or 0.0)
            if conf+1e-12<floor:
                low_conf+=1;can_adjust=False
            elif cap is not None and _canonical_margin(canonical,idx,row)>cap+1e-12:
                safe+=1;can_adjust=False
        changed=False
        if can_adjust:
            eligible+=1
            for p in MAIN_PARTIES:
                if not allowed(p,str(row["country"])):continue
                delta=strength*conf*float(lp["advantage"].get(p,0.0))
                delta=clamp(delta,-LOCAL_MAX_SEAT_SHIFT,LOCAL_MAX_SEAT_SHIFT)
                if abs(delta)>1e-9:
                    out.at[idx,p]=max(.0001,float(out.at[idx,p])+delta);shifts.append(abs(delta));changed=True
        if changed:adjusted+=1
        # Preserve v0.9.15 semantics exactly: every row is re-normalised before raking,
        # including rows without a local profile or filtered out by the new gates.
        vals={p:(max(.0001,float(out.at[idx,p])) if allowed(p,str(row["country"])) else 0.0) for p in PARTIES}
        den=sum(vals.values()) or 1.0
        for p in PARTIES:out.at[idx,p]=vals[p]/den*100.0
    out=experimental_rake(out,base,target)
    return out,{
        "local_strength":strength,"confidence_floor":floor,"margin_cap":cap,
        "adjusted_seats":adjusted,"eligible_profile_seats":eligible,
        "skipped_low_confidence":low_conf,"skipped_safe_margin":safe,
        "mean_abs_pre_rake_shift":float(np.mean(shifts)) if shifts else 0.0,
    }


def _local_refinement_id(ls:float,cf:float,mc:float|None)->str:
    return f"l{ls:.2f}_q{cf:.2f}_{'all' if mc is None else 'm'+str(int(mc))}"


def _local_refinement_complexity(c:dict[str,Any])->tuple[float,float,float]:
    cap=c.get("margin_cap")
    return (-float(c["local_strength"]),float(c["confidence_floor"]),-(999.0 if cap is None else float(cap)))


def evaluate_local_strength_sweep(val_rows:pd.DataFrame,hold_rows:pd.DataFrame,e17:dict[str,Any],e19:dict[str,Any],
                                  e19n:dict[str,Any],e24:dict[str,Any])->dict[str,Any]:
    """Select refined local-strength parameters on 2019 only; 2024 is score-only."""
    raw19,src19=fetch_dc_local_results(LOCAL_DATES_2019)
    raw24,src24=fetch_dc_local_results(LOCAL_DATES_2024)
    ons19,ons19_meta=fetch_ons_ward_lookup("2019");ons24,ons24_meta=fetch_ons_ward_lookup("2024")
    local19=build_local_advantage_profile(e17,raw19,ons19,"2019-12-12")
    local24=build_local_advantage_profile(e19n,raw24,ons24,"2024-07-04")
    if local19["matched_seats"]<300 or local24["matched_seats"]<300:
        raise RuntimeError(f"Local-strength coverage too low: 2019={local19['matched_seats']} 2024={local24['matched_seats']}")
    target19=nat_shares(e19);target24=nat_shares(e24)
    candidates=[]
    for ls in LOCAL_STRENGTH_GRID:
        for cf in LOCAL_CONFIDENCE_FLOOR_GRID:
            for mc in LOCAL_MARGIN_CAP_GRID:
                rows,meta=apply_local_election_strength_refined(val_rows,e17,target19,local19,ls,cf,mc)
                m=evaluate_rows(rows,e19,e17);cid=_local_refinement_id(ls,cf,mc)
                candidates.append({"id":cid,"local_strength":ls,"confidence_floor":cf,"margin_cap":mc,
                                   "validation_2019":m,"meta_2019":meta})
    candidates.sort(key=lambda x:(score_tuple(x["validation_2019"]),_local_refinement_complexity(x)),reverse=True)
    selected=candidates[0]
    selected_rows24,meta24=apply_local_election_strength_refined(
        hold_rows,e19n,target24,local24,selected["local_strength"],selected["confidence_floor"],selected["margin_cap"])
    selected24=evaluate_rows(selected_rows24,e24,e19n)

    benchmark=[]
    for ls in LOCAL_STRENGTH_GRID:
        for cf in LOCAL_CONFIDENCE_FLOOR_GRID:
            for mc in LOCAL_MARGIN_CAP_GRID:
                rows,meta=apply_local_election_strength_refined(hold_rows,e19n,target24,local24,ls,cf,mc)
                m=evaluate_rows(rows,e24,e19n);cid=_local_refinement_id(ls,cf,mc)
                benchmark.append({"id":cid,"local_strength":ls,"confidence_floor":cf,"margin_cap":mc,
                                  "benchmark_2024":m,"meta_2024":meta,
                                  "research_gate":bool(m["correct_winners"]>=506 and m["seat_abs_error_sum"]<=166)})
    benchmark.sort(key=lambda x:score_tuple(x["benchmark_2024"]),reverse=True)

    ref19_rows,ref19_meta=apply_local_election_strength_refined(val_rows,e17,target19,local19,0.25,0.0,None)
    ref24_rows,ref24_meta=apply_local_election_strength_refined(hold_rows,e19n,target24,local24,0.25,0.0,None)
    ref19=evaluate_rows(ref19_rows,e19,e17);ref24=evaluate_rows(ref24_rows,e24,e19n)
    baseline19=evaluate_rows(val_rows,e19,e17);baseline24=evaluate_rows(hold_rows,e24,e19n)
    gate=bool(selected24["correct_winners"]>=506 and selected24["seat_abs_error_sum"]<=166)
    return {
        "version":"uk-v0917-error-audit","status":"ok","generated_at":utcnow().isoformat(),
        "shadow_only":True,"uses_2024_for_parameter_selection":False,"parameter_selection_election":"2019",
        "candidate_count":len(candidates),
        "grid":{"local_strength":list(LOCAL_STRENGTH_GRID),"confidence_floor":list(LOCAL_CONFIDENCE_FLOOR_GRID),
                "margin_cap":list(LOCAL_MARGIN_CAP_GRID),"byelection_strength_fixed":0.0},
        "temporal_policy":{"validation_2019":{"local_dates":list(LOCAL_DATES_2019),"cutoff":"2019-12-12"},
                           "benchmark_2024":{"local_dates":list(LOCAL_DATES_2024),"cutoff":"2024-07-04"}},
        "method":"v0.9.15 local-authority advantage only; fine strength grid plus minimum source-confidence and canonical predicted-margin gates; by-election strength fixed at zero; national target restored by raking",
        "selection_policy":"81 candidates fixed in source; 2019 only selects by correct winners, seat error and share MAE; ties prefer lower strength, higher confidence floor and tighter margin scope; 2024 cannot select",
        "baseline":{"validation_2019":baseline19,"benchmark_2024":baseline24},
        "v0915_reference":{"parameters":V0915_REFERENCE,"validation_2019":ref19,"benchmark_2024":ref24,
                           "meta_2019":ref19_meta,"meta_2024":ref24_meta},
        "selected_pre2024":{"id":selected["id"],"local_strength":selected["local_strength"],
                            "confidence_floor":selected["confidence_floor"],"margin_cap":selected["margin_cap"],
                            "validation_2019":selected["validation_2019"],"benchmark_2024":selected24,
                            "meta_2024":meta24,"research_gate":gate},
        "pre2024_validation_ranking":candidates,
        "benchmark_2024_diagnostic":{"ranking":benchmark,"best_expost":benchmark[0],
                                     "passing_research_gate":[x["id"] for x in benchmark if x["research_gate"]],
                                     "warning":"2024 ranking is diagnostic only and cannot select parameters"},
        "coverage":{"local_2019":{k:v for k,v in local19.items() if k!="seats"},
                    "local_2024":{k:v for k,v in local24.items() if k!="seats"}},
        "sources":{"local_2019":src19,"local_2024":src24,"ons_2019":ons19_meta,"ons_2024":ons24_meta},
        "research_gate_definition":"selected-on-2019 candidate must reach >=506/632 correct in 2024 AND seat_abs_error_sum <=166; informational only",
        "next_step_if_no_fixed_candidate_passes":"stop local-strength tuning and run the planned audit of remaining errors",
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
        "version":"uk-v0917-error-audit",
        "model_type":"constituency-residual-error-audit-v11",
        "status":"error",
        "approved":False,
        "publication_ready":False,
        "diagnostic_only":True,
        "used_for_parameter_selection":False,
        "changes_production_model":False,
        "changes_candidate_model":False,
        "shadow_only":True,
        "generated_at":utcnow().isoformat(),
        "error":str(exc),
        "traceback_tail":traceback.format_exc().splitlines()[-12:],
        "note":"Audit build failed; the previously deployed production/fallback model must remain unchanged.",
    }
    MODEL_OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    LIVE_OUT.write_text(json.dumps({
        "version":"uk-v0917-error-audit-live","approved":False,"status":"error",
        "diagnostic_only":True,"changes_production_model":False,"changes_candidate_model":False,"shadow_only":True,
        "generated_at":utcnow().isoformat(),"seats":[]
    },ensure_ascii=False,indent=2),encoding="utf-8")
    BACKTEST_OUT.write_text(json.dumps({
        "version":"uk-v0917-error-audit-backtest","status":"error","error":str(exc)
    },ensure_ascii=False,indent=2),encoding="utf-8")
    DIAGNOSTIC_OUT.write_text(json.dumps({
        "version":"uk-v0917-error-audit","status":"error",
        "diagnostic_only":True,"used_for_parameter_selection":False,
        "changes_production_model":False,"parameter_updates":{},
        "source_model":"uk-v0917-error-audit",
        "error":str(exc)
    },ensure_ascii=False,indent=2),encoding="utf-8")
    SWEEP_OUT.write_text(json.dumps({
        "version":"uk-v0917-error-audit","status":"error",
        "diagnostic_only":True,"used_for_parameter_selection":False,
        "changes_production_model":False,"error":str(exc)
    },ensure_ascii=False,indent=2),encoding="utf-8")
    if not INTEGRITY_OUT.exists():
        INTEGRITY_OUT.write_text(json.dumps({
            "version":"uk-v0917-bes-integrity","status":"failed",
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

        # HARD PARSER GATE. No target-election fitting is allowed before these pass.
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

        selected_spec,tuning=tune_spec(t10_15,t15_17)

        # 2017 development election: share model trained only through 2015.
        dev_models,dev_names=train_models([t10_15],selected_spec)
        dev_raw=predict_transition(
            e15,t15_17["target"],dev_models,dev_names,selected_spec
        )
        dev_dispersed,dev_dispersion=calibrate_party_dispersion(
            dev_raw,e15,t15_17["target"],[e10,e15]
        )
        selected_party_strengths,party_strength_tuning,dev_contest_scores=(
            tune_party_strengths(
                dev_dispersed,e15,e17,t15_17["target"],[t10_15]
            )
        )
        dev_calibrated=calibrate_with_party_strengths(
            dev_dispersed,dev_contest_scores,e15,t15_17["target"],
            selected_party_strengths
        )
        selected_routing,routing_tuning,dev_routed=tune_incumbent_routing(
            dev_calibrated,e15,e17,t15_17["target"]
        )
        development_2017=evaluate_rows(dev_routed,e17,e15)

        # 2019 is temporal validation for the new party-specific calibration.
        models_val,names_val=train_models([t10_15,t15_17],selected_spec)
        val_raw=predict_transition(
            e17,t17_19["target"],models_val,names_val,selected_spec
        )
        validation_share_only=evaluate_rows(val_raw,e19,e17)
        val_pre_route,val_dispersion,val_contest_scores=apply_party_calibration(
            val_raw,e17,t17_19["target"],
            [e10,e15,e17],[t10_15,t15_17],
            selected_party_strengths
        )
        validation_pre_route=evaluate_rows(val_pre_route,e19,e17)
        val_rows,val_routing=route_incumbent_collapse(
            val_pre_route,e17,t17_19["target"],
            selected_routing["route_strength"],
            selected_routing["unwind_strength"]
        )
        validation=evaluate_rows(val_rows,e19,e17)

        # 2024 is a development benchmark, not a pristine holdout anymore.
        models_hold,names_hold=train_models(
            [t10_15,t15_17,t17_19],selected_spec
        )
        hold_raw=predict_transition(
            e19n,t19n_24["target"],models_hold,names_hold,selected_spec
        )
        holdout_share_only=evaluate_rows(hold_raw,e24,e19n)
        hold_pre_route,hold_dispersion,hold_contest_scores=apply_party_calibration(
            hold_raw,e19n,t19n_24["target"],
            [e10,e15,e17,e19],[t10_15,t15_17,t17_19],
            selected_party_strengths
        )
        holdout_pre_route=evaluate_rows(hold_pre_route,e24,e19n)
        hold_rows,hold_routing=route_incumbent_collapse(
            hold_pre_route,e19n,t19n_24["target"],
            selected_routing["route_strength"],
            selected_routing["unwind_strength"]
        )
        holdout=evaluate_rows(hold_rows,e24,e19n)

        candidate_gate_passed,reasons=approval_gate(
            validation,holdout,validation_base,holdout_base
        )
        reference,v0915_hold_rows,local24=evaluate_v0915_reference(val_rows,hold_rows,e17,e19,e19n,e24)
        error_structure=build_remaining_error_audit(v0915_hold_rows,e24,e19n,hold_rows,local24)
        # v0.9.17 is audit-only. The canonical candidate remains the frozen
        # v0.9.10-equivalent model; the best validated shadow reference is v0.9.15.
        # The 2024 labels below diagnose residual errors but select nothing.
        approved=False
        publication_ready=False

        # Live refit can use 2024 only AFTER the holdout has been scored.
        target_now,poll_meta=calculate_poll_target(DATA/"polls.json")
        models_live,names_live=train_models(
            [t10_15,t15_17,t17_19,t19n_24],selected_spec
        )
        live_raw=predict_transition(
            e24,target_now,models_live,names_live,selected_spec
        )
        live_pre_route,live_dispersion,live_contest_scores=apply_party_calibration(
            live_raw,e24,target_now,
            [e10,e15,e17,e19,e24],
            [t10_15,t15_17,t17_19,t19n_24],
            selected_party_strengths
        )
        live_rows,live_routing=route_incumbent_collapse(
            live_pre_route,e24,target_now,
            selected_routing["route_strength"],
            selected_routing["unwind_strength"]
        )
        live=live_projection(
            e24,target_now,live_rows,live_contest_scores,
            {
                "kind":"party_specific_plus_incumbent_routing",
                "classifier":PARTY_CONTEST_BASE_SPEC,
                "strengths":selected_party_strengths,
                "dispersion":live_dispersion,
                "routing":selected_routing,
                "routing_audit":live_routing,
            }
        )

        model_payload={
            "version":"uk-v0917-error-audit",
            "model_type":"constituency-residual-error-audit-v11",
            "status":"ok",
            "approved":approved,
            "publication_ready":publication_ready,
            "diagnostic_only":True,
            "used_for_parameter_selection":False,
            "changes_production_model":False,
            "changes_candidate_model":False,
            "shadow_only":True,
            "candidate_gate_passed":candidate_gate_passed,
            "promotion_blocked_reason":"v0.9.17 is audit-only; 2024 outcomes diagnose the residual errors of the frozen v0.9.15 reference and cannot select or promote a rule",
            "canonical_candidate":"frozen_v0910_equivalent",
            "best_shadow_reference":{
                "version":"v0.9.15",
                "output":"data/v0915-reference-v0917.json",
                "parameters":reference["reference_parameters"],
                "validation_2019":reference["validation_2019"],
                "benchmark_2024":reference["benchmark_2024"],
                "uses_2024_for_parameter_selection":False,
            },
            "remaining_error_audit":{
                "output":"data/error-audit-v0917.json",
                "correct_seats":error_structure["totals"]["correct"],
                "wrong_seats":error_structure["totals"]["wrong"],
                "minimum_net_recoveries_for_80pct":error_structure["totals"]["minimum_net_recoveries_for_80pct"],
                "largest_error_pair":error_structure["largest_error_pair"],
                "priority_families_min5":error_structure["priority_families_min5"],
            },
            "generated_at":utcnow().isoformat(),
            "selected_spec":selected_spec,
            "selected_party_strengths":selected_party_strengths,
            "party_contest_classifier":PARTY_CONTEST_BASE_SPEC,
            "selected_incumbent_routing":selected_routing,
            "incumbent_routing_development":routing_tuning,
            "scenario_activation":{
                "turnover_low":SCENARIO_TURNOVER_LOW,
                "turnover_high":SCENARIO_TURNOVER_HIGH,
                "own_change_full":SCENARIO_OWN_CHANGE_FULL,
                "con_drop_full":SCENARIO_CON_DROP_FULL,
                "ref_rise_full":SCENARIO_REF_RISE_FULL,
                "development_2017":national_scenario_metrics(e15,t15_17["target"]),
                "validation_2019":national_scenario_metrics(e17,t17_19["target"]),
                "benchmark_2024":national_scenario_metrics(e19n,t19n_24["target"]),
                "live":national_scenario_metrics(e24,target_now),
            },
            "evaluation_status":{
                "development_2017":"parameter_selection",
                "validation_2019":"temporal_validation",
                "benchmark_2024":"development_benchmark_not_pristine_holdout",
                "publication_ready_requires_fresh_external_validation":True
            },
            "hard_gate":{
                "min_holdout_accuracy":.80,
                "min_holdout_gain_pp":5.0,
                "max_holdout_seat_abs_error":200,
                "max_validation_accuracy_loss_pp":1.0,
                "max_validation_seat_error_increase":30,
            },
            "gate_failures":reasons,
            "development_2017":{
                "candidate":development_2017,
                "dispersion":dev_dispersion,
                "party_strength_tuning":party_strength_tuning,
                "routing_tuning":routing_tuning,
                "scotland":country_accuracy(dev_routed,e17,e15,"Scotland")
            },
            "validation_2019":{
                "baseline":validation_base,
                "share_only_candidate":validation_share_only,
                "pre_routing_candidate":validation_pre_route,
                "candidate":validation,
                "dispersion":val_dispersion,
                "routing":val_routing,
                "scotland":country_accuracy(val_rows,e19,e17,"Scotland")
            },
            "holdout_2024":{
                "evaluation_label":"development_benchmark_not_pristine_holdout",
                "baseline":holdout_base,
                "share_only_candidate":holdout_share_only,
                "pre_routing_candidate":holdout_pre_route,
                "candidate":holdout,
                "dispersion":hold_dispersion,
                "routing":hold_routing,
                "scotland":country_accuracy(hold_rows,e24,e19n,"Scotland"),
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
            "party_calibration_2017":{
                "classifier":PARTY_CONTEST_BASE_SPEC,
                "selected_strengths":selected_party_strengths,
                "tuning":party_strength_tuning,
                "dispersion":dev_dispersion
            },
            "features":{
                "historical_demographics":[c.replace("demo_","") for c in e19["demo_columns"]],
                "current_demographics":[c.replace("demo_","") for c in e24["demo_columns"]],
                "notes":"v0.9.17 keeps the canonical candidate identical to v0.9.10 and freezes the best shadow reference at the pre-2024-selected v0.9.15 local-election signal. The 2024 labels are used only to audit its 131 residual errors; no new parameters are selected.",
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
                "v0.9.17 keeps the canonical candidate frozen at the v0.9.10-equivalent model and reproduces the v0.9.15 local-strength reference exactly. "
                "The 2024 benchmark is used only to audit the 131 residual constituency errors and to nominate future hypotheses; it selects nothing for live use."
            )
        }
        MODEL_OUT.write_text(json.dumps(model_payload,ensure_ascii=False,indent=2),encoding="utf-8")

        live_payload={
            "version":"uk-v0917-error-audit-live",
            "model_type":"constituency-residual-error-audit-v11",
            "status":"ok",
            "approved":approved,
            "publication_ready":publication_ready,
            "diagnostic_only":True,
            "used_for_parameter_selection":False,
            "changes_production_model":False,
            "changes_candidate_model":False,
            "shadow_only":True,
            "candidate_gate_passed":candidate_gate_passed,
            "best_shadow_reference":{
                "version":"v0.9.15",
                "output":"data/v0915-reference-v0917.json",
                "parameters":reference["reference_parameters"],
                "benchmark_2024":reference["benchmark_2024"],
                "uses_2024_for_parameter_selection":False,
            },
            "remaining_error_audit":{
                "output":"data/error-audit-v0917.json",
                "wrong_seats":error_structure["totals"]["wrong"],
                "minimum_net_recoveries_for_80pct":error_structure["totals"]["minimum_net_recoveries_for_80pct"],
            },
            "generated_at":utcnow().isoformat(),
            "model_version":model_payload["version"],
            "selected_spec":selected_spec,
            "selected_party_strengths":selected_party_strengths,
            "party_contest_classifier":PARTY_CONTEST_BASE_SPEC,
            "selected_incumbent_routing":selected_routing,
            "live_routing_audit":live_routing,
            "scenario":national_scenario_metrics(e24,target_now),
            "effective_party_strengths":{
                p:selected_party_strengths.get(p,0.0)*party_scenario_activation(
                    e24,target_now,p,national_scenario_metrics(e24,target_now)
                )
                for p in PARTIES
            },
            "development_benchmark_2024_accuracy":holdout["winner_accuracy"],
            "target_gb":target_now,
            "poll_meta":poll_meta,
            "holdout_accuracy":holdout["winner_accuracy"],
            "holdout_seat_abs_error":holdout["seat_abs_error_sum"],
            **live,
        }
        LIVE_OUT.write_text(json.dumps(live_payload,ensure_ascii=False,indent=2),encoding="utf-8")

        backtest_payload={
            "version":"uk-v0917-error-audit-backtest",
            "status":"ok",
            "diagnostic_only":True,
            "used_for_parameter_selection":False,
            "shadow_only":True,
            "changes_production_model":False,
            "changes_candidate_model":False,
            "best_shadow_reference":{
                "version":"v0.9.15",
                "output":"data/v0915-reference-v0917.json",
                "parameters":reference["reference_parameters"],
                "validation_2019":reference["validation_2019"],
                "benchmark_2024":reference["benchmark_2024"],
                "uses_2024_for_parameter_selection":False,
            },
            "remaining_error_audit":{
                "output":"data/error-audit-v0917.json",
                "correct_seats":error_structure["totals"]["correct"],
                "wrong_seats":error_structure["totals"]["wrong"],
                "largest_error_pair":error_structure["largest_error_pair"],
                "priority_families_min5":error_structure["priority_families_min5"],
            },
            "selected_spec":selected_spec,
            "selected_party_strengths":selected_party_strengths,
            "party_contest_classifier":PARTY_CONTEST_BASE_SPEC,
            "selected_incumbent_routing":selected_routing,
            "approved_for_live":False,
            "candidate_gate_passed":candidate_gate_passed,
            "publication_ready":publication_ready,
            "development_2017":model_payload["development_2017"],
            "validation_2019":{"baseline":validation_base,"share_only_candidate":validation_share_only,"pre_routing_candidate":validation_pre_route,"candidate":validation,"dispersion":val_dispersion,"routing":val_routing,"scotland":country_accuracy(val_rows,e19,e17,"Scotland")},
            "holdout_2024":{"evaluation_label":"development_benchmark_not_pristine_holdout","baseline":holdout_base,"share_only_candidate":holdout_share_only,"pre_routing_candidate":holdout_pre_route,"candidate":holdout,"dispersion":hold_dispersion,"routing":hold_routing,"scotland":country_accuracy(hold_rows,e24,e19n,"Scotland")},
            "internal_selection_2017":model_payload["internal_selection_2017"],
            "party_calibration_2017":model_payload["party_calibration_2017"],
        }
        BACKTEST_OUT.write_text(json.dumps(backtest_payload,ensure_ascii=False,indent=2),encoding="utf-8")
        DIAGNOSTIC_OUT.write_text(
            json.dumps(error_structure,ensure_ascii=False,indent=2),
            encoding="utf-8"
        )
        SWEEP_OUT.write_text(
            json.dumps(reference,ensure_ascii=False,indent=2),
            encoding="utf-8"
        )

        print("v0.9.17 selected share spec:",selected_spec)
        print("v0.9.15 reference 2019 regression:",reference["validation_2019"])
        print("v0.9.15 reference 2024 benchmark:",reference["benchmark_2024"])
        print("v0.9.17 remaining errors:",error_structure["totals"])
        print("v0.9.17 largest remaining error pair:",error_structure["largest_error_pair"])
        print("v0.9.17 local-strength impact vs v0.9.10:",error_structure["local_strength_impact_vs_v0910"])
        print("v0.9.17 priority families >=5:",error_structure["priority_families_min5"][:20])
        print("v0.9.17 selected party strengths:",selected_party_strengths)
        print("v0.9.17 incumbent routing:",selected_routing)
        print("2017 routing audit:",routing_tuning["selected_audit"])
        print("2017 scenario:",national_scenario_metrics(e15,t15_17["target"]))
        print("2019 scenario:",national_scenario_metrics(e17,t17_19["target"]))
        print("2024 scenario:",national_scenario_metrics(e19n,t19n_24["target"]))
        print(
            "2019 validation:",
            f"baseline {validation_base['winner_accuracy']:.2%}/{validation_base['seat_abs_error_sum']}",
            f"share-only {validation_share_only['winner_accuracy']:.2%}/{validation_share_only['seat_abs_error_sum']}",
            f"pre-route {validation_pre_route['winner_accuracy']:.2%}/{validation_pre_route['seat_abs_error_sum']}",
            f"routed {validation['winner_accuracy']:.2%}/{validation['seat_abs_error_sum']}"
        )
        print(
            "2024 DEVELOPMENT BENCHMARK:",
            f"baseline {holdout_base['winner_accuracy']:.2%}/{holdout_base['seat_abs_error_sum']}",
            f"share-only {holdout_share_only['winner_accuracy']:.2%}/{holdout_share_only['seat_abs_error_sum']}",
            f"pre-route {holdout_pre_route['winner_accuracy']:.2%}/{holdout_pre_route['seat_abs_error_sum']}",
            f"routed {holdout['winner_accuracy']:.2%}/{holdout['seat_abs_error_sum']}"
        )
        print("Underlying candidate gate passed:",candidate_gate_passed,reasons)
        print("Shadow build approved for live:",approved)
        print("v0.9.15 reference 2024 wrong seats:",error_structure["totals"]["wrong"])
        print("Publication-ready (requires a future version and fresh validation):",publication_ready)
        print("Live central GB seat totals:",live["totals"])
    return 0

if __name__=="__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"build_mrp_lite.py v0.9.17 diagnostic build failed: {exc}",file=sys.stderr)
        write_failure(exc)
        # A broken research build must not be deployed. The previously deployed
        # production/fallback remains untouched because this workflow stops before
        # the commit and Pages deployment steps.
        raise SystemExit(1)
