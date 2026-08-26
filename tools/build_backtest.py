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
                if len(seats)!=650:
                    raise RuntimeError(f"{k}: expected 650 seats, got {len(seats)}")

            train=[
                ("2010→2015",elections["2010"],elections["2015"]),
                ("2015→2017",elections["2015"],elections["2017"]),
            ]
            common={p:COMMON_LAMBDA for p in FIT_PARTIES}

            # Baseline comparator: same lambda everywhere, no geographic sensitivity.
            train_common=[evaluate(b,a,common,None,0) for _,b,a in train]
            val_common=evaluate(elections["2017"],elections["2019"],common,None,0)
            hold_common=evaluate(elections["2019N"],elections["2024"],common,None,0)

            # v0.4-style party-only candidate (reported for diagnosis, never preferred
            # over the hierarchical candidate unless the latter fails internally).
            party_lambdas,party_prior,party_train=fit_party_params(train,None)
            val_party=evaluate(elections["2017"],elections["2019"],party_lambdas,None,party_prior)
            hold_party=evaluate(elections["2019N"],elections["2024"],party_lambdas,None,party_prior)

            # v0.5 hierarchical candidate.
            lambdas,regional_betas,prior,ridge,train_hier=fit_hierarchical(train)
            val_hier=evaluate(elections["2017"],elections["2019"],lambdas,regional_betas,prior)
            hold_hier=evaluate(elections["2019N"],elections["2024"],lambdas,regional_betas,prior)

            # Diagnostics only: actual country target shares show the theoretical
            # gain available from perfect country-level information.
            hold_country=evaluate(
                elections["2019N"],elections["2024"],
                lambdas,regional_betas,prior,country_oracle=True
            )

            approved=model_gate(val_common,val_hier,hold_common,hold_hier)

            params={
                "version":"uk-v05-hierarchical-territorial",
                "approved":approved,
                "training_elections":["2010→2015","2015→2017"],
                "validation_election":"2017→2019",
                "holdout_election":"2019 notional→2024",
                "common_lambda":COMMON_LAMBDA,
                "lambdas":{p:round(lambdas[p],4) for p in FIT_PARTIES},
                "regional_beta":{
                    z:{p:round(v,4) for p,v in row.items()}
                    for z,row in regional_betas.items()
                },
                "regional_ridge":ridge,
                "ref_missing_prior":round(prior,4),
                "validation":{
                    "common_accuracy":val_common["winner_accuracy"],
                    "hierarchical_accuracy":val_hier["winner_accuracy"],
                    "common_seat_abs_error":val_common["seat_abs_error_sum"],
                    "hierarchical_seat_abs_error":val_hier["seat_abs_error_sum"],
                },
                "holdout":{
                    "common_accuracy":hold_common["winner_accuracy"],
                    "hierarchical_accuracy":hold_hier["winner_accuracy"],
                    "common_seat_abs_error":hold_common["seat_abs_error_sum"],
                    "hierarchical_seat_abs_error":hold_hier["seat_abs_error_sum"],
                },
                "note":(
                    "Live use only when approved=true. Regional betas are learned on "
                    "2010→2015 and 2015→2017 only; 2019 and 2024 are unseen gates. "
                    "Current Scotland/Wales polling is a separate live-data layer in app.js."
                )
            }
            PARAMS_OUT.write_text(json.dumps(params,ensure_ascii=False,indent=2),encoding="utf-8")

            payload={
                "meta":{
                    "stage":"v0.5 hierarchical territorial calibration",
                    "source":"UK Parliament psephology database",
                    "polling_error_included":False,
                    "production_rule":(
                        "train on 2015/2017; hierarchical party+region model must not "
                        "worsen accuracy or seat error on either 2019 validation or 2024 holdout"
                    )
                },
                "baseline_common":{
                    "lambda":COMMON_LAMBDA,
                    "training":{label:r for (label,_,_),r in zip(train,train_common)},
                    "validation_2019":val_common,
                    "holdout_2024":hold_common,
                },
                "party_only_candidate":{
                    "lambdas":party_lambdas,
                    "ref_missing_prior":party_prior,
                    "training":party_train,
                    "validation_2019":val_party,
                    "holdout_2024":hold_party,
                },
                "hierarchical_candidate":{
                    "lambdas":lambdas,
                    "regional_beta":regional_betas,
                    "regional_ridge":ridge,
                    "ref_missing_prior":prior,
                    "training":train_hier,
                    "validation_2019":val_hier,
                    "holdout_2024":hold_hier,
                    "holdout_2024_country_oracle":hold_country,
                },
                "approved_for_live":approved
            }
            OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")

            print("Hierarchical lambdas:",json.dumps(lambdas,sort_keys=True))
            print("Regional ridge:",ridge)
            print("Reform missing-seat prior:",prior)
            print(
                "2019 validation:",
                f"common={val_common['winner_accuracy']:.2%}/{val_common['seat_abs_error_sum']}",
                f"party={val_party['winner_accuracy']:.2%}/{val_party['seat_abs_error_sum']}",
                f"hier={val_hier['winner_accuracy']:.2%}/{val_hier['seat_abs_error_sum']}"
            )
            print(
                "2024 holdout:",
                f"common={hold_common['winner_accuracy']:.2%}/{hold_common['seat_abs_error_sum']}",
                f"party={hold_party['winner_accuracy']:.2%}/{hold_party['seat_abs_error_sum']}",
                f"hier={hold_hier['winner_accuracy']:.2%}/{hold_hier['seat_abs_error_sum']}"
            )
            print(
                "2024 country-oracle diagnostic:",
                f"{hold_country['winner_accuracy']:.2%}/{hold_country['seat_abs_error_sum']}"
            )
            print("Approved for live:",approved)
        finally:
            conn.close()
    return 0


if __name__=="__main__":
    try:raise SystemExit(main())
    except Exception as exc:
        print(f"build_backtest.py failed: {exc}",file=sys.stderr)
        raise
