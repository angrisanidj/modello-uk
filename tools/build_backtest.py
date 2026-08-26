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



RAKE_ALPHA_GRID=tuple(round(i/40,3) for i in range(41))  # 0.000 .. 1.000 by .025
RAKE_ITERATIONS=40


def seat_weight(seat:dict[str,Any])->float:
    return float(sum((seat.get("votes") or {}).values()) or 1.0)


def normalized_row(raw:dict[str,float],country:str)->dict[str,float]:
    vals={}
    total=0.0
    for p in PARTIES:
        if not allowed(p,country):
            vals[p]=0.0
            continue
        v=max(.0001,float(raw.get(p,0.0)))
        vals[p]=v
        total+=v
    if total<=0:
        return {p:(100.0 if p=="other" else 0.0) for p in PARTIES}
    return {p:(vals[p]/total*100.0 if allowed(p,country) else 0.0) for p in PARTIES}


def proportional_rows(
    baseline:dict[str,dict[str,Any]],
    target_nat:dict[str,float],
    lam:float=COMMON_LAMBDA
)->dict[str,dict[str,float]]:
    """Row-form equivalent of the production proportional-swing centre."""
    base_nat=shares_from_seats(baseline)
    rows={}
    for code,seat in baseline.items():
        if country_key(seat["country"])=="Northern Ireland":
            continue
        local=local_shares(seat)
        raw={}
        for p in PARTIES:
            if not allowed(p,seat["country"]):
                raw[p]=0.0
                continue
            if p=="other":
                raw[p]=max(local.get(p,0.0),FLOOR_SMALL)
                continue
            b=local.get(p,0.0)
            b=max(b,FLOOR_MAIN if p in {"lab","con","ref","ld","green"} else FLOOR_SMALL)
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
        if not seat: continue
        w=seat_weight(seat)
        den+=w
        for p in PARTIES:
            totals[p]+=w*float(row.get(p,0.0))/100.0
    if den<=0: return totals
    return {p:totals[p]/den*100.0 for p in PARTIES}


def normalized_target(target_nat:dict[str,float])->dict[str,float]:
    vals={p:max(.0001,float(target_nat.get(p,0.0))) for p in PARTIES}
    total=sum(vals.values())
    if total<=0: return vals
    return {p:vals[p]/total*100.0 for p in PARTIES}


def rake_rows(
    rows:dict[str,dict[str,float]],
    baseline:dict[str,dict[str,Any]],
    target_nat:dict[str,float],
    iterations:int=RAKE_ITERATIONS
)->dict[str,dict[str,float]]:
    """Full iterative proportional fitting to the supplied GB target."""
    target=normalized_target(target_nat)
    out={code:dict(row) for code,row in rows.items()}
    for _ in range(iterations):
        current=weighted_national_from_rows(out,baseline)
        if max(abs(current[p]-target[p]) for p in PARTIES)<.01:
            break
        mult={p:clamp(target[p]/max(.01,current.get(p,0.0)),.40,2.50) for p in PARTIES}
        for code,row in out.items():
            seat=baseline[code]
            raw={p:((row.get(p,0.0)*mult[p]) if allowed(p,seat["country"]) else 0.0) for p in PARTIES}
            out[code]=normalized_row(raw,seat["country"])
    return out


def blend_rows(
    base_rows:dict[str,dict[str,float]],
    fully_raked:dict[str,dict[str,float]],
    baseline:dict[str,dict[str,Any]],
    alpha:float
)->dict[str,dict[str,float]]:
    """
    Linear share blend has a useful property: because constituency weights are
    unchanged, national totals also move linearly from the original implied
    result toward the exact target. Thus alpha has a transparent interpretation.
    """
    a=clamp(float(alpha),0.0,1.0)
    rows={}
    for code,base in base_rows.items():
        seat=baseline[code]
        full=fully_raked[code]
        raw={p:((1-a)*base.get(p,0.0)+a*full.get(p,0.0)) for p in PARTIES}
        rows[code]=normalized_row(raw,seat["country"])
    return rows


def partial_raked_rows(
    baseline:dict[str,dict[str,Any]],
    target_nat:dict[str,float],
    alpha:float
)->dict[str,dict[str,float]]:
    base=proportional_rows(baseline,target_nat)
    if alpha<=0: return base
    full=rake_rows(base,baseline,target_nat)
    if alpha>=1: return full
    return blend_rows(base,full,baseline,alpha)


def evaluate_rows(rows:dict[str,dict[str,float]],actual:dict[str,dict[str,Any]])->dict[str,Any]:
    pred=Counter();real=Counter();correct=0;n=0
    by_region=defaultdict(lambda:[0,0])
    share_abs=0.0;share_n=0
    for code,a in actual.items():
        if country_key(a["country"])=="Northern Ireland": continue
        row=rows.get(code)
        if row is None: raise RuntimeError(f"Missing prediction for {code}")
        candidates=[p for p in PARTIES if allowed(p,a["country"])]
        pw=max(candidates,key=lambda p:row.get(p,0.0))
        rw=a["winner"] or "other"
        pred[pw]+=1;real[rw]+=1;n+=1
        if pw==rw:
            correct+=1;by_region[zone_key(a)][0]+=1
        by_region[zone_key(a)][1]+=1
        truth=local_shares(a)
        for p in candidates:
            share_abs+=abs(row.get(p,0.0)-truth.get(p,0.0));share_n+=1
    if n!=632: raise RuntimeError(f"Expected 632 GB seats, got {n}")
    seat_error={p:int(pred[p]-real[p]) for p in PARTIES}
    abs_error=sum(abs(x) for x in seat_error.values())
    return {
        "winner_accuracy":correct/n,"correct_winners":correct,"gb_seats":n,
        "predicted_seats":{p:int(pred[p]) for p in PARTIES},
        "actual_seats":{p:int(real[p]) for p in PARTIES},
        "seat_error":seat_error,"seat_abs_error_sum":int(abs_error),
        "share_mae":share_abs/share_n if share_n else None,
        "regional_accuracy":{
            r:{"correct":v[0],"n":v[1],"accuracy":v[0]/v[1] if v[1] else None}
            for r,v in sorted(by_region.items())
        }
    }


def evaluate_partial(
    baseline:dict[str,dict[str,Any]],actual:dict[str,dict[str,Any]],alpha:float
)->dict[str,Any]:
    target=shares_from_seats(actual)
    return evaluate_rows(partial_raked_rows(baseline,target,alpha),actual)


def fit_rake_strength(
    train_cycles:list[tuple[str,dict[str,Any],dict[str,Any]]]
)->tuple[float,dict[str,Any],list[dict[str,Any]]]:
    """Select alpha on TRAIN only, favouring balanced performance across cycles."""
    candidates=[]
    best=None
    for alpha in RAKE_ALPHA_GRID:
        results=[evaluate_partial(b,a,alpha) for _,b,a in train_cycles]
        # Conservative criterion: protect the weaker training election first,
        # then total winner accuracy, then seat error, then share MAE. If tied,
        # prefer less raking / less model intervention.
        score=(
            min(r["correct_winners"] for r in results),
            sum(r["correct_winners"] for r in results),
            -sum(r["seat_abs_error_sum"] for r in results),
            -sum((r["share_mae"] or 999) for r in results),
            -alpha,
        )
        candidates.append({
            "alpha":alpha,
            "combined_correct":sum(r["correct_winners"] for r in results),
            "combined_seat_abs_error":sum(r["seat_abs_error_sum"] for r in results),
            "mean_share_mae":sum((r["share_mae"] or 0) for r in results)/len(results),
        })
        item=(score,alpha,results)
        if best is None or item[0]>best[0]: best=item
    assert best is not None
    _,alpha,results=best
    return alpha,{
        "cycles":{label:r for (label,_,_),r in zip(train_cycles,results)},
        "combined_correct":sum(r["correct_winners"] for r in results),
        "combined_seat_abs_error":sum(r["seat_abs_error_sum"] for r in results),
        "mean_share_mae":sum((r["share_mae"] or 0) for r in results)/len(results),
    },candidates


def main()->int:
    with tempfile.TemporaryDirectory() as td:
        db=Path(td)/"psephology.db";download_db(db)
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
                if len(seats)!=650: raise RuntimeError(f"{k}: expected 650 seats, got {len(seats)}")

            train=[
                ("2010→2015",elections["2010"],elections["2015"]),
                ("2015→2017",elections["2015"],elections["2017"]),
            ]
            common={p:COMMON_LAMBDA for p in FIT_PARTIES}
            train_common=[evaluate(b,a,common,None,0) for _,b,a in train]
            val_common=evaluate(elections["2017"],elections["2019"],common,None,0)
            hold_common=evaluate(elections["2019N"],elections["2024"],common,None,0)

            alpha,train_partial,alpha_grid=fit_rake_strength(train)
            val_partial=evaluate_partial(elections["2017"],elections["2019"],alpha)
            hold_partial=evaluate_partial(elections["2019N"],elections["2024"],alpha)

            # Keep endpoints as transparent diagnostics.
            val_unraked=evaluate_partial(elections["2017"],elections["2019"],0.0)
            hold_unraked=evaluate_partial(elections["2019N"],elections["2024"],0.0)
            val_full=evaluate_partial(elections["2017"],elections["2019"],1.0)
            hold_full=evaluate_partial(elections["2019N"],elections["2024"],1.0)

            approved=model_gate(val_common,val_partial,hold_common,hold_partial)

            params={
                "version":"uk-v07-partial-raking",
                "model_type":"partial-raked-v1",
                "approved":approved,
                "training_elections":["2010→2015","2015→2017"],
                "validation_election":"2017→2019",
                "holdout_election":"2019 notional→2024",
                "common_lambda":COMMON_LAMBDA,
                "rake_strength":round(alpha,3),
                "rake_iterations":RAKE_ITERATIONS,
                "validation":{
                    "common_accuracy":val_common["winner_accuracy"],
                    "partial_accuracy":val_partial["winner_accuracy"],
                    "full_accuracy":val_full["winner_accuracy"],
                    "common_seat_abs_error":val_common["seat_abs_error_sum"],
                    "partial_seat_abs_error":val_partial["seat_abs_error_sum"],
                    "full_seat_abs_error":val_full["seat_abs_error_sum"],
                    "partial_share_mae":val_partial["share_mae"],
                },
                "holdout":{
                    "common_accuracy":hold_common["winner_accuracy"],
                    "partial_accuracy":hold_partial["winner_accuracy"],
                    "full_accuracy":hold_full["winner_accuracy"],
                    "common_seat_abs_error":hold_common["seat_abs_error_sum"],
                    "partial_seat_abs_error":hold_partial["seat_abs_error_sum"],
                    "full_seat_abs_error":hold_full["seat_abs_error_sum"],
                    "partial_share_mae":hold_partial["share_mae"],
                },
                "note":(
                    "Rake strength is selected only on 2010→2015 and 2015→2017. "
                    "alpha=0 is no raking; alpha=1 is full raking. Live use requires "
                    "non-worsening winner accuracy AND seat error on unseen 2019 and 2024."
                ),
            }
            PARAMS_OUT.write_text(json.dumps(params,ensure_ascii=False,indent=2),encoding="utf-8")

            payload={
                "meta":{
                    "stage":"v0.7 partial national raking",
                    "source":"UK Parliament psephology database",
                    "polling_error_included":False,
                    "production_rule":"alpha trained on 2015/2017; strict non-worsening gate on both 2019 and 2024",
                    "interpretation":"alpha linearly blends constituency shares between the unraked proportional centre and the fully nationally-raked centre",
                },
                "baseline_common":{
                    "lambda":COMMON_LAMBDA,
                    "training":{label:r for (label,_,_),r in zip(train,train_common)},
                    "validation_2019":val_common,"holdout_2024":hold_common,
                },
                "partial_raking_candidate":{
                    "selected_alpha":alpha,
                    "training":train_partial,
                    "validation_2019":val_partial,
                    "holdout_2024":hold_partial,
                    "alpha_grid_training":alpha_grid,
                },
                "endpoint_diagnostics":{
                    "unraked_alpha_0":{"validation_2019":val_unraked,"holdout_2024":hold_unraked},
                    "full_raking_alpha_1":{"validation_2019":val_full,"holdout_2024":hold_full},
                },
                "approved_for_live":approved,
            }
            OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")

            print("Selected partial-raking alpha (TRAIN only):",alpha)
            print("2019 validation:",f"common={val_common['winner_accuracy']:.2%}/{val_common['seat_abs_error_sum']}",f"partial={val_partial['winner_accuracy']:.2%}/{val_partial['seat_abs_error_sum']}",f"full={val_full['winner_accuracy']:.2%}/{val_full['seat_abs_error_sum']}")
            print("2024 holdout:",f"common={hold_common['winner_accuracy']:.2%}/{hold_common['seat_abs_error_sum']}",f"partial={hold_partial['winner_accuracy']:.2%}/{hold_partial['seat_abs_error_sum']}",f"full={hold_full['winner_accuracy']:.2%}/{hold_full['seat_abs_error_sum']}")
            print("Approved partial-raking model for live:",approved)
        finally:
            conn.close()
    return 0


if __name__=="__main__":
    try: raise SystemExit(main())
    except Exception as exc:
        print(f"build_backtest.py failed: {exc}",file=sys.stderr)
        raise
