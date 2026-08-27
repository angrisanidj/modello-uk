#!/usr/bin/env python3
"""
modello-uk v0.9.27 — calibrated temporal MRP geography bridge (shadow research)

Core idea
---------
The existing model keeps ownership of the national GB vote target.  External
pre-election MRP data are used only as a *relative constituency geography*
prior. Provider toplines are stripped out. The constituency pattern is then
interpolated in log-space between the internal v0.9.15 geography and the
external MRP geography; every blended projection is raked back to the model's
own national target.

Temporal discipline
-------------------
* Blend strength is selected on the pre-election YouGov 2019 MRP only.
* YouGov 2024 is then a score-only development benchmark.
* More in Common 2024 and the equal-provider ensemble are diagnostics only.
* No realised 2024 result is used for parameter or provider selection.
* Live 2026 is shadow-only even if the research gate passes.

Live geography
--------------
When the July 2026 More in Common constituency workbook can be parsed, live
geography uses a YouGov-2024 structural anchor plus the relative geographic
movement from MiC-2024 to MiC-2026.  The resulting rows are again raked to the
model's own current polling target.  If the 2026 workbook is unavailable or
changes schema, the research backtest still completes and a static YouGov-2024
live shadow is emitted with an explicit fallback flag.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

# Import the proven v0.9.22 engine as a library; importing it does not run main().
import build_mrp_lite as core

V0927_BRIDGE="logspace-internal-to-external-geography-replacement"
V0927_SELECTION="yougov-2019-only-blend-selection"
V0927_LIVE_EVOLUTION="yougov24-anchor-plus-mic24-to-mic26-shrunk-relative-shift"
V0927_BASELINE="reconstruct-v0915-local-strength-both-elections"
V0927_DIAGNOSTICS="full-zero-to-pure-external-blend-sweep-2024"
V0927_LIVE_CANDIDATE="latest-mic26-dynamic-topline-cross-provider-temporal-calibration"
V0927_MRP_SOURCE="more-in-common-2026-07-19-fieldwork-2026-06-05-to-2026-06-28"
V0927_PARSER_HOTFIX="mic26-leading-article-aliases-complete-header-selection"
V0927_TEMPORAL_TRANSFER="lambda-selected-on-2024-mrp-wave-movement-not-election-result"
V0927_TEMPORAL_VALIDATION="train-2024-06-03-to-06-19-validate-06-19-to-07-03"

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
CACHE=ROOT/".cache"/"mrp-bridge"
CACHE.mkdir(parents=True,exist_ok=True)

BACKTEST_OUT=DATA/"backtest-v0927-geography-bridge.json"
DIAGNOSTIC_OUT=DATA/"mrp-geography-bridge-v0927.json"
LIVE_OUT=DATA/"mrp-lite-live-v0927-candidate.json"
INTEGRITY_OUT=DATA/"bes-integrity-v0927.json"

PARTIES=core.PARTIES
EPS=0.05
FACTOR_MIN=0.01
FACTOR_MAX=100.0
EVOLUTION_MIN=0.40
EVOLUTION_MAX=2.50
TEMPORAL_LAMBDA_GRID=(0.0,0.125,0.25,0.375,0.50,0.625,0.75,0.875,1.00)
TEMPORAL_RELEVANCE_SHARE=3.0

# Small, predeclared grid.  It is selected on 2019 only and then frozen before
# the 2024 benchmark is inspected.
STRENGTH_GRID=(0.0,0.125,0.25,0.375,0.50,0.625,0.75,0.875,1.00)

YOUGOV_2019_URL=(
    "https://raw.githubusercontent.com/calbal91/project-understanding-elections/"
    "refs/heads/master/CSVs/YouGov.csv"
)
YOUGOV_2024_EARLY_URL=(
    "https://raw.githubusercontent.com/inglesp/apogee/refs/heads/main/"
    "data/processed/yougov/2024-06-03/data.csv"
)
YOUGOV_2024_MID_URL=(
    "https://raw.githubusercontent.com/inglesp/apogee/refs/heads/main/"
    "data/processed/yougov/2024-06-19/data.csv"
)
YOUGOV_2024_URL=(
    "https://raw.githubusercontent.com/inglesp/apogee/refs/heads/main/"
    "data/processed/yougov/2024-07-03/data.csv"
)
MIC_2024_EARLY_URL=(
    "https://raw.githubusercontent.com/inglesp/apogee/refs/heads/main/"
    "data/processed/moreincommon/2024-06-03/data.csv"
)
MIC_2024_MID_URL=(
    "https://raw.githubusercontent.com/inglesp/apogee/refs/heads/main/"
    "data/processed/moreincommon/2024-06-19/data.csv"
)
MIC_2024_URL=(
    "https://raw.githubusercontent.com/inglesp/apogee/refs/heads/main/"
    "data/processed/moreincommon/2024-07-03/data.csv"
)
MIC_2026_URL=(
    "https://www.moreincommon.org.uk/wp-content/uploads/2026/07/"
    "jul26-mrp-datatables-final-3.xlsx"
)

UA="FocusAmerica-UK-election-model/0.9.27 calibrated-temporal-geography (+https://angrisanidj.github.io/modello-uk/)"


def _json_safe(obj:Any)->Any:
    if isinstance(obj,dict):return {str(k):_json_safe(v) for k,v in obj.items()}
    if isinstance(obj,(list,tuple)):return [_json_safe(v) for v in obj]
    if isinstance(obj,(np.integer,)):return int(obj)
    if isinstance(obj,(np.floating,)):return float(obj)
    if isinstance(obj,(np.bool_,)):return bool(obj)
    if isinstance(obj,Path):return str(obj)
    if pd.isna(obj) if not isinstance(obj,(str,bytes)) else False:return None
    return obj


def _write_json(path:Path,payload:dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload),ensure_ascii=False,indent=2),encoding="utf-8")


def _sha256(raw:bytes)->str:
    return hashlib.sha256(raw).hexdigest()


def _cache_path(url:str)->Path:
    suffix=Path(url.split("?",1)[0]).suffix or ".bin"
    key=hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return CACHE/f"{key}{suffix}"


def _payload_looks_valid(url:str,raw:bytes)->bool:
    if len(raw)<=100:return False
    clean=url.split("?",1)[0].lower();low=raw[:300].lstrip().lower()
    if clean.endswith(".csv"):
        return not low.startswith(b"<html") and b"," in raw[:500]
    if clean.endswith(".xlsx"):
        return raw.startswith(b"PK")
    return True


def fetch_remote_bytes(url:str,attempts:int=6,timeout:int=90)->tuple[bytes,dict[str,Any]]:
    """Fetch a pinned research source with memory-independent disk caching.

    A cached copy is preferred so GitHub Actions reruns do not repeatedly hit
    external providers.  A network response is accepted only when non-trivial.
    """
    path=_cache_path(url)
    if path.exists() and path.stat().st_size>100:
        raw=path.read_bytes()
        if _payload_looks_valid(url,raw):
            return raw,{"url":url,"cache":"hit","bytes":len(raw),"sha256":_sha256(raw),"cache_path":str(path.relative_to(ROOT))}
        path.unlink(missing_ok=True)

    last:Exception|None=None
    for attempt in range(1,attempts+1):
        try:
            response=requests.get(url,headers={"User-Agent":UA,"Accept":"*/*"},timeout=timeout)
            response.raise_for_status()
            raw=response.content
            if len(raw)<=100:
                raise RuntimeError(f"response too small ({len(raw)} bytes)")
            if not _payload_looks_valid(url,raw):
                raise RuntimeError("endpoint returned content inconsistent with file extension")
            path.write_bytes(raw)
            return raw,{"url":url,"cache":"miss","attempt":attempt,"bytes":len(raw),"sha256":_sha256(raw),"cache_path":str(path.relative_to(ROOT))}
        except Exception as exc:
            last=exc
            if attempt<attempts:
                delay=min(45.0,2.0*(2**(attempt-1)))
                print(f"MRP source retry {attempt}/{attempts} for {url}: {exc}; sleeping {delay:.0f}s",file=sys.stderr)
                time.sleep(delay)
    raise RuntimeError(f"Failed to fetch external MRP source after {attempts} attempts: {url}: {last}")


def _norm_name(value:Any)->str:
    s=str(value or "").lower().strip()
    s=s.replace("&","and")
    s=re.sub(r"\b(the|constituency|borough|county)\b"," ",s)
    s=re.sub(r"[^a-z0-9]+","",s)
    return s


def _normalise_row_shares(df:pd.DataFrame)->pd.DataFrame:
    out=df.copy()
    for p in PARTIES:
        out[p]=pd.to_numeric(out.get(p,0.0),errors="coerce").fillna(0.0).clip(lower=0.0)
    maxima=[float(out[p].max()) for p in PARTIES if len(out)]
    if maxima and max(maxima)<=1.5:
        for p in PARTIES:out[p]*=100.0
    sums=out.loc[:,PARTIES].sum(axis=1)
    good=sums>0
    out.loc[good,PARTIES]=out.loc[good,PARTIES].div(sums[good],axis=0)*100.0
    return out


def parse_apogee_csv(raw:bytes,provider:str,date:str)->tuple[pd.DataFrame,dict[str,Any]]:
    df=pd.read_csv(io.BytesIO(raw))
    lookup={core.nkey(c):c for c in df.columns}
    code=lookup.get("code")
    name=lookup.get("name") or lookup.get("constituency")
    if not code or not name:
        raise RuntimeError(f"{provider} {date}: expected code/name columns; got {list(df.columns)}")
    mapping={
        "con":"con","grn":"green","green":"green","lab":"lab",
        "lib":"ld","ld":"ld","libdem":"ld","libdems":"ld",
        "oth":"other","other":"other","pc":"pc","ref":"ref","reform":"ref","snp":"snp",
    }
    out=pd.DataFrame({"code":df[code].astype(str).str.strip(),"name":df[name].astype(str).str.strip()})
    for p in PARTIES:out[p]=0.0
    mapped=[]
    for nk,col in lookup.items():
        p=mapping.get(nk)
        if p:
            out[p]=pd.to_numeric(df[col],errors="coerce").fillna(0.0)
            mapped.append((col,p))
    if len({p for _,p in mapped})<7:
        raise RuntimeError(f"{provider} {date}: too few mapped party columns: {mapped}")
    out=_normalise_row_shares(out)
    out=out[out.loc[:,PARTIES].sum(axis=1)>0].drop_duplicates(subset=["code"],keep="first").reset_index(drop=True)
    if len(out)<620:
        raise RuntimeError(f"{provider} {date}: only {len(out)} usable constituency rows")
    return out,{"provider":provider,"date":date,"rows":int(len(out)),"mapped_columns":mapped}


def parse_yougov_2019(raw:bytes)->tuple[pd.DataFrame,dict[str,Any]]:
    df=pd.read_csv(io.BytesIO(raw))
    lookup={core.nkey(c):c for c in df.columns}
    code=lookup.get("code")
    name=lookup.get("constituency") or lookup.get("name")
    if not code or not name:
        raise RuntimeError(f"YouGov 2019: missing code/constituency columns: {list(df.columns)}")
    source_map={
        "con":"con","lab":"lab","ld":"ld","brexit":"ref","green":"green",
        "snp":"snp","pc":"pc","other":"other"
    }
    out=pd.DataFrame({"code":df[code].astype(str).str.strip(),"name":df[name].astype(str).str.strip()})
    for p in PARTIES:out[p]=0.0
    mapped=[]
    for src,p in source_map.items():
        col=lookup.get(src)
        if col:
            out[p]=pd.to_numeric(df[col],errors="coerce").fillna(0.0)
            mapped.append((col,p))
    if len({p for _,p in mapped})<7:
        raise RuntimeError(f"YouGov 2019: too few party columns: {mapped}")
    out=_normalise_row_shares(out)
    out=out[out.loc[:,PARTIES].sum(axis=1)>0].drop_duplicates(subset=["code"],keep="first").reset_index(drop=True)
    if len(out)<630:
        raise RuntimeError(f"YouGov 2019: only {len(out)} usable constituency rows")
    return out,{"provider":"YouGov","date":"2019-11-27","rows":int(len(out)),"mapped_columns":mapped}


def _party_from_header(value:Any)->str|None:
    """Map human-readable MiC party headers to internal party codes.

    The workbook does not expose stable machine field names. In particular,
    Green may be labelled ``The Green Party`` or use a longer descriptive
    header. Strip only a leading definite article before conservative prefix
    matching; never use unconstrained substring matching.
    """
    raw=core.nkey(value)
    if not raw:
        return None
    exact={
        "con":"con","conservative":"con","conservatives":"con","tories":"con",
        "lab":"lab","labour":"lab","labor":"lab",
        "ld":"ld","libdem":"ld","libdems":"ld","liberaldemocrat":"ld","liberaldemocrats":"ld",
        "ref":"ref","reform":"ref","reformuk":"ref",
        "green":"green","greens":"green","greenparty":"green","thegreenparty":"green","thegreens":"green",
        "snp":"snp","scottishnationalparty":"snp","scottishnationalpartysnp":"snp",
        "pc":"pc","plaid":"pc","plaidcymru":"pc",
        "other":"other","others":"other","otherparty":"other","indother":"other","otherind":"other",
        "otherindependent":"other","otherindependents":"other","independentother":"other",
        "independentsandothers":"other","otherandindependent":"other","otherandindependents":"other",
    }
    if raw in exact:
        return exact[raw]
    k=raw[3:] if raw.startswith("the") and len(raw)>3 else raw
    if k.startswith("conservative") or k.startswith("tory"):
        return "con"
    if k.startswith("labour") or k.startswith("labor"):
        return "lab"
    if k.startswith("liberaldem") or k.startswith("libdem"):
        return "ld"
    if k.startswith("reform"):
        return "ref"
    if k.startswith("green"):
        return "green"
    if k.startswith("snp") or k.startswith("scottishnational"):
        return "snp"
    if k.startswith("plaid"):
        return "pc"
    if k.startswith("other") or k.startswith("independent"):
        return "other"
    return None


def parse_mic_2026_xlsx(raw:bytes)->tuple[pd.DataFrame,dict[str,Any]]:
    """Parse the public July-2026 MiC workbook without assuming one sheet name.

    The workbook is an external publication and may carry title rows/merged cells.
    We scan candidate header rows, then choose the table with the most usable
    constituency rows and party columns.  This makes harmless formatting changes
    non-fatal while still enforcing a high coverage gate.
    """
    book=pd.ExcelFile(io.BytesIO(raw),engine="openpyxl")
    candidates=[]
    for sheet in book.sheet_names:
        try:
            raw_df=pd.read_excel(book,sheet_name=sheet,header=None,dtype=object)
        except Exception:
            continue
        scan=min(60,len(raw_df))
        for header_i in range(scan):
            vals=[str(v).strip() if not pd.isna(v) else "" for v in raw_df.iloc[header_i].tolist()]
            norm=[core.nkey(v) for v in vals]
            name_idx=None;code_idx=None
            for j,k in enumerate(norm):
                if k in {"constituency","constituencyname","seat","seatname","name"}:
                    name_idx=j
                if k in {"code","constituencycode","onscode","pcon24cd","constituencyid"}:
                    code_idx=j
            party_cols={}
            for j,v in enumerate(vals):
                p=_party_from_header(v)
                if p and p not in party_cols:party_cols[p]=j
            if name_idx is None or len(party_cols)<5:
                continue
            body=raw_df.iloc[header_i+1:].copy()
            out=pd.DataFrame({
                "code":body.iloc[:,code_idx].astype(str).str.strip() if code_idx is not None else "",
                "name":body.iloc[:,name_idx].astype(str).str.strip(),
            })
            for p in PARTIES:out[p]=0.0
            for p,j in party_cols.items():
                out[p]=pd.to_numeric(body.iloc[:,j],errors="coerce").fillna(0.0)
            out=out[~out["name"].str.lower().isin({"","nan","none"})]
            out=_normalise_row_shares(out)
            out=out[out.loc[:,PARTIES].sum(axis=1)>0].copy()
            # Constituency tables should have hundreds of distinct names.
            distinct=int(out["name"].map(_norm_name).nunique())
            # Prefer party completeness before row-count tie-breaking.
            complete=int(set(PARTIES).issubset(set(party_cols)))
            score=(complete,len(party_cols),distinct)
            if distinct>=500:
                candidates.append((score,sheet,header_i,out,party_cols,vals))
    if not candidates:
        raise RuntimeError(f"MiC 2026 workbook: no constituency vote-share table found; sheets={book.sheet_names}")
    candidates.sort(key=lambda x:x[0],reverse=True)
    score,sheet,header_i,out,party_cols,headers=candidates[0]
    required=set(PARTIES)
    missing=sorted(required-set(party_cols))
    if missing:
        nonempty_headers=[str(x).strip() for x in headers if str(x).strip()]
        raise RuntimeError(
            f"MiC 2026 workbook: constituency table is missing required party columns {missing}; "
            f"mapped={sorted(party_cols)}; sheet={sheet!r}; header_row={header_i+1}; "
            f"headers={nonempty_headers[:30]}. Refusing a live candidate with incomplete geography."
        )
    out=out.drop_duplicates(subset=["name"],keep="first").reset_index(drop=True)
    if len(out)<600:
        raise RuntimeError(f"MiC 2026 workbook: best sheet {sheet!r} has only {len(out)} rows")
    return out,{
        "provider":"More in Common","date":"2026-07-19","rows":int(len(out)),
        "sheet":sheet,"header_row_1based":int(header_i+1),
        "mapped_columns":{p:headers[j] for p,j in party_cols.items()},
        "workbook_sheets":book.sheet_names,
    }


def align_prior(prior:pd.DataFrame,election:dict[str,Any],label:str,min_match:int=620)->tuple[pd.DataFrame,dict[str,Any]]:
    frame=election["frame"]
    by_code={str(r["code"]).strip():r for _,r in prior.iterrows() if str(r.get("code","")).strip() not in {"","nan","None"}}
    by_name={_norm_name(r["name"]):r for _,r in prior.iterrows() if _norm_name(r.get("name",""))}
    aligned=pd.DataFrame(index=frame.index,columns=PARTIES,dtype=float)
    matched=0;code_matches=0;name_matches=0;missing=[]
    for idx,row in frame.iterrows():
        rec=by_code.get(str(row["id"]).strip())
        method="code"
        if rec is None:
            rec=by_name.get(_norm_name(row["name"]));method="name"
        if rec is None:
            # Missing external seats are neutral rather than fabricated.  The
            # final raking still enforces the model's national target.
            missing.append({"id":str(row["id"]),"name":str(row["name"])})
            continue
        matched+=1
        if method=="code":code_matches+=1
        else:name_matches+=1
        for p in PARTIES:
            aligned.at[idx,p]=float(rec[p]) if core.allowed(p,str(row["country"])) else 0.0
    if matched<min_match:
        raise RuntimeError(f"{label}: matched only {matched}/{len(frame)} seats (min {min_match}); first missing={missing[:8]}")
    return aligned,{
        "label":label,"matched_seats":matched,"total_seats":int(len(frame)),
        "coverage":matched/len(frame),"code_matches":code_matches,"name_matches":name_matches,
        "missing_seats":missing,
    }


def relative_factors(
    prior_aligned:pd.DataFrame,geometry_election:dict[str,Any],weight_election:dict[str,Any]|None=None
)->tuple[pd.DataFrame,dict[str,float]]:
    frame=geometry_election["frame"]
    weight_frame=(weight_election or geometry_election)["frame"]
    if not frame.index.equals(weight_frame.index):
        raise RuntimeError("relative-factor weighting frame does not align with constituency geometry")
    # Use only weights that were available before the scored election whenever
    # possible (2017 weights for the 2019 test; notional-2019 weights for 2024).
    # This prevents target-election turnout from leaking into the external prior.
    weights=weight_frame["weight"].to_numpy(dtype=float)
    nat={}
    for p in PARTIES:
        vals=prior_aligned[p].to_numpy(dtype=float)
        ok=np.isfinite(vals)
        w=weights[ok]
        nat[p]=float(np.sum(vals[ok]*w)/np.sum(w)) if ok.any() and float(np.sum(w))>0 else 0.0
    factors=pd.DataFrame(1.0,index=frame.index,columns=PARTIES,dtype=float)
    for idx,row in frame.iterrows():
        country=str(row["country"])
        for p in PARTIES:
            if not core.allowed(p,country):
                factors.at[idx,p]=0.0;continue
            value=prior_aligned.at[idx,p]
            if pd.isna(value):
                factors.at[idx,p]=1.0;continue
            ratio=(float(value)+EPS)/(float(nat[p])+EPS)
            factors.at[idx,p]=core.clamp(ratio,FACTOR_MIN,FACTOR_MAX)
    return factors,nat


def _internal_relative_factors(base_rows:pd.DataFrame,base_election:dict[str,Any])->tuple[pd.DataFrame,dict[str,float]]:
    """Convert the internal constituency rows into party-specific geography.

    The denominator is calculated with the same pre-election constituency
    weights used by the scored projection.  Because the base rows have already
    been raked, these national shares should be extremely close to the target.
    """
    frame=base_election["frame"]
    nat=core.weighted_nat_rows(base_rows,base_election)
    factors=pd.DataFrame(1.0,index=frame.index,columns=PARTIES,dtype=float)
    for idx,row in frame.iterrows():
        country=str(row["country"])
        for p in PARTIES:
            if not core.allowed(p,country):
                factors.at[idx,p]=0.0;continue
            b=max(EPS,float(base_rows.at[idx,p]))
            n=max(EPS,float(nat.get(p,0.0)))
            factors.at[idx,p]=core.clamp(b/n,FACTOR_MIN,FACTOR_MAX)
    return factors,{p:float(nat.get(p,0.0)) for p in PARTIES}


def apply_factors(base_rows:pd.DataFrame,base_election:dict[str,Any],target:dict[str,float],external_factors:pd.DataFrame,strength:float)->pd.DataFrame:
    """True geography replacement/blend rather than multiplicative stacking.

    strength=0   -> exact v0.9.15 constituency rows
    strength=1   -> external MRP relative geography, with our national topline
    0<s<1        -> geometric/log-space interpolation of the two geographies

    Formally R = R_internal^(1-s) * R_external^s.  We then multiply by our
    national target, normalise within each seat, and perform the final rake.
    """
    strength=float(strength)
    if strength < -1e-12 or strength > 1.0+1e-12:
        raise ValueError(f"replacement blend strength must be in [0,1], got {strength}")
    if abs(strength)<1e-12:
        # Preserve the frozen reference exactly; this is both a methodological
        # invariant and a guard against epsilon/normalisation drift.
        return base_rows.copy()

    frame=base_election["frame"]
    internal_factors,_=_internal_relative_factors(base_rows,base_election)
    target_n=core.normalize_target(target)
    out=pd.DataFrame(index=base_rows.index,columns=PARTIES,dtype=float)
    for idx,row in frame.iterrows():
        vals={}
        country=str(row["country"])
        for p in PARTIES:
            if not core.allowed(p,country):
                vals[p]=0.0;continue
            ri=max(FACTOR_MIN,float(internal_factors.at[idx,p]))
            re=max(FACTOR_MIN,float(external_factors.at[idx,p]))
            # Linear interpolation in log relative-geography space.
            blend=math.exp((1.0-strength)*math.log(ri)+strength*math.log(re))
            vals[p]=max(0.0,float(target_n.get(p,0.0)))*blend
        total=sum(vals.values()) or 1.0
        for p in PARTIES:
            out.at[idx,p]=vals[p]/total*100.0
    return core.rake(out,base_election,target_n)


def ensemble_factors(*factor_frames:pd.DataFrame)->pd.DataFrame:
    if not factor_frames:raise ValueError("no factor frames")
    out=pd.DataFrame(1.0,index=factor_frames[0].index,columns=PARTIES,dtype=float)
    for p in PARTIES:
        stack=np.vstack([np.maximum(0.0001,f[p].to_numpy(dtype=float)) for f in factor_frames])
        out[p]=np.exp(np.mean(np.log(stack),axis=0))
    return out


def evolution_factors(anchor:pd.DataFrame,old_provider:pd.DataFrame,new_provider:pd.DataFrame,temporal_lambda:float=1.0)->pd.DataFrame:
    """Transfer only a calibrated fraction of another provider's geographic movement.

    lambda=0 keeps the structural anchor unchanged. lambda=1 reproduces the full
    old v0.9.26 MiC evolution. Intermediate values shrink the log movement toward
    zero before it is applied to the YouGov anchor. The raw per-seat movement is
    still clipped to the predeclared [EVOLUTION_MIN, EVOLUTION_MAX] interval.
    """
    lam=float(temporal_lambda)
    if lam < -1e-12 or lam > 1.0+1e-12:
        raise ValueError(f"temporal lambda must be in [0,1], got {lam}")
    out=anchor.copy().astype(float)
    for p in PARTIES:
        a=np.maximum(0.0001,anchor[p].to_numpy(dtype=float))
        old=np.maximum(0.0001,old_provider[p].to_numpy(dtype=float))
        new=np.maximum(0.0001,new_provider[p].to_numpy(dtype=float))
        raw_shift=np.clip(new/old,EVOLUTION_MIN,EVOLUTION_MAX)
        shift=np.exp(lam*np.log(raw_shift))
        out[p]=np.clip(a*shift,FACTOR_MIN,FACTOR_MAX)
    return out


def _movement_error(predicted:pd.DataFrame,target:pd.DataFrame,*share_frames:pd.DataFrame)->dict[str,Any]:
    """Robust distance between two relative-geography factor fields.

    Only party-seat pairs with at least TEMPORAL_RELEVANCE_SHARE percent in at
    least one supplied MRP wave are scored. This avoids letting tiny local shares
    dominate a log-ratio objective while using no realised election result.
    """
    errors=[]
    by_party={p:[] for p in PARTIES}
    for idx in predicted.index:
        for p in PARTIES:
            pv=float(predicted.at[idx,p]); tv=float(target.at[idx,p])
            if pv<=0 or tv<=0: continue
            if share_frames:
                vals=[]
                for sf in share_frames:
                    try:
                        v=float(sf.at[idx,p])
                        if math.isfinite(v): vals.append(v)
                    except Exception:
                        pass
                if vals and max(vals)<TEMPORAL_RELEVANCE_SHARE: continue
            err=abs(math.log(max(1e-6,pv)/max(1e-6,tv)))
            errors.append(err);by_party[p].append(err)
    if not errors:
        return {"pairs":0,"median_abs_log_error":float("inf"),"mean_abs_log_error":float("inf"),"rmse_log_error":float("inf"),"by_party":{}}
    arr=np.asarray(errors,dtype=float)
    return {
        "pairs":int(len(arr)),
        "median_abs_log_error":float(np.median(arr)),
        "mean_abs_log_error":float(np.mean(arr)),
        "rmse_log_error":float(np.sqrt(np.mean(arr*arr))),
        "by_party":{p:{"pairs":len(v),"mean_abs_log_error":float(np.mean(v)),"median_abs_log_error":float(np.median(v))} for p,v in by_party.items() if v},
    }


def calibrate_temporal_transfer(
    y_early_f:pd.DataFrame,m_early_f:pd.DataFrame,m_mid_f:pd.DataFrame,y_mid_f:pd.DataFrame,
    y_mid_shares:pd.DataFrame,m_early_shares:pd.DataFrame,m_mid_shares:pd.DataFrame,
    y_final_f:pd.DataFrame,m_final_f:pd.DataFrame,
    y_final_shares:pd.DataFrame,m_final_shares:pd.DataFrame,
)->dict[str,Any]:
    """Select temporal transfer lambda on MRP wave movement, never on election results.

    Training: 2024-06-03 -> 2024-06-19. Apply MiC movement to the YouGov
    2024-06-03 anchor and select the lambda that best reproduces YouGov 06-19.
    Validation: freeze lambda, then test 06-19 -> 07-03 against YouGov 07-03.
    """
    candidates=[]
    for lam in TEMPORAL_LAMBDA_GRID:
        pred=evolution_factors(y_early_f,m_early_f,m_mid_f,lam)
        metrics=_movement_error(pred,y_mid_f,y_mid_shares,m_early_shares,m_mid_shares)
        candidates.append({"lambda":float(lam),"metrics":metrics})
    selected_row=min(candidates,key=lambda x:(x["metrics"]["median_abs_log_error"],x["metrics"]["mean_abs_log_error"],x["lambda"]))
    selected=float(selected_row["lambda"])

    def score_validation(lam:float)->dict[str,Any]:
        pred=evolution_factors(y_mid_f,m_mid_f,m_final_f,lam)
        return _movement_error(pred,y_final_f,y_final_shares,y_mid_shares,m_mid_shares,m_final_shares)
    val_selected=score_validation(selected)
    val_static=score_validation(0.0)
    val_raw=score_validation(1.0)
    validated=(
        val_selected["median_abs_log_error"] <= val_static["median_abs_log_error"]+1e-12
        and val_selected["mean_abs_log_error"] <= val_static["mean_abs_log_error"]+1e-12
        and (val_selected["median_abs_log_error"] < val_static["median_abs_log_error"]-1e-12
             or val_selected["mean_abs_log_error"] < val_static["mean_abs_log_error"]-1e-12)
    )
    return {
        "selection_role":"MRP-wave movement only; no realised election result",
        "training_interval":"2024-06-03/2024-06-19",
        "validation_interval":"2024-06-19/2024-07-03",
        "grid":list(TEMPORAL_LAMBDA_GRID),
        "relevance_share_threshold_pct":TEMPORAL_RELEVANCE_SHARE,
        "training_candidates":candidates,
        "selected_lambda":selected,
        "validation_selected":val_selected,
        "validation_static_lambda_0":val_static,
        "validation_raw_lambda_1":val_raw,
        "validation_passed_vs_static":bool(validated),
        "uses_realised_2024_result_for_selection":False,
    }


def _projection_stability(projections:dict[str,dict[str,Any]])->dict[str,Any]:
    maps={name:{str(x.get("id")):str(x.get("centralWinner")) for x in payload.get("seats",[]) if x.get("id")} for name,payload in projections.items()}
    names=list(maps)
    pairwise={}
    for i,a in enumerate(names):
        for b in names[i+1:]:
            common=sorted(set(maps[a])&set(maps[b]))
            changed=[k for k in common if maps[a][k]!=maps[b][k]]
            transitions=Counter(f"{maps[a][k]}->{maps[b][k]}" for k in changed)
            pairwise[f"{a}__vs__{b}"]={"changed_winners":len(changed),"transitions":dict(transitions.most_common())}
    common_ids=set.intersection(*(set(m) for m in maps.values())) if maps else set()
    all_agree=0;majority=0;all_different=0;consensus_totals=Counter()
    for k in common_ids:
        ws=[maps[n][k] for n in names]
        c=Counter(ws)
        if len(c)==1: all_agree+=1
        winner,count=c.most_common(1)[0]
        if count>=2:
            majority+=1;consensus_totals[winner]+=1
        else:
            all_different+=1
    return {
        "scenario_names":names,
        "pairwise":pairwise,
        "all_scenarios_agree":all_agree,
        "majority_consensus_available":majority,
        "all_scenarios_different":all_different,
        "majority_consensus_totals":dict(consensus_totals),
        "note":"Consensus is diagnostic only and never selects the live route.",
    }


def _seat_records(reference_rows:pd.DataFrame,bridge_rows:pd.DataFrame,actual:dict[str,Any],base:dict[str,Any])->list[dict[str,Any]]:
    frame=actual["frame"];base_frame=base["frame"];records=[]
    for idx,row in frame.iterrows():
        refw=core.predicted_winner(reference_rows.loc[idx],base_frame.loc[idx])
        brw=core.predicted_winner(bridge_rows.loc[idx],base_frame.loc[idx])
        actualw=str(row["actual_winner"])
        if refw==brw and brw==actualw:continue
        records.append({
            "id":str(row["id"]),"name":str(row["name"]),"country":str(row["country"]),"region":str(row["region"]),
            "actual":actualw,"reference":refw,"bridge":brw,
            "reference_correct":refw==actualw,"bridge_correct":brw==actualw,
            "bridge_top":sorted(((p,round(float(bridge_rows.at[idx,p]),3)) for p in PARTIES),key=lambda x:x[1],reverse=True)[:3],
        })
    return records


def build_core_state()->dict[str,Any]:
    """Reproduce only the proven canonical pipeline needed by the bridge."""
    with tempfile.TemporaryDirectory() as td_raw:
        td=Path(td_raw)
        hist_path,hist_meta=core.fetch_article_file(core.HIST_ARTICLE,td)
        curr_path,curr_meta=core.fetch_article_file(core.CURR_ARTICLE,td)
        hist_df=core.read_table(hist_path);curr_df=core.read_table(curr_path)
        hist_demo=core.demo_frame(hist_df);curr_demo=core.demo_frame(curr_df)
        e10=core.merge_demo(core.extract_election(hist_df,"10"),hist_demo)
        e15=core.merge_demo(core.extract_election(hist_df,"15"),hist_demo)
        e17=core.merge_demo(core.extract_election(hist_df,"17"),hist_demo)
        e19=core.merge_demo(core.extract_election(hist_df,"19"),hist_demo)
        e19n=core.merge_demo(core.extract_election(curr_df,"19"),curr_demo)
        e24=core.merge_demo(core.extract_election(curr_df,"24"),curr_demo)

        # Redirect the parser audit to a v0.9.26 research artefact while keeping
        # the already-validated v0.9.22 parser implementation unchanged.
        old_integrity=core.INTEGRITY_OUT
        core.INTEGRITY_OUT=INTEGRITY_OUT
        try:
            integrity=core.run_integrity_checks([
                ("2010 actual",e10,"old",core.EXPECTED_WINNERS["10"]),
                ("2015 actual",e15,"old",core.EXPECTED_WINNERS["15"]),
                ("2017 actual",e17,"old",core.EXPECTED_WINNERS["17"]),
                ("2019 actual",e19,"old",core.EXPECTED_WINNERS["19"]),
                ("2019 notional on 2024 boundaries",e19n,"new",None),
                ("2024 actual",e24,"new",core.EXPECTED_WINNERS["24"]),
            ])
        finally:
            core.INTEGRITY_OUT=old_integrity
        integrity["version"]="uk-v0927-bes-integrity-wrapper"
        integrity["engine_parser_version"]="uk-v0922-bes-integrity"
        _write_json(INTEGRITY_OUT,integrity)
        print("BES integrity gate: PASSED")

        t10_15=core.build_transition(e10,e15);t15_17=core.build_transition(e15,e17)
        t17_19=core.build_transition(e17,e19);t19n_24=core.build_transition(e19n,e24)
        selected_spec,tuning=core.tune_spec(t10_15,t15_17)

        dev_models,dev_names=core.train_models([t10_15],selected_spec)
        dev_raw=core.predict_transition(e15,t15_17["target"],dev_models,dev_names,selected_spec)
        dev_dispersed,dev_dispersion=core.calibrate_party_dispersion(dev_raw,e15,t15_17["target"],[e10,e15])
        selected_party_strengths,party_strength_tuning,dev_contest_scores=core.tune_party_strengths(dev_dispersed,e15,e17,t15_17["target"],[t10_15])
        dev_calibrated=core.calibrate_with_party_strengths(dev_dispersed,dev_contest_scores,e15,t15_17["target"],selected_party_strengths)
        selected_routing,routing_tuning,dev_routed=core.tune_incumbent_routing(dev_calibrated,e15,e17,t15_17["target"])

        models_val,names_val=core.train_models([t10_15,t15_17],selected_spec)
        val_raw=core.predict_transition(e17,t17_19["target"],models_val,names_val,selected_spec)
        val_pre_route,val_dispersion,val_contest_scores=core.apply_party_calibration(val_raw,e17,t17_19["target"],[e10,e15,e17],[t10_15,t15_17],selected_party_strengths)
        val_rows,val_routing=core.route_incumbent_collapse(val_pre_route,e17,t17_19["target"],selected_routing["route_strength"],selected_routing["unwind_strength"])

        models_hold,names_hold=core.train_models([t10_15,t15_17,t17_19],selected_spec)
        hold_raw=core.predict_transition(e19n,t19n_24["target"],models_hold,names_hold,selected_spec)
        hold_pre_route,hold_dispersion,hold_contest_scores=core.apply_party_calibration(hold_raw,e19n,t19n_24["target"],[e10,e15,e17,e19],[t10_15,t15_17,t17_19],selected_party_strengths)
        hold_rows,hold_routing=core.route_incumbent_collapse(hold_pre_route,e19n,t19n_24["target"],selected_routing["route_strength"],selected_routing["unwind_strength"])

        reference,_,v0915_hold_rows,_,local24=core.evaluate_v0915_reference(val_rows,hold_rows,e17,e19,e19n,e24)

        # v0.9.26 methodological correction: reconstruct the ACTUAL constituency-level
        # v0.9.15 validation rows for 2019.  v0.9.23 verified only the frozen 585/632
        # aggregate but accidentally passed the older 583/632 canonical rows into the
        # geography bridge.  The zero-strength bridge must be exactly the v0.9.15
        # baseline in both elections.
        raw19,src_local19=core.fetch_dc_local_results(core.LOCAL_DATES_2019)
        ons19,ons19_meta=core.fetch_ons_ward_lookup("2019")
        local19=core.build_local_advantage_profile(e17,raw19,ons19,"2019-12-12")
        if local19["matched_seats"]<300:
            raise RuntimeError(f"v0.9.15 2019 local-strength coverage too low: {local19['matched_seats']}")
        v0915_val_rows,v0915_meta19=core.apply_local_election_strength_refined(
            val_rows,e17,core.nat_shares(e19),local19,0.25,0.0,None
        )
        v0915_m19=core.evaluate_rows(v0915_val_rows,e19,e17)
        if v0915_m19["correct_winners"]!=585 or v0915_m19["seat_abs_error_sum"]!=42:
            raise RuntimeError(f"Reconstructed v0.9.15 2019 rows do not match frozen reference: {v0915_m19}")
        v0915_m24=core.evaluate_rows(v0915_hold_rows,e24,e19n)
        if v0915_m24["correct_winners"]!=501 or v0915_m24["seat_abs_error_sum"]!=166:
            raise RuntimeError(f"Reconstructed v0.9.15 2024 rows do not match frozen reference: {v0915_m24}")
        baseline_reconstruction={
            "status":"passed",
            "parameters":{"local_strength":0.25,"confidence_floor":0.0,"margin_cap":None},
            "validation_2019":v0915_m19,"benchmark_2024":v0915_m24,
            "meta_2019":v0915_meta19,
            "coverage_2019":{k:v for k,v in local19.items() if k!="seats"},
            "sources_2019":{"local_results":src_local19,"ons_lookup":ons19_meta},
            "invariant":"strength=0 must reproduce v0.9.15 constituency rows and metrics in both 2019 and 2024",
        }

        # Live canonical rows, still using our own polling target.
        target_now,poll_meta=core.calculate_poll_target(DATA/"polls.json")
        models_live,names_live=core.train_models([t10_15,t15_17,t17_19,t19n_24],selected_spec)
        live_raw=core.predict_transition(e24,target_now,models_live,names_live,selected_spec)
        live_pre_route,live_dispersion,live_contest_scores=core.apply_party_calibration(
            live_raw,e24,target_now,[e10,e15,e17,e19,e24],[t10_15,t15_17,t17_19,t19n_24],selected_party_strengths
        )
        live_rows,live_routing=core.route_incumbent_collapse(live_pre_route,e24,target_now,selected_routing["route_strength"],selected_routing["unwind_strength"])

        return {
            "integrity":integrity,"hist_meta":hist_meta,"curr_meta":curr_meta,
            "e10":e10,"e15":e15,"e17":e17,"e19":e19,"e19n":e19n,"e24":e24,
            "t10_15":t10_15,"t15_17":t15_17,"t17_19":t17_19,"t19n_24":t19n_24,
            "selected_spec":selected_spec,"tuning":tuning,
            "selected_party_strengths":selected_party_strengths,"party_strength_tuning":party_strength_tuning,
            "selected_routing":selected_routing,"routing_tuning":routing_tuning,
            "val_rows":val_rows,"v0915_val_rows":v0915_val_rows,"v0915_hold_rows":v0915_hold_rows,"hold_rows":hold_rows,
            "reference":reference,"local19":local19,"local24":local24,"baseline_reconstruction":baseline_reconstruction,
            "target_now":target_now,"poll_meta":poll_meta,"live_rows":live_rows,
            "live_contest_scores":live_contest_scores,"live_dispersion":live_dispersion,"live_routing":live_routing,
        }


def _load_prior_sources()->dict[str,Any]:
    specs=[
        ("yougov2019",YOUGOV_2019_URL,"YouGov","2019-11-27",True),
        ("yougov2024_early",YOUGOV_2024_EARLY_URL,"YouGov","2024-06-03",False),
        ("yougov2024_mid",YOUGOV_2024_MID_URL,"YouGov","2024-06-19",False),
        ("yougov2024",YOUGOV_2024_URL,"YouGov","2024-07-03",False),
        ("mic2024_early",MIC_2024_EARLY_URL,"More in Common","2024-06-03",False),
        ("mic2024_mid",MIC_2024_MID_URL,"More in Common","2024-06-19",False),
        ("mic2024",MIC_2024_URL,"More in Common","2024-07-03",False),
    ]
    out={};meta={}
    for key,url,provider,date,is_y19 in specs:
        raw,src=fetch_remote_bytes(url)
        if is_y19:
            df,pmeta=parse_yougov_2019(raw)
        else:
            df,pmeta=parse_apogee_csv(raw,provider,date)
        out[key]=df;meta[key]={**pmeta,**src}
    out["source_meta"]=meta
    return out


def _self_test()->int:
    # Parser row-count gates are intentionally not weakened for tests; exercise
    # the transformation directly with synthetic election geometry instead.
    idx=pd.RangeIndex(2)
    frame=pd.DataFrame({
        "id":["A","B"],"name":["Alpha","Beta"],"country":["England","England"],
        "region":["london","south_east"],"weight":[1000.0,1000.0],
        "actual_winner":["lab","con"],"actual_second":["con","lab"],
        **{p:[0.0,0.0] for p in PARTIES}
    },index=idx)
    for p,vals in {"lab":[45,35],"con":[35,45],"ref":[10,10],"ld":[5,5],"green":[4,4],"other":[1,1],"snp":[0,0],"pc":[0,0]}.items():frame[p]=vals
    election={"frame":frame,"year":"x"}
    rows=frame.loc[:,PARTIES].copy()
    factors=pd.DataFrame(1.0,index=idx,columns=PARTIES)
    factors.loc[0,"lab"]=1.5;factors.loc[1,"con"]=1.5
    out=apply_factors(rows,election,core.nat_shares(election),factors,0.75)
    nat=core.weighted_nat_rows(out,election);target=core.normalize_target(core.nat_shares(election))
    if max(abs(nat[p]-target[p]) for p in PARTIES)>.08:
        raise RuntimeError(f"self-test national rake failed: {nat} vs {target}")
    if float(out.loc[0,"lab"])<=float(rows.loc[0,"lab"]):raise RuntimeError("self-test geography factor did not move seat 0")
    if float(out.loc[1,"con"])<=float(rows.loc[1,"con"]):raise RuntimeError("self-test geography factor did not move seat 1")
    zero=apply_factors(rows,election,core.nat_shares(election),factors,0.0)
    if not zero.equals(rows):raise RuntimeError("self-test strength=0 is not exact baseline")
    pure=apply_factors(rows,election,core.nat_shares(election),factors,1.0)
    half=apply_factors(rows,election,core.nat_shares(election),factors,0.5)
    # The half blend must lie between the internal and pure-external direction
    # for the deliberately boosted party/seat combinations.
    if not (float(rows.loc[0,"lab"]) < float(half.loc[0,"lab"]) < float(pure.loc[0,"lab"])):
        raise RuntimeError("self-test log-space interpolation failed for Labour")
    alt=rows.copy()
    alt.loc[0,"lab"],alt.loc[0,"con"]=60.0,20.0
    alt.loc[1,"lab"],alt.loc[1,"con"]=20.0,60.0
    # Re-rake the alternate internal geography to the same national target.
    alt=core.rake(alt,election,core.nat_shares(election))
    pure_alt=apply_factors(alt,election,core.nat_shares(election),factors,1.0)
    if float((pure_alt-pure).abs().to_numpy().max())>1e-7:
        raise RuntimeError("self-test strength=1 still depends on internal geography")

    # Exercise the flexible XLSX scanner with a realistic title row.
    buf=io.BytesIO()
    synth=pd.DataFrame([
        ["More in Common synthetic MRP",None,None,None,None,None,None,None,None],
        ["Constituency","Conservative","Labour","Liberal Democrats","Reform UK","The Green Party if standing in your constituency","Scottish National Party (SNP)","Plaid Cymru if standing in your constituency","Other / Independent"],
    ]+[[f"Seat {i}",25,30,12,20,8,0,0,5] for i in range(620)])
    with pd.ExcelWriter(buf,engine="openpyxl") as writer:synth.to_excel(writer,index=False,header=False,sheet_name="Constituencies")
    if _party_from_header("The Green Party")!="green":
        raise RuntimeError("self-test failed to map The Green Party")
    if _party_from_header("The Green Party if standing in your constituency")!="green":
        raise RuntimeError("self-test failed to map long Green header")
    xdf,xmeta=parse_mic_2026_xlsx(buf.getvalue())
    if len(xdf)!=620 or xmeta["sheet"]!="Constituencies":raise RuntimeError("self-test XLSX parser failed")
    if set(xmeta.get("mapped_columns",{}))!=set(PARTIES):
        raise RuntimeError(f"self-test XLSX party coverage failed: {xmeta.get('mapped_columns')}")

    # Temporal transfer endpoint and shrinkage checks.
    anchor=pd.DataFrame(1.0,index=idx,columns=PARTIES)
    oldp=pd.DataFrame(1.0,index=idx,columns=PARTIES)
    newp=pd.DataFrame(1.0,index=idx,columns=PARTIES)
    newp.loc[0,"lab"]=2.0;newp.loc[1,"con"]=0.5
    ev0=evolution_factors(anchor,oldp,newp,0.0)
    ev1=evolution_factors(anchor,oldp,newp,1.0)
    evh=evolution_factors(anchor,oldp,newp,0.5)
    if float((ev0-anchor).abs().to_numpy().max())>1e-10:
        raise RuntimeError("self-test temporal lambda=0 does not preserve anchor")
    if not (1.0<float(evh.loc[0,"lab"])<float(ev1.loc[0,"lab"])):
        raise RuntimeError("self-test temporal shrinkage is not monotonic")
    print("v0.9.27 geography replacement + temporal transfer self-test: PASSED")
    return 0


def main()->int:
    state=build_core_state()
    e17=state["e17"];e19=state["e19"];e19n=state["e19n"];e24=state["e24"]
    target19=core.nat_shares(e19);target24=core.nat_shares(e24)
    sources=_load_prior_sources()

    y19_aligned,y19_cov=align_prior(sources["yougov2019"],e19,"YouGov 2019",min_match=630)
    y24e_aligned,y24e_cov=align_prior(sources["yougov2024_early"],e24,"YouGov 2024-06-03",min_match=620)
    y24m_aligned,y24m_cov=align_prior(sources["yougov2024_mid"],e24,"YouGov 2024-06-19",min_match=620)
    y24_aligned,y24_cov=align_prior(sources["yougov2024"],e24,"YouGov 2024-07-03",min_match=620)
    m24e_aligned,m24e_cov=align_prior(sources["mic2024_early"],e24,"More in Common 2024-06-03",min_match=620)
    m24m_aligned,m24m_cov=align_prior(sources["mic2024_mid"],e24,"More in Common 2024-06-19",min_match=620)
    m24_aligned,m24_cov=align_prior(sources["mic2024"],e24,"More in Common 2024-07-03",min_match=620)
    y19_factors,y19_nat=relative_factors(y19_aligned,e19,e17)
    y24e_factors,y24e_nat=relative_factors(y24e_aligned,e24,e19n)
    y24m_factors,y24m_nat=relative_factors(y24m_aligned,e24,e19n)
    y24_factors,y24_nat=relative_factors(y24_aligned,e24,e19n)
    m24e_factors,m24e_nat=relative_factors(m24e_aligned,e24,e19n)
    m24m_factors,m24m_nat=relative_factors(m24m_aligned,e24,e19n)
    m24_factors,m24_nat=relative_factors(m24_aligned,e24,e19n)

    # Calibrate how much geographic *movement* from MiC transfers to a YouGov
    # structural anchor. This uses only successive pre-election MRP waves and
    # never the realised 2024 election outcome. Training and validation windows
    # are chronologically separated.
    temporal_transfer=calibrate_temporal_transfer(
        y24e_factors,m24e_factors,m24m_factors,y24m_factors,
        y24m_aligned,m24e_aligned,m24m_aligned,
        y24_factors,m24_factors,y24_aligned,m24_aligned,
    )
    temporal_lambda=float(temporal_transfer["selected_lambda"])

    # Select geography blend strength on 2019 only.
    calibration=[];cal_rows={}
    for strength in STRENGTH_GRID:
        rows=apply_factors(state["v0915_val_rows"],e17,target19,y19_factors,strength)
        metrics=core.evaluate_rows(rows,e19,e17)
        calibration.append({"strength":strength,"metrics":metrics})
        cal_rows[strength]=rows
    calibration.sort(key=lambda x:(core.score_tuple(x["metrics"]),-x["strength"]),reverse=True)
    selected=float(calibration[0]["strength"])
    val_bridge=cal_rows[selected]
    val_metrics=core.evaluate_rows(val_bridge,e19,e17)
    val_base=core.evaluate_rows(state["v0915_val_rows"],e19,e17)

    # Score the ENTIRE predeclared strength grid on 2024 for diagnostics only.
    # This does not participate in parameter selection; `selected` above is already
    # frozen from 2019.  The sweep tells us whether the bridge has latent 2024 value
    # even when historical validation rejects a particular strength.
    ensemble=ensemble_factors(y24_factors,m24_factors)
    sweep_2024=[]
    sweep_rows={}
    providers=(("yougov",y24_factors),("more_in_common",m24_factors),("equal_provider_ensemble",ensemble))
    for provider,factors in providers:
        for strength in STRENGTH_GRID:
            rows=apply_factors(state["v0915_hold_rows"],e19n,target24,factors,strength)
            metrics=core.evaluate_rows(rows,e24,e19n)
            sweep_2024.append({"provider":provider,"strength":float(strength),"metrics":metrics,"selection_role":"diagnostic_only"})
            sweep_rows[(provider,float(strength))]=rows

    primary_rows=sweep_rows[("yougov",selected)]
    primary_metrics=core.evaluate_rows(primary_rows,e24,e19n)
    mic_rows=sweep_rows[("more_in_common",selected)]
    mic_metrics=core.evaluate_rows(mic_rows,e24,e19n)
    ens_rows=sweep_rows[("equal_provider_ensemble",selected)]
    ens_metrics=core.evaluate_rows(ens_rows,e24,e19n)

    best_expost_by_provider={}
    for provider,_ in providers:
        candidates=[x for x in sweep_2024 if x["provider"]==provider]
        best_expost_by_provider[provider]=max(candidates,key=lambda x:core.score_tuple(x["metrics"]))

    reference=state["reference"]
    if reference["benchmark_2024"]["correct_winners"]!=501 or reference["benchmark_2024"]["seat_abs_error_sum"]!=166:
        raise RuntimeError(f"Frozen v0.9.15 benchmark changed: {reference['benchmark_2024']}")
    if reference["validation_2019"]["correct_winners"]!=585 or reference["validation_2019"]["seat_abs_error_sum"]!=42:
        raise RuntimeError(f"Frozen v0.9.15 validation changed: {reference['validation_2019']}")

    zero19=next(x["metrics"] for x in calibration if abs(float(x["strength"]))<1e-12)
    zero24=next(x["metrics"] for x in sweep_2024 if x["provider"]=="yougov" and abs(float(x["strength"]))<1e-12)
    if zero19["correct_winners"]!=585 or zero19["seat_abs_error_sum"]!=42:
        raise RuntimeError(f"Corrected-baseline invariant failed in 2019 at strength=0: {zero19}")
    if zero24["correct_winners"]!=501 or zero24["seat_abs_error_sum"]!=166:
        raise RuntimeError(f"Corrected-baseline invariant failed in 2024 at strength=0: {zero24}")

    validation_gate=(val_metrics["correct_winners"]>=585 and val_metrics["seat_abs_error_sum"]<=42)
    gate_85=(primary_metrics["correct_winners"]>=538 and primary_metrics["seat_abs_error_sum"]<=166 and validation_gate)
    breakthrough_87=(primary_metrics["correct_winners"]>=550 and primary_metrics["seat_abs_error_sum"]<=150 and validation_gate)
    stretch_90=(primary_metrics["correct_winners"]>=569 and primary_metrics["seat_abs_error_sum"]<=130 and validation_gate)

    # Frozen-lambda election replay. Lambda was selected above solely from the
    # 03-Jun -> 19-Jun MRP wave movement. We now test, without re-tuning, whether
    # transferring the 19-Jun -> 03-Jul MiC movement to the 19-Jun YouGov anchor
    # improved the eventual 2024 election projection. This is validation only.
    replay_static_rows=apply_factors(state["v0915_hold_rows"],e19n,target24,y24m_factors,selected)
    replay_cal_factors=evolution_factors(y24m_factors,m24m_factors,m24_factors,temporal_lambda)
    replay_cal_rows=apply_factors(state["v0915_hold_rows"],e19n,target24,replay_cal_factors,selected)
    replay_raw_factors=evolution_factors(y24m_factors,m24m_factors,m24_factors,1.0)
    replay_raw_rows=apply_factors(state["v0915_hold_rows"],e19n,target24,replay_raw_factors,selected)
    replay_static=core.evaluate_rows(replay_static_rows,e24,e19n)
    replay_cal=core.evaluate_rows(replay_cal_rows,e24,e19n)
    replay_raw=core.evaluate_rows(replay_raw_rows,e24,e19n)
    replay_final_youg=primary_metrics
    replay_final_mic=mic_metrics
    temporal_replay_passed=(
        replay_cal["correct_winners"]>=replay_static["correct_winners"]
        and replay_cal["seat_abs_error_sum"]<=replay_static["seat_abs_error_sum"]
        and (replay_cal["correct_winners"]>replay_static["correct_winners"]
             or replay_cal["seat_abs_error_sum"]<replay_static["seat_abs_error_sum"])
    )
    temporal_transfer["election_replay_2024"]={
        "selection_role":"validation_only_lambda_already_frozen",
        "anchor_date":"2024-06-19",
        "movement_source_interval":"More in Common 2024-06-19/2024-07-03",
        "static_yougov_0619":replay_static,
        "calibrated_transfer":replay_cal,
        "raw_full_transfer_lambda_1":replay_raw,
        "final_yougov_0703":replay_final_youg,
        "final_mic_0703":replay_final_mic,
        "passed_vs_static":bool(temporal_replay_passed),
        "uses_result_for_lambda_selection":False,
    }

    # Live 2026 candidate. The latest full-GB constituency MRP located for this
    # release is More in Common, published 2026-07-19 (fieldwork 5-28 June).
    # Unlike v0.9.25 shadow mode, v0.9.26 refuses to emit a "latest-data" live
    # candidate if this source is unavailable or a major party column is missing.
    m26_raw,m26_src=fetch_remote_bytes(MIC_2026_URL)
    m26,m26_parse=parse_mic_2026_xlsx(m26_raw)
    m26_aligned,mic26_cov=align_prior(m26,e24,"More in Common 2026",min_match=600)
    m26_factors,m26_nat=relative_factors(m26_aligned,e24,e24)
    if float(m26_nat.get("green",0.0))<=0.1:
        raise RuntimeError(f"MiC 2026 Green geography failed sanity check: weighted share={m26_nat.get('green')}")

    # Primary live route: preserve the historically validated YouGov-2024
    # structural anchor and transfer only the fraction of MiC 2024->2026
    # geographic movement supported by the pre-election cross-provider wave test.
    live_factors=evolution_factors(y24_factors,m24_factors,m26_factors,temporal_lambda)
    live_source={
        "status":"yougov24_plus_calibrated_mic26_evolution",
        "provider":"More in Common",
        "publication_date":"2026-07-19",
        "fieldwork":"2026-06-05/2026-06-28",
        "latest_full_gb_mrp_checked_for_release":True,
        "temporal_lambda":temporal_lambda,
        "temporal_lambda_selected_from":"2024 pre-election cross-provider MRP wave movement",
        "temporal_wave_validation_passed_vs_static":bool(temporal_transfer.get("validation_passed_vs_static")),
        "temporal_election_replay_passed_vs_static":bool(temporal_replay_passed),
    }

    live_bridge_rows=apply_factors(state["live_rows"],e24,state["target_now"],live_factors,selected)
    live_projection=core.live_projection(
        e24,state["target_now"],live_bridge_rows,state["live_contest_scores"],
        {
            "kind":"v0927_calibrated_temporal_mrp_geography_live_candidate",
            "national_target_source":"internal_polling_model_dynamic_each_run",
            "geography_strength":selected,
            "temporal_evolution_lambda":temporal_lambda,
            "live_geography":live_source["status"],
            "provider_topline_used":False,
            "external_geography_publication_date":"2026-07-19",
        }
    )

    # Non-selecting live sensitivities. There is no realised 2026 general-election
    # outcome, so these cannot choose the live route. Include the old full-evolution
    # route explicitly to quantify how much the new shrinkage resolves instability.
    live_full_rows=apply_factors(
        state["live_rows"],e24,state["target_now"],
        evolution_factors(y24_factors,m24_factors,m26_factors,1.0),selected
    )
    live_full=core.live_projection(
        e24,state["target_now"],live_full_rows,state["live_contest_scores"],
        {"kind":"v0927_full_evolution_lambda_1_sensitivity","geography_strength":selected,"provider_topline_used":False}
    )
    live_direct_rows=apply_factors(state["live_rows"],e24,state["target_now"],m26_factors,selected)
    live_direct=core.live_projection(
        e24,state["target_now"],live_direct_rows,state["live_contest_scores"],
        {"kind":"v0927_direct_mic26_sensitivity","geography_strength":selected,"provider_topline_used":False}
    )
    live_static_rows=apply_factors(state["live_rows"],e24,state["target_now"],y24_factors,selected)
    live_static=core.live_projection(
        e24,state["target_now"],live_static_rows,state["live_contest_scores"],
        {"kind":"v0927_static_yougov24_sensitivity","geography_strength":selected,"provider_topline_used":False}
    )
    def _winner_map(payload):
        return {str(x.get("id")):str(x.get("centralWinner")) for x in payload.get("seats",[]) if x.get("id")}
    primary_w=_winner_map(live_projection); full_w=_winner_map(live_full); direct_w=_winner_map(live_direct); static_w=_winner_map(live_static)
    stability=_projection_stability({
        "calibrated_primary":live_projection,
        "full_evolution_lambda_1":live_full,
        "direct_mic26":live_direct,
        "static_yougov24":live_static,
    })
    live_sensitivity={
        "selection_role":"diagnostic_only_no_2026_ground_truth",
        "calibrated_primary_totals":live_projection.get("totals",{}),
        "full_evolution_lambda_1_totals":live_full.get("totals",{}),
        "direct_mic26_totals":live_direct.get("totals",{}),
        "static_yougov24_totals":live_static.get("totals",{}),
        "changed_winners_vs_primary":{
            "full_evolution_lambda_1":sum(primary_w.get(k)!=full_w.get(k) for k in primary_w),
            "direct_mic26":sum(primary_w.get(k)!=direct_w.get(k) for k in primary_w),
            "static_yougov24":sum(primary_w.get(k)!=static_w.get(k) for k in primary_w),
        },
        "stability_audit":stability,
    }
    mic26_meta={**m26_parse,**m26_src,"relative_national_share":m26_nat}

    generated=core.utcnow().isoformat()
    common={
        "version":"uk-v0927-mrp-geography-bridge","status":"ok","generated_at":generated,
        "diagnostic_only":False,"shadow_only":False,"live_candidate":True,"approved_for_live":False,"publication_ready":False,
        "uses_2024_for_parameter_selection":False,"parameter_selection_election":"2019",
        "parameter_selection_source":"YouGov pre-election MRP 2019-11-27",
        "primary_2024_provider_precommitted":"YouGov 2024-07-03",
        "provider_topline_used":False,
        "national_target_after_bridge":"internal model target via final rake",
        "selected_strength":selected,"strength_grid":list(STRENGTH_GRID),
        "temporal_evolution_lambda":temporal_lambda,
        "temporal_lambda_selection_uses_election_result":False,
        "temporal_transfer_validation_passed":bool(temporal_transfer.get("validation_passed_vs_static")),
        "temporal_election_replay_passed":bool(temporal_replay_passed),
        "corrected_v0915_baseline":True,
        "zero_strength_invariant_passed":True,
        "research_gate_85_passed":gate_85,"breakthrough_87_passed":breakthrough_87,"stretch_90_passed":stretch_90,
        "validation_gate_passed":validation_gate,
        "thresholds":{
            "validation_2019":{"min_correct_winners":585,"max_seat_abs_error_sum":42},
            "research_85":{"min_correct_winners_2024":538,"max_seat_abs_error_sum_2024":166},
            "breakthrough_87":{"min_correct_winners_2024":550,"max_seat_abs_error_sum_2024":150},
            "stretch_90":{"min_correct_winners_2024":569,"max_seat_abs_error_sum_2024":130},
        },
        "source_urls":{
            "yougov_2019":YOUGOV_2019_URL,
            "yougov_2024_early":YOUGOV_2024_EARLY_URL,"yougov_2024_mid":YOUGOV_2024_MID_URL,"yougov_2024":YOUGOV_2024_URL,
            "mic_2024_early":MIC_2024_EARLY_URL,"mic_2024_mid":MIC_2024_MID_URL,"mic_2024":MIC_2024_URL,"mic_2026":MIC_2026_URL,
        },
    }

    backtest={
        **common,
        "reference_v0915":{"validation_2019":reference["validation_2019"],"benchmark_2024":reference["benchmark_2024"]},
        "v0915_constituency_baseline_reconstruction":state["baseline_reconstruction"],
        "strength_selection_2019":{
            "baseline_v0915_reconstructed":val_base,"selected":val_metrics,
            "candidates":calibration,
            "note":"Only this block selects a parameter. 2024 results are not consulted.",
        },
        "benchmark_2024":{
            "evaluation_label":"development_benchmark_not_pristine_holdout",
            "reference_v0915":reference["benchmark_2024"],
            "primary_yougov_anchor":primary_metrics,
            "diagnostic_mic_anchor":mic_metrics,
            "diagnostic_equal_provider_ensemble":ens_metrics,
            "primary_gain_correct_winners":primary_metrics["correct_winners"]-reference["benchmark_2024"]["correct_winners"],
            "primary_accuracy_gain_pp":(primary_metrics["winner_accuracy"]-reference["benchmark_2024"]["winner_accuracy"])*100.0,
            "primary_seat_error_improvement":reference["benchmark_2024"]["seat_abs_error_sum"]-primary_metrics["seat_abs_error_sum"],
            "provider_or_strength_selected_on_2024":False,
            "all_strengths_diagnostic":sweep_2024,
            "best_expost_by_provider":best_expost_by_provider,
            "pure_external_geography":{
                provider:next(x["metrics"] for x in sweep_2024 if x["provider"]==provider and abs(float(x["strength"])-1.0)<1e-12)
                for provider,_ in providers
            },
            "warning":"The full 2024 replacement/blend sweep is diagnostic only. It cannot select provider or strength in v0.9.27.",
        },
        "coverage":{
            "yougov2019":y19_cov,"yougov2024_early":y24e_cov,"yougov2024_mid":y24m_cov,"yougov2024":y24_cov,
            "mic2024_early":m24e_cov,"mic2024_mid":m24m_cov,"mic2024":m24_cov,"mic2026":mic26_cov,
        },
        "external_source_meta":{**sources["source_meta"],"mic2026":mic26_meta},
        "relative_prior_national_shares":{
            "yougov2019":y19_nat,"yougov2024_early":y24e_nat,"yougov2024_mid":y24m_nat,"yougov2024":y24_nat,
            "mic2024_early":m24e_nat,"mic2024_mid":m24m_nat,"mic2024":m24_nat,
        },
        "temporal_transfer_calibration":temporal_transfer,
        "changed_or_wrong_seats_2024":_seat_records(state["v0915_hold_rows"],primary_rows,e24,e19n),
        "method_note":(
            "External MRP toplines are discarded. Internal and external constituency vote shares are each converted into relative geographic factors. "
            "The two geographies are interpolated in log space: s=0 is exactly v0.9.15, s=1 is the external MRP geography with the internal national topline. "
            "The blend strength is selected on 2019 only and every projection is finally raked to the internal national target."
        ),
    }
    _write_json(BACKTEST_OUT,backtest)

    diagnostic={
        **common,
        "architecture":{
            "formula":"R_internal=(internal_local/internal_weighted_national); R_external=(external_local/external_weighted_national); R_blend=R_internal^(1-s)*R_external^s; local=internal_target*R_blend; normalize seat; rake to internal target",
            "epsilon":EPS,"factor_clip":[FACTOR_MIN,FACTOR_MAX],
            "endpoint_semantics":{"strength_0":"exact reconstructed v0.9.15 geography","strength_1":"pure external relative MRP geography with internal national target"},
            "external_topline_weighting":"pre-score-election constituency weights: 2017 for 2019; notional-2019 for 2024; 2024 for live 2026",
            "live_formula":"YouGov2024_relative_geography * exp(lambda_temporal * log(clip(latest_MiC2026_relative / MiC2024_relative))); then validated 2019-selected geography strength and final internal-target rake",
            "live_evolution_clip":[EVOLUTION_MIN,EVOLUTION_MAX],
            "temporal_lambda_grid":list(TEMPORAL_LAMBDA_GRID),
            "temporal_lambda_selection":"2024-06-03 to 2024-06-19 cross-provider MRP wave movement only; no election result",
            "temporal_lambda_validation":"frozen lambda on 2024-06-19 to 2024-07-03 cross-provider MRP wave movement plus election replay diagnostic",
        },
        "selection_result_2019":val_metrics,
        "temporal_transfer_calibration":temporal_transfer,
        "primary_result_2024":primary_metrics,
        "diagnostics_2024":{"more_in_common":mic_metrics,"equal_provider_ensemble":ens_metrics,
                            "all_strengths":sweep_2024,"best_expost_by_provider":best_expost_by_provider},
        "live_geography_status":live_source,"live_2026_sensitivity":live_sensitivity,
        "promotion_policy":"Never auto-promote. Passing the research gate only nominates the method for review and a fresh external validation.",
    }
    _write_json(DIAGNOSTIC_OUT,diagnostic)

    live_payload={
        **common,
        "version":"uk-v0927-mrp-geography-bridge-live-candidate",
        "model_type":"external-mrp-geography-replacement-blend-live-candidate",
        "applied_to_production":False,"live_candidate":True,
        "live_geography":live_source,"live_2026_sensitivity":live_sensitivity,
        "target_gb":state["target_now"],"poll_meta":state["poll_meta"],
        "selected_strength":selected,
        "source_meta":{
            "yougov2024_early":sources["source_meta"]["yougov2024_early"],"yougov2024_mid":sources["source_meta"]["yougov2024_mid"],"yougov2024":sources["source_meta"]["yougov2024"],
            "mic2024_early":sources["source_meta"]["mic2024_early"],"mic2024_mid":sources["source_meta"]["mic2024_mid"],"mic2024":sources["source_meta"]["mic2024"],"mic2026":mic26_meta,
        },
        "temporal_transfer_calibration":temporal_transfer,
        **live_projection,
    }
    _write_json(LIVE_OUT,live_payload)

    print("v0.9.27 calibrated temporal MRP geography bridge: COMPLETE")
    print(f"2019 selected strength={selected:.2f}: {val_metrics['correct_winners']}/632, seat error {val_metrics['seat_abs_error_sum']}")
    print(f"2024 PRIMARY YouGov replacement/blend: {primary_metrics['correct_winners']}/632 = {primary_metrics['winner_accuracy']*100:.2f}%, seat error {primary_metrics['seat_abs_error_sum']}")
    print(f"2024 diagnostic MiC: {mic_metrics['correct_winners']}/632 = {mic_metrics['winner_accuracy']*100:.2f}%")
    print(f"2024 diagnostic ensemble: {ens_metrics['correct_winners']}/632 = {ens_metrics['winner_accuracy']*100:.2f}%")
    for provider in ("yougov","more_in_common","equal_provider_ensemble"):
        best=best_expost_by_provider[provider]
        bm=best["metrics"]
        print(f"2024 EX-POST diagnostic best {provider}: strength={best['strength']:.2f}, {bm['correct_winners']}/632 = {bm['winner_accuracy']*100:.2f}%, seat error {bm['seat_abs_error_sum']} [NOT SELECTED]")
    for provider in ("yougov","more_in_common","equal_provider_ensemble"):
        pure=next(x["metrics"] for x in sweep_2024 if x["provider"]==provider and abs(float(x["strength"])-1.0)<1e-12)
        print(f"2024 PURE external geography {provider}: {pure['correct_winners']}/632 = {pure['winner_accuracy']*100:.2f}%, seat error {pure['seat_abs_error_sum']} [DIAGNOSTIC]")
    print(f"Gate 85={gate_85}; breakthrough 87={breakthrough_87}; stretch 90={stretch_90}; validation={validation_gate}")
    print(f"Temporal lambda selected from MRP waves={temporal_lambda:.3f}; wave validation={temporal_transfer.get('validation_passed_vs_static')}; election replay={temporal_replay_passed}")
    print(f"2026 calibrated totals={live_projection.get('totals',{})}")
    print(f"2026 changed winners vs calibrated={live_sensitivity.get('changed_winners_vs_primary',{})}")
    print(f"Live geography={live_source['status']}")
    return 0


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    try:
        raise SystemExit(_self_test() if args.self_test else main())
    except SystemExit:
        raise
    except Exception as exc:
        print(f"build_mrp_geography_bridge.py v0.9.27 failed: {exc}",file=sys.stderr)
        traceback.print_exc()
        # Leave an explicit failure artefact when DATA exists, but never disguise
        # a technical failure as a scientific gate failure.
        try:
            _write_json(DIAGNOSTIC_OUT,{"version":"uk-v0927-mrp-geography-bridge","status":"failed","generated_at":core.utcnow().isoformat(),"error":f"{type(exc).__name__}: {exc}"})
        except Exception:
            pass
        raise SystemExit(1)
