#!/usr/bin/env python3
"""
UK territorial calibration v0.5.

Goal
----
Move beyond a single GB swing by estimating:
- party-specific elasticities;
- party x geography sensitivity for Scotland, Wales and the nine English regions;
- a historical missing-baseline prior for the UKIP/Brexit/Reform lineage.

Strict validation sequence
--------------------------
TRAIN:    2010 -> 2015 and 2015 -> 2017
VALIDATE: 2017 -> 2019
HOLDOUT:  2019 notional (2024 boundaries) -> 2024

Every historical stage receives the ACTUAL target GB vote. Polling error is therefore
still excluded: this script measures only the constituency/territorial conversion.

The hierarchical model is allowed into the live site only when it does not worsen
EITHER winner accuracy OR aggregate seat error on BOTH unseen elections, and improves
at least one of those metrics somewhere. If that gate fails, app.js automatically
uses the conservative common-lambda fallback.
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import requests

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
DATA.mkdir(exist_ok=True)
DB_URL="https://raw.githubusercontent.com/ukparliament/psephology-datasette/main/psephology.db"
OUT=DATA/"backtest-2024-territorial.json"
PARAMS_OUT=DATA/"model-params.json"

PARTIES=("lab","con","ref","ld","green","snp","pc","other")
FIT_PARTIES=("lab","con","ref","ld","green","snp","pc")
FLOOR_MAIN=.18
FLOOR_SMALL=.03
COMMON_LAMBDA=.82
BETA_MIN=.45
BETA_MAX=1.65


def clamp(x:float,a:float,b:float)->float:
    return max(a,min(b,x))


def party_id(name:str|None,abbr:str|None,independent:int=0,speaker:int=0)->str:
    n=(name or "").strip().lower()
    a=(abbr or "").strip().lower()
    if independent or speaker:return "other"
    if a in {"lab","labour"} or "labour" in n:return "lab"
    if a in {"con","cons"} or "conservative" in n:return "con"
    if a in {"ld","lib dem","libdem"} or "liberal democrat" in n:return "ld"
    if a=="snp" or "scottish national" in n:return "snp"
    if a=="pc" or "plaid cymru" in n:return "pc"
    if "green" in n or a in {"green","grn"}:return "green"
    # Electoral Commission continuity: UKIP -> Brexit Party -> Reform lineage is
    # used only as a historical geographic signal.
    if (
        "reform uk" in n or "brexit party" in n or "uk independence" in n
        or a in {"ref","ruk","brx","brexit","ukip"}
    ):return "ref"
    return "other"


def download_db(dest:Path)->None:
    with requests.get(DB_URL,timeout=90,stream=True) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_content(1024*1024):
                if chunk:f.write(chunk)
    if dest.stat().st_size<1_000_000:
        raise RuntimeError("Psephology DB download unexpectedly small")


def general_election_id(conn:sqlite3.Connection,date:str,notional:bool)->int:
    rows=conn.execute(
        "SELECT id FROM general_elections WHERE polling_on=? AND is_notional=? ORDER BY id",
        (date,int(notional))
    ).fetchall()
    if len(rows)!=1:
        raise RuntimeError(f"Expected one election {date} notional={notional}, got {rows}")
    return int(rows[0][0])


def election_rows(conn:sqlite3.Connection,ge_id:int)->list[dict[str,Any]]:
    conn.row_factory=sqlite3.Row
    sql="""
    SELECT ca.geographic_code code, ca.name constituency, co.name country,
           er.name region, cand.vote_count votes,
           cand.is_winning_candidacy is_winner,
           cand.is_standing_as_independent is_independent,
           cand.is_standing_as_commons_speaker is_speaker,
           pp.name party_name, pp.abbreviation party_abbr
    FROM elections e
    JOIN constituency_groups cg ON cg.id=e.constituency_group_id
    JOIN constituency_areas ca ON ca.id=cg.constituency_area_id
    JOIN countries co ON co.id=ca.country_id
    LEFT JOIN english_regions er ON er.id=ca.english_region_id
    JOIN candidacies cand ON cand.election_id=e.id
    LEFT JOIN certifications cert ON cert.id=(
      SELECT c2.id FROM certifications c2
      WHERE c2.candidacy_id=cand.id AND c2.adjunct_to_certification_id IS NULL
      ORDER BY c2.id LIMIT 1
    )
    LEFT JOIN political_parties pp ON pp.id=cert.political_party_id
    WHERE e.general_election_id=?
    ORDER BY ca.geographic_code,cand.vote_count DESC
    """
    return [dict(r) for r in conn.execute(sql,(ge_id,)).fetchall()]


def aggregate(rows:list[dict[str,Any]])->dict[str,dict[str,Any]]:
    seats={}
    for row in rows:
        code=str(row.get("code") or "").strip()
        if not code:continue
        seat=seats.setdefault(code,{
            "id":code,"name":row.get("constituency") or code,
            "country":row.get("country") or "",
            "region":row.get("region") or row.get("country") or "",
            "votes":defaultdict(int),"winner":None
        })
        p=party_id(row.get("party_name"),row.get("party_abbr"),
                   int(row.get("is_independent") or 0),int(row.get("is_speaker") or 0))
        seat["votes"][p]+=int(row.get("votes") or 0)
        if int(row.get("is_winner") or 0):seat["winner"]=p
    for seat in seats.values():
        seat["votes"]=dict(seat["votes"])
        if not seat["winner"] and seat["votes"]:
            seat["winner"]=max(seat["votes"],key=seat["votes"].get)
    return seats


def country_key(country:str)->str:
    c=country.lower()
    if "scotland" in c:return "Scotland"
    if "wales" in c:return "Wales"
    if "northern ireland" in c:return "Northern Ireland"
    return "England"


def zone_key(seat:dict[str,Any])->str:
    c=country_key(seat["country"])
    if c in {"Scotland","Wales","Northern Ireland"}:
        return c
    return (seat.get("region") or "England").strip() or "England"


def shares_from_seats(
    seats:dict[str,dict[str,Any]],
    *,
    country:str|None=None,
    zone:str|None=None
)->dict[str,float]:
    totals=Counter()
    for seat in seats.values():
        ck=country_key(seat["country"])
        if ck=="Northern Ireland":continue
        if country is not None and ck!=country:continue
        if zone is not None and zone_key(seat)!=zone:continue
        totals.update(seat["votes"])
    denom=sum(totals.values())
    if not denom:
        return {p:0.0 for p in PARTIES}
    return {p:totals[p]/denom*100 for p in PARTIES}


def local_shares(seat:dict[str,Any])->dict[str,float]:
    total=sum(seat["votes"].values())
    return {p:(seat["votes"].get(p,0)/total*100 if total else 0) for p in PARTIES}


def allowed(p:str,country:str)->bool:
    c=country.lower()
    if p=="snp":return "scotland" in c
    if p=="pc":return "wales" in c
    return True


def all_zones(seats:dict[str,dict[str,Any]])->list[str]:
    return sorted({
        zone_key(s) for s in seats.values()
        if country_key(s["country"])!="Northern Ireland"
    })


def fit_regional_betas(
    train_cycles:list[tuple[str,dict[str,Any],dict[str,Any]]],
    prior_strength:float
)->dict[str,dict[str,float]]:
    """
    Estimate how strongly each geography historically responds to a GB swing.

    For each party/zone:
        log(region target / region base) ~= beta * log(GB target / GB base)

    beta is ridge-shrunk to 1.0 because only two training transitions exist.
    """
    zones=sorted(set().union(*(all_zones(b) for _,b,_ in train_cycles)))
    betas={z:{p:1.0 for p in FIT_PARTIES} for z in zones}

    for z in zones:
        for p in FIT_PARTIES:
            num=prior_strength
            den=prior_strength
            observations=0
            for _,base,target in train_cycles:
                gb_b=shares_from_seats(base).get(p,0)
                gb_t=shares_from_seats(target).get(p,0)
                rz_b=shares_from_seats(base,zone=z).get(p,0)
                rz_t=shares_from_seats(target,zone=z).get(p,0)
                if min(gb_b,gb_t,rz_b,rz_t)<0.12:
                    continue
                x=math.log(gb_t/gb_b)
                y=math.log(rz_t/rz_b)
                if abs(x)<0.025:
                    continue
                # Very large national moves carry more information but are capped.
                w=min(1.5,max(.35,abs(x)/.12))
                num+=w*x*y
                den+=w*x*x
                observations+=1
            if observations:
                betas[z][p]=round(clamp(num/den,BETA_MIN,BETA_MAX),4)
    return betas


def project_winner(
    seat:dict[str,Any],
    base_nat:dict[str,float],
    target_nat:dict[str,float],
    lambdas:dict[str,float],
    regional_betas:dict[str,dict[str,float]]|None=None,
    ref_missing_prior:float=0.0
)->str:
    base=local_shares(seat)
    raw={}
    zone=zone_key(seat)
    beta_row=(regional_betas or {}).get(zone,{})
    for p in PARTIES:
        if not allowed(p,seat["country"]):
            raw[p]=0.0;continue
        if p=="other":
            raw[p]=max(base.get(p,0),FLOOR_SMALL);continue
        bn=max(base_nat.get(p,0),.05)
        tn=max(target_nat.get(p,0),.05)
        b=base.get(p,0)
        if p=="ref" and b<FLOOR_MAIN and ref_missing_prior>0:
            b=max(b,bn*ref_missing_prior)
        b=max(b,FLOOR_MAIN if p in {"lab","con","ref","ld","green"} else FLOOR_SMALL)
        beta=beta_row.get(p,1.0)
        raw[p]=b*(max(.08,tn/bn)**(lambdas.get(p,COMMON_LAMBDA)*beta))
    return max(raw,key=raw.get)


def evaluate(
    baseline:dict[str,dict[str,Any]],
    actual:dict[str,dict[str,Any]],
    lambdas:dict[str,float],
    regional_betas:dict[str,dict[str,float]]|None=None,
    ref_missing_prior:float=0.0,
    country_oracle:bool=False
)->dict[str,Any]:
    gb_base=shares_from_seats(baseline)
    gb_target=shares_from_seats(actual)
    base_country={c:shares_from_seats(baseline,country=c) for c in ("England","Scotland","Wales")}
    target_country={c:shares_from_seats(actual,country=c) for c in ("England","Scotland","Wales")}

    pred=Counter();real=Counter();correct=0;n=0
    by_region=defaultdict(lambda:[0,0])
    missing=[]
    for code,a in actual.items():
        if country_key(a["country"])=="Northern Ireland":continue
        b=baseline.get(code)
        if not b:
            missing.append(code);continue
        ck=country_key(a["country"])
        bn=base_country[ck] if country_oracle else gb_base
        tn=target_country[ck] if country_oracle else gb_target
        pw=project_winner(b,bn,tn,lambdas,regional_betas,ref_missing_prior)
        rw=a["winner"] or "other"
        pred[pw]+=1;real[rw]+=1;n+=1
        if pw==rw:
            correct+=1;by_region[zone_key(a)][0]+=1
        by_region[zone_key(a)][1]+=1

    if missing:
        raise RuntimeError(f"{len(missing)} missing baseline seats, e.g. {missing[:8]}")
    if n!=632:
        raise RuntimeError(f"Expected 632 GB seats, got {n}")

    seat_error={p:int(pred[p]-real[p]) for p in PARTIES}
    abs_error=sum(abs(x) for x in seat_error.values())
    return {
        "winner_accuracy":correct/n,
        "correct_winners":correct,
        "gb_seats":n,
        "predicted_seats":{p:int(pred[p]) for p in PARTIES},
        "actual_seats":{p:int(real[p]) for p in PARTIES},
        "seat_error":seat_error,
        "seat_abs_error_sum":int(abs_error),
        "regional_accuracy":{
            r:{"correct":v[0],"n":v[1],"accuracy":v[0]/v[1] if v[1] else None}
            for r,v in sorted(by_region.items())
        }
    }


def combine_score(results:list[dict[str,Any]])->tuple[int,int]:
    return (
        sum(r["correct_winners"] for r in results),
        -sum(r["seat_abs_error_sum"] for r in results)
    )


def fit_party_params(
    train_cycles:list[tuple[str,dict[str,Any],dict[str,Any]]],
    regional_betas:dict[str,dict[str,float]]|None
)->tuple[dict[str,float],float,dict[str,Any]]:
    lambdas={p:COMMON_LAMBDA for p in FIT_PARTIES}
    prior=0.0

    def results_for(ls,pr):
        return [evaluate(b,a,ls,regional_betas,pr) for _,b,a in train_cycles]

    grid=[round(.35+i*.05,2) for i in range(23)]  # .35..1.45
    for _ in range(2):
        for p in FIT_PARTIES:
            best=(combine_score(results_for(lambdas,prior)),lambdas[p])
            for candidate in grid:
                trial=dict(lambdas);trial[p]=candidate
                score=combine_score(results_for(trial,prior))
                if score>best[0]:
                    best=(score,candidate)
            lambdas[p]=best[1]

        best=(combine_score(results_for(lambdas,prior)),prior)
        for candidate in [0,.1,.2,.3,.4,.5,.6,.7,.8,1.0]:
            score=combine_score(results_for(lambdas,candidate))
            if score>best[0]:
                best=(score,candidate)
        prior=best[1]

    train_results=results_for(lambdas,prior)
    return lambdas,prior,{
        "cycles":{label:r for (label,_,_),r in zip(train_cycles,train_results)},
        "combined_correct":sum(r["correct_winners"] for r in train_results),
        "combined_seat_abs_error":sum(r["seat_abs_error_sum"] for r in train_results),
    }


def fit_hierarchical(
    train_cycles:list[tuple[str,dict[str,Any],dict[str,Any]]]
)->tuple[dict[str,float],dict[str,dict[str,float]],float,float,dict[str,Any]]:
    """
    Tune only the ridge strength on training data; validation/holdout remain unseen.
    For each ridge candidate, estimate regional beta analytically and fit party lambdas.
    """
    best=None
    for ridge in (.02,.04,.07,.10,.16,.25,.40,.65,1.0):
        betas=fit_regional_betas(train_cycles,ridge)
        lambdas,prior,train_result=fit_party_params(train_cycles,betas)
        score=(train_result["combined_correct"],-train_result["combined_seat_abs_error"])
        candidate=(score,lambdas,betas,prior,ridge,train_result)
        if best is None or candidate[0]>best[0]:
            best=candidate
    assert best is not None
    _,lambdas,betas,prior,ridge,train_result=best
    return lambdas,betas,prior,ridge,train_result


def model_gate(
    val_base:dict[str,Any],val_candidate:dict[str,Any],
    hold_base:dict[str,Any],hold_candidate:dict[str,Any]
)->bool:
    val_ok=(
        val_candidate["winner_accuracy"]>=val_base["winner_accuracy"]
        and val_candidate["seat_abs_error_sum"]<=val_base["seat_abs_error_sum"]
    )
    hold_ok=(
        hold_candidate["winner_accuracy"]>=hold_base["winner_accuracy"]
        and hold_candidate["seat_abs_error_sum"]<=hold_base["seat_abs_error_sum"]
    )
    strict=(
        val_candidate["winner_accuracy"]>val_base["winner_accuracy"]
        or val_candidate["seat_abs_error_sum"]<val_base["seat_abs_error_sum"]
        or hold_candidate["winner_accuracy"]>hold_base["winner_accuracy"]
        or hold_candidate["seat_abs_error_sum"]<hold_base["seat_abs_error_sum"]
    )
    return bool(val_ok and hold_ok and strict)



TRANSFER_FEATURE_PARTIES=("lab","con","ref","ld","green","snp","pc")
TRANSFER_TARGET_PARTIES=("lab","con","ref","ld","green","snp","pc","other")
TRANSFER_RIDGE_GRID=(.10,.30,1.0,3.0,10.0,30.0,100.0)


def seat_weight(seat:dict[str,Any])->float:
    return float(sum((seat.get("votes") or {}).values()) or 1.0)


def normalized_row(raw:dict[str,float],country:str)->dict[str,float]:
    out={}
    total=0.0
    for p in PARTIES:
        if not allowed(p,country):
            out[p]=0.0
            continue
        v=max(.0001,float(raw.get(p,0.0)))
        out[p]=v
        total+=v
    if total<=0:
        return {p:(100.0 if p=="other" else 0.0) for p in PARTIES}
    return {p:(out[p]/total*100.0 if allowed(p,country) else 0.0) for p in PARTIES}


def proportional_rows(
    baseline:dict[str,dict[str,Any]],
    target_nat:dict[str,float],
    lam:float=COMMON_LAMBDA
)->dict[str,dict[str,float]]:
    base_nat=shares_from_seats(baseline)
    rows={}
    for code,seat in baseline.items():
        if country_key(seat["country"])=="Northern Ireland":
            continue
        base=local_shares(seat)
        raw={}
        for p in PARTIES:
            if not allowed(p,seat["country"]):
                raw[p]=0.0
                continue
            b=base.get(p,0.0)
            floor=FLOOR_MAIN if p in {"lab","con","ref","ld","green"} else FLOOR_SMALL
            b=max(b,floor)
            bn=max(base_nat.get(p,0.0),.05)
            tn=max(target_nat.get(p,0.0),.05)
            raw[p]=b*(max(.08,tn/bn)**lam)
        rows[code]=normalized_row(raw,seat["country"])
    return rows


def weighted_national_from_rows(
    rows:dict[str,dict[str,float]],
    baseline:dict[str,dict[str,Any]]
)->dict[str,float]:
    totals={p:0.0 for p in PARTIES}
    den=0.0
    for code,row in rows.items():
        seat=baseline.get(code)
        if not seat:
            continue
        w=seat_weight(seat)
        den+=w
        for p in PARTIES:
            totals[p]+=w*float(row.get(p,0.0))/100.0
    if den<=0:
        return {p:0.0 for p in PARTIES}
    return {p:totals[p]/den*100.0 for p in PARTIES}


def normalize_target_for_model(target_nat:dict[str,float])->dict[str,float]:
    vals={p:max(.0001,float(target_nat.get(p,0.0))) for p in PARTIES}
    total=sum(vals.values())
    if total<=0:
        return vals
    return {p:vals[p]/total*100.0 for p in PARTIES}


def rake_rows(
    rows:dict[str,dict[str,float]],
    baseline:dict[str,dict[str,Any]],
    target_nat:dict[str,float],
    iterations:int=36
)->dict[str,dict[str,float]]:
    target=normalize_target_for_model(target_nat)
    out={code:dict(row) for code,row in rows.items()}
    for _ in range(iterations):
        current=weighted_national_from_rows(out,baseline)
        max_err=max(abs(current[p]-target[p]) for p in PARTIES)
        if max_err<.015:
            break
        mult={}
        for p in PARTIES:
            cur=max(current.get(p,0.0),.01)
            mult[p]=clamp(target.get(p,0.0)/cur,.45,2.20)
        for code,row in out.items():
            seat=baseline[code]
            raw={}
            for p in PARTIES:
                raw[p]=(row.get(p,0.0)*mult[p]) if allowed(p,seat["country"]) else 0.0
            out[code]=normalized_row(raw,seat["country"])
    return out


def transfer_features(
    seat:dict[str,Any],
    base_nat:dict[str,float],
    target_nat:dict[str,float]
)->list[float]:
    local=local_shares(seat)
    features=[]
    for p in TRANSFER_FEATURE_PARTIES:
        # Signed national movement × local over/under-exposure.
        # Scaling constants make ridge strengths comparable across parties.
        national_move=(target_nat.get(p,0.0)-base_nat.get(p,0.0))/10.0
        local_exposure=(local.get(p,0.0)-base_nat.get(p,0.0))/20.0
        features.append(national_move*local_exposure)
    return features


def solve_linear_system(a:list[list[float]],b:list[float])->list[float]:
    n=len(b)
    aug=[list(map(float,a[i]))+[float(b[i])] for i in range(n)]
    for col in range(n):
        pivot=max(range(col,n),key=lambda r:abs(aug[r][col]))
        if abs(aug[pivot][col])<1e-12:
            continue
        if pivot!=col:
            aug[col],aug[pivot]=aug[pivot],aug[col]
        div=aug[col][col]
        aug[col]=[x/div for x in aug[col]]
        for r in range(n):
            if r==col:
                continue
            f=aug[r][col]
            if abs(f)<1e-15:
                continue
            aug[r]=[aug[r][c]-f*aug[col][c] for c in range(n+1)]
    return [aug[i][-1] for i in range(n)]


def ridge_coefficients(
    x_rows:list[list[float]],
    y:list[float],
    ridge:float
)->list[float]:
    k=len(x_rows[0]) if x_rows else 0
    xtx=[[0.0]*k for _ in range(k)]
    xty=[0.0]*k
    for x,yy in zip(x_rows,y):
        for i in range(k):
            xty[i]+=x[i]*yy
            for j in range(k):
                xtx[i][j]+=x[i]*x[j]
    for i in range(k):
        xtx[i][i]+=ridge
    return solve_linear_system(xtx,xty)


def fit_transfer_coefficients(
    train_cycles:list[tuple[str,dict[str,Any],dict[str,Any]]],
    ridge:float
)->dict[str,dict[str,float]]:
    x_rows=[]
    residuals={p:[] for p in TRANSFER_TARGET_PARTIES}
    for _,baseline,actual in train_cycles:
        base_nat=shares_from_seats(baseline)
        target_nat=shares_from_seats(actual)
        initial=rake_rows(proportional_rows(baseline,target_nat),baseline,target_nat)
        for code,seat in baseline.items():
            if country_key(seat["country"])=="Northern Ireland":
                continue
            actual_seat=actual.get(code)
            if not actual_seat:
                continue
            x=transfer_features(seat,base_nat,target_nat)
            x_rows.append(x)
            truth=local_shares(actual_seat)
            for p in TRANSFER_TARGET_PARTIES:
                residuals[p].append(truth.get(p,0.0)-initial[code].get(p,0.0))
    coeff={}
    for target in TRANSFER_TARGET_PARTIES:
        beta=ridge_coefficients(x_rows,residuals[target],ridge)
        coeff[target]={
            source:round(clamp(v,-18.0,18.0),6)
            for source,v in zip(TRANSFER_FEATURE_PARTIES,beta)
        }
    return coeff


def apply_transfer_rows(
    baseline:dict[str,dict[str,Any]],
    target_nat:dict[str,float],
    coefficients:dict[str,dict[str,float]]
)->dict[str,dict[str,float]]:
    base_nat=shares_from_seats(baseline)
    initial=rake_rows(proportional_rows(baseline,target_nat),baseline,target_nat)
    rows={}
    for code,seat in baseline.items():
        if country_key(seat["country"])=="Northern Ireland":
            continue
        features=transfer_features(seat,base_nat,target_nat)
        raw=dict(initial[code])
        for target in TRANSFER_TARGET_PARTIES:
            if not allowed(target,seat["country"]):
                raw[target]=0.0
                continue
            row=coefficients.get(target,{})
            corr=0.0
            for source,value in zip(TRANSFER_FEATURE_PARTIES,features):
                corr+=float(row.get(source,0.0))*value
            raw[target]=max(.0001,raw.get(target,0.0)+corr)
        rows[code]=normalized_row(raw,seat["country"])
    # Corrections redistribute geography only. National totals are forced back
    # to the supplied target so the transfer layer cannot invent national vote.
    return rake_rows(rows,baseline,target_nat)


def evaluate_rows(
    rows:dict[str,dict[str,float]],
    actual:dict[str,dict[str,Any]]
)->dict[str,Any]:
    pred=Counter()
    real=Counter()
    correct=0
    n=0
    by_region=defaultdict(lambda:[0,0])
    share_abs=0.0
    share_n=0
    for code,a in actual.items():
        if country_key(a["country"])=="Northern Ireland":
            continue
        row=rows.get(code)
        if row is None:
            raise RuntimeError(f"Missing prediction for {code}")
        allowed_parties=[p for p in PARTIES if allowed(p,a["country"])]
        pw=max(allowed_parties,key=lambda p:row.get(p,0.0))
        rw=a["winner"] or "other"
        pred[pw]+=1
        real[rw]+=1
        n+=1
        if pw==rw:
            correct+=1
            by_region[zone_key(a)][0]+=1
        by_region[zone_key(a)][1]+=1
        truth=local_shares(a)
        for p in allowed_parties:
            share_abs+=abs(row.get(p,0.0)-truth.get(p,0.0))
            share_n+=1
    if n!=632:
        raise RuntimeError(f"Expected 632 GB seats, got {n}")
    seat_error={p:int(pred[p]-real[p]) for p in PARTIES}
    abs_error=sum(abs(x) for x in seat_error.values())
    return {
        "winner_accuracy":correct/n,
        "correct_winners":correct,
        "gb_seats":n,
        "predicted_seats":{p:int(pred[p]) for p in PARTIES},
        "actual_seats":{p:int(real[p]) for p in PARTIES},
        "seat_error":seat_error,
        "seat_abs_error_sum":int(abs_error),
        "share_mae":share_abs/share_n if share_n else None,
        "regional_accuracy":{
            r:{"correct":v[0],"n":v[1],"accuracy":v[0]/v[1] if v[1] else None}
            for r,v in sorted(by_region.items())
        }
    }


def evaluate_raked(
    baseline:dict[str,dict[str,Any]],
    actual:dict[str,dict[str,Any]]
)->dict[str,Any]:
    target=shares_from_seats(actual)
    rows=rake_rows(proportional_rows(baseline,target),baseline,target)
    return evaluate_rows(rows,actual)


def evaluate_transfer(
    baseline:dict[str,dict[str,Any]],
    actual:dict[str,dict[str,Any]],
    coefficients:dict[str,dict[str,float]]
)->dict[str,Any]:
    target=shares_from_seats(actual)
    rows=apply_transfer_rows(baseline,target,coefficients)
    return evaluate_rows(rows,actual)


def fit_transfer_model(
    train_cycles:list[tuple[str,dict[str,Any],dict[str,Any]]]
)->tuple[dict[str,dict[str,float]],float,dict[str,Any]]:
    best=None
    for ridge in TRANSFER_RIDGE_GRID:
        coeff=fit_transfer_coefficients(train_cycles,ridge)
        results=[evaluate_transfer(b,a,coeff) for _,b,a in train_cycles]
        score=(
            sum(r["correct_winners"] for r in results),
            -sum(r["seat_abs_error_sum"] for r in results),
            -sum(r["share_mae"] or 999 for r in results),
        )
        candidate=(score,coeff,ridge,results)
        if best is None or candidate[0]>best[0]:
            best=candidate
    assert best is not None
    _,coeff,ridge,results=best
    return coeff,ridge,{
        "cycles":{label:r for (label,_,_),r in zip(train_cycles,results)},
        "combined_correct":sum(r["correct_winners"] for r in results),
        "combined_seat_abs_error":sum(r["seat_abs_error_sum"] for r in results),
        "combined_share_mae":sum(r["share_mae"] or 0 for r in results)/len(results),
    }


def rounded_coefficients(coeff:dict[str,dict[str,float]])->dict[str,dict[str,float]]:
    return {
        target:{source:round(float(v),6) for source,v in row.items()}
        for target,row in coeff.items()
    }


def main()->int:
    with tempfile.TemporaryDirectory() as td:
        db=Path(td)/"psephology.db"
        download_db(db)
        conn=sqlite3.connect(db)
        try:
            ids={
                "2010":general_election_id(conn,"2010-05-06",False),
                "2015":general_election_id(conn,"2015-05-07",False),
                "2017":general_election_id(conn,"2017-06-08",False),
                "2019":general_election_id(conn,"2019-12-12",False),
                "2019N":general_election_id(conn,"2019-12-12",True),
                "2024":general_election_id(conn,"2024-07-04",False),
            }
            elections={k:aggregate(election_rows(conn,v)) for k,v in ids.items()}
            for k,seats in elections.items():
                if len(seats)!=650:
                    raise RuntimeError(f"{k}: expected 650 seats, got {len(seats)}")

            train=[
                ("2010→2015",elections["2010"],elections["2015"]),
                ("2015→2017",elections["2015"],elections["2017"]),
            ]
            common={p:COMMON_LAMBDA for p in FIT_PARTIES}

            # Production fallback currently used by app.js when no candidate passes.
            train_common=[evaluate(b,a,common,None,0) for _,b,a in train]
            val_common=evaluate(elections["2017"],elections["2019"],common,None,0)
            hold_common=evaluate(elections["2019N"],elections["2024"],common,None,0)

            # Diagnostic: exact national raking without learned cross-party transfers.
            train_raked=[evaluate_raked(b,a) for _,b,a in train]
            val_raked=evaluate_raked(elections["2017"],elections["2019"])
            hold_raked=evaluate_raked(elections["2019N"],elections["2024"])

            # v0.6 candidate: residual cross-party transfer matrix fitted on TRAIN only.
            coeff,ridge,train_transfer=fit_transfer_model(train)
            val_transfer=evaluate_transfer(elections["2017"],elections["2019"],coeff)
            hold_transfer=evaluate_transfer(elections["2019N"],elections["2024"],coeff)

            approved=model_gate(val_common,val_transfer,hold_common,hold_transfer)

            params={
                "version":"uk-v06-transfer-raked",
                "model_type":"transfer-raked-v1",
                "approved":approved,
                "training_elections":["2010→2015","2015→2017"],
                "validation_election":"2017→2019",
                "holdout_election":"2019 notional→2024",
                "common_lambda":COMMON_LAMBDA,
                "transfer_feature_parties":list(TRANSFER_FEATURE_PARTIES),
                "transfer_target_parties":list(TRANSFER_TARGET_PARTIES),
                "transfer_coefficients":rounded_coefficients(coeff),
                "transfer_ridge":ridge,
                "rake_iterations":36,
                "validation":{
                    "common_accuracy":val_common["winner_accuracy"],
                    "raked_accuracy":val_raked["winner_accuracy"],
                    "transfer_accuracy":val_transfer["winner_accuracy"],
                    "common_seat_abs_error":val_common["seat_abs_error_sum"],
                    "raked_seat_abs_error":val_raked["seat_abs_error_sum"],
                    "transfer_seat_abs_error":val_transfer["seat_abs_error_sum"],
                    "transfer_share_mae":val_transfer["share_mae"],
                },
                "holdout":{
                    "common_accuracy":hold_common["winner_accuracy"],
                    "raked_accuracy":hold_raked["winner_accuracy"],
                    "transfer_accuracy":hold_transfer["winner_accuracy"],
                    "common_seat_abs_error":hold_common["seat_abs_error_sum"],
                    "raked_seat_abs_error":hold_raked["seat_abs_error_sum"],
                    "transfer_seat_abs_error":hold_transfer["seat_abs_error_sum"],
                    "transfer_share_mae":hold_transfer["share_mae"],
                },
                "note":(
                    "The transfer matrix is trained only on 2010→2015 and 2015→2017. "
                    "It redistributes local vote according to cross-party exposure, then "
                    "rakes constituency shares back to the supplied national target. "
                    "It is used live only when approved=true after unseen 2019 and 2024 gates."
                ),
            }
            PARAMS_OUT.write_text(
                json.dumps(params,ensure_ascii=False,indent=2),
                encoding="utf-8"
            )

            payload={
                "meta":{
                    "stage":"v0.6 transfer / competition calibration",
                    "source":"UK Parliament psephology database",
                    "polling_error_included":False,
                    "production_rule":(
                        "transfer model trained on 2010→2015 and 2015→2017 must not worsen "
                        "winner accuracy or aggregate seat error on either 2019 validation "
                        "or the untouched 2024 holdout"
                    ),
                    "model_description":(
                        "Start from proportional national swing, exactly rake back to the "
                        "national vote target, then redistribute local shares through a "
                        "ridge-regularised cross-party exposure matrix and rake again."
                    ),
                },
                "baseline_common":{
                    "lambda":COMMON_LAMBDA,
                    "training":{label:r for (label,_,_),r in zip(train,train_common)},
                    "validation_2019":val_common,
                    "holdout_2024":hold_common,
                },
                "raked_only_diagnostic":{
                    "training":{label:r for (label,_,_),r in zip(train,train_raked)},
                    "validation_2019":val_raked,
                    "holdout_2024":hold_raked,
                },
                "transfer_candidate":{
                    "ridge":ridge,
                    "coefficients":rounded_coefficients(coeff),
                    "training":train_transfer,
                    "validation_2019":val_transfer,
                    "holdout_2024":hold_transfer,
                },
                "approved_for_live":approved,
            }
            OUT.write_text(
                json.dumps(payload,ensure_ascii=False,indent=2),
                encoding="utf-8"
            )

            print("Transfer ridge:",ridge)
            print("Transfer coefficients:",json.dumps(rounded_coefficients(coeff),sort_keys=True))
            print(
                "2019 validation:",
                f"common={val_common['winner_accuracy']:.2%}/{val_common['seat_abs_error_sum']}",
                f"raked={val_raked['winner_accuracy']:.2%}/{val_raked['seat_abs_error_sum']}",
                f"transfer={val_transfer['winner_accuracy']:.2%}/{val_transfer['seat_abs_error_sum']}"
            )
            print(
                "2024 holdout:",
                f"common={hold_common['winner_accuracy']:.2%}/{hold_common['seat_abs_error_sum']}",
                f"raked={hold_raked['winner_accuracy']:.2%}/{hold_raked['seat_abs_error_sum']}",
                f"transfer={hold_transfer['winner_accuracy']:.2%}/{hold_transfer['seat_abs_error_sum']}"
            )
            print("Approved transfer model for live:",approved)
        finally:
            conn.close()
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"build_backtest.py failed: {exc}",file=sys.stderr)
        raise
