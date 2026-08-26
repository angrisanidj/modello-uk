#!/usr/bin/env python3
"""
UK territorial calibration v0.4.

Strict sequence:
  TRAIN:    2010 -> 2015, 2015 -> 2017
  VALIDATE: 2017 -> 2019
  HOLDOUT:  2019 notional (2024 boundaries) -> 2024

All stages use the ACTUAL target GB vote, so this still isolates seat conversion
from polling error. The live model may use fitted party elasticities only if the
same parameters improve both the 2019 validation and the untouched 2024 holdout.

A separate 2024 "country oracle" diagnostic uses actual England/Scotland/Wales
target shares only to measure how much subnational polling could potentially add.
It is never approved for live use from this test.
"""
from __future__ import annotations

import json
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


def shares_from_seats(seats:dict[str,dict[str,Any]],country:str|None=None)->dict[str,float]:
    totals=Counter()
    for seat in seats.values():
        ck=country_key(seat["country"])
        if ck=="Northern Ireland":continue
        if country is not None and ck!=country:continue
        totals.update(seat["votes"])
    denom=sum(totals.values())
    if not denom:raise RuntimeError(f"No votes for {country or 'GB'}")
    return {p:totals[p]/denom*100 for p in PARTIES}


def local_shares(seat:dict[str,Any])->dict[str,float]:
    total=sum(seat["votes"].values())
    return {p:(seat["votes"].get(p,0)/total*100 if total else 0) for p in PARTIES}


def allowed(p:str,country:str)->bool:
    c=country.lower()
    if p=="snp":return "scotland" in c
    if p=="pc":return "wales" in c
    return True


def project_winner(
    seat:dict[str,Any],
    base_nat:dict[str,float],
    target_nat:dict[str,float],
    lambdas:dict[str,float],
    ref_missing_prior:float=0.0
)->str:
    base=local_shares(seat)
    raw={}
    for p in PARTIES:
        if not allowed(p,seat["country"]):
            raw[p]=0.0;continue
        if p=="other":
            raw[p]=max(base.get(p,0),FLOOR_SMALL);continue
        bn=max(base_nat.get(p,0),.05)
        tn=max(target_nat.get(p,0),.05)
        b=base.get(p,0)
        # Historical UKIP/Brexit/Reform often did not contest every seat.
        # Only fill truly missing baselines; never flatten an observed local share.
        if p=="ref" and b<FLOOR_MAIN and ref_missing_prior>0:
            b=max(b,bn*ref_missing_prior)
        b=max(b,FLOOR_MAIN if p in {"lab","con","ref","ld","green"} else FLOOR_SMALL)
        raw[p]=b*(max(.08,tn/bn)**lambdas.get(p,COMMON_LAMBDA))
    return max(raw,key=raw.get)


def evaluate(
    baseline:dict[str,dict[str,Any]],
    actual:dict[str,dict[str,Any]],
    lambdas:dict[str,float],
    ref_missing_prior:float=0.0,
    country_oracle:bool=False
)->dict[str,Any]:
    gb_base=shares_from_seats(baseline)
    gb_target=shares_from_seats(actual)
    base_country={c:shares_from_seats(baseline,c) for c in ("England","Scotland","Wales")}
    target_country={c:shares_from_seats(actual,c) for c in ("England","Scotland","Wales")}

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
        pw=project_winner(b,bn,tn,lambdas,ref_missing_prior)
        rw=a["winner"] or "other"
        pred[pw]+=1;real[rw]+=1;n+=1
        if pw==rw:
            correct+=1;by_region[a["region"]][0]+=1
        by_region[a["region"]][1]+=1
    if missing:raise RuntimeError(f"{len(missing)} missing baseline seats, e.g. {missing[:8]}")
    if n!=632:raise RuntimeError(f"Expected 632 GB seats, got {n}")
    seat_error={p:int(pred[p]-real[p]) for p in PARTIES}
    abs_error=sum(abs(x) for x in seat_error.values())
    return {
        "winner_accuracy":correct/n,"correct_winners":correct,"gb_seats":n,
        "predicted_seats":{p:int(pred[p]) for p in PARTIES},
        "actual_seats":{p:int(real[p]) for p in PARTIES},
        "seat_error":seat_error,"seat_abs_error_sum":int(abs_error),
        "regional_accuracy":{
            r:{"correct":v[0],"n":v[1],"accuracy":v[0]/v[1] if v[1] else None}
            for r,v in sorted(by_region.items())
        }
    }


def combine_score(results:list[dict[str,Any]])->tuple[int,int]:
    return (sum(r["correct_winners"] for r in results),
            -sum(r["seat_abs_error_sum"] for r in results))


def fit(train_cycles:list[tuple[str,dict[str,Any],dict[str,Any]]])->tuple[dict[str,float],float,dict[str,Any]]:
    lambdas={p:COMMON_LAMBDA for p in FIT_PARTIES}
    prior=0.0

    def results_for(ls,pr):
        return [evaluate(b,a,ls,pr) for _,b,a in train_cycles]

    # Two conservative coordinate-descent passes. The parameters never see
    # either the 2019 validation or the 2024 holdout.
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
            if score>best[0]:best=(score,candidate)
        prior=best[1]

    train_results=results_for(lambdas,prior)
    return lambdas,prior,{
        "cycles":{label:r for (label,_,_),r in zip(train_cycles,train_results)},
        "combined_correct":sum(r["correct_winners"] for r in train_results),
        "combined_seat_abs_error":sum(r["seat_abs_error_sum"] for r in train_results),
    }


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
            common_train=[evaluate(b,a,common,0) for _,b,a in train]

            lambdas,prior,train_fit=fit(train)

            val_common=evaluate(elections["2017"],elections["2019"],common,0)
            val_fit=evaluate(elections["2017"],elections["2019"],lambdas,prior)
            hold_common=evaluate(elections["2019N"],elections["2024"],common,0)
            hold_fit=evaluate(elections["2019N"],elections["2024"],lambdas,prior)
            hold_country=evaluate(elections["2019N"],elections["2024"],lambdas,prior,True)

            # Production gate: the fitted model must not trade one validation
            # metric for another. On BOTH unseen elections it must be at least
            # as good as the common-lambda baseline on constituency accuracy
            # AND aggregate seat error, with at least one strict improvement.
            val_ok=(
                val_fit["winner_accuracy"]>=val_common["winner_accuracy"]
                and val_fit["seat_abs_error_sum"]<=val_common["seat_abs_error_sum"]
            )
            hold_ok=(
                hold_fit["winner_accuracy"]>=hold_common["winner_accuracy"]
                and hold_fit["seat_abs_error_sum"]<=hold_common["seat_abs_error_sum"]
            )
            strict_improvement=(
                val_fit["winner_accuracy"]>val_common["winner_accuracy"]
                or val_fit["seat_abs_error_sum"]<val_common["seat_abs_error_sum"]
                or hold_fit["winner_accuracy"]>hold_common["winner_accuracy"]
                or hold_fit["seat_abs_error_sum"]<hold_common["seat_abs_error_sum"]
            )
            approved=val_ok and hold_ok and strict_improvement

            params={
                "version":"uk-v04-historical-calibration",
                "approved":approved,
                "training_elections":["2010→2015","2015→2017"],
                "validation_election":"2017→2019",
                "holdout_election":"2019 notional→2024",
                "lambdas":{p:round(lambdas[p],3) for p in FIT_PARTIES},
                "ref_missing_prior":round(prior,3),
                "validation":{
                    "common_accuracy":val_common["winner_accuracy"],
                    "fitted_accuracy":val_fit["winner_accuracy"],
                    "common_seat_abs_error":val_common["seat_abs_error_sum"],
                    "fitted_seat_abs_error":val_fit["seat_abs_error_sum"],
                },
                "holdout":{
                    "common_accuracy":hold_common["winner_accuracy"],
                    "fitted_accuracy":hold_fit["winner_accuracy"],
                    "common_seat_abs_error":hold_common["seat_abs_error_sum"],
                    "fitted_seat_abs_error":hold_fit["seat_abs_error_sum"],
                },
                "note":"Live use is allowed only when approved=true. Country-oracle diagnostics are never live parameters."
            }
            PARAMS_OUT.write_text(json.dumps(params,ensure_ascii=False,indent=2),encoding="utf-8")

            payload={
                "meta":{
                    "stage":"v0.4 historical territorial calibration",
                    "source":"UK Parliament psephology database",
                    "polling_error_included":False,
                    "production_rule":"fit on 2015/2017; require non-worsening winner accuracy AND seat error on both 2019 validation and 2024 holdout, plus at least one strict improvement"
                },
                "common_lambda":COMMON_LAMBDA,
                "training_common":{
                    label:r for (label,_,_),r in zip(train,common_train)
                },
                "training_fitted":train_fit,
                "fitted_parameters":{"lambdas":lambdas,"ref_missing_prior":prior},
                "validation_2019":{"common":val_common,"fitted":val_fit},
                "holdout_2024":{"common":hold_common,"fitted":hold_fit},
                "holdout_2024_country_oracle":hold_country,
                "approved_for_live":approved
            }
            OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")

            print("Fitted lambdas:",json.dumps(lambdas,sort_keys=True))
            print("Reform missing-seat prior:",prior)
            print(
                "2019 validation:",
                f"common={val_common['winner_accuracy']:.2%}/{val_common['seat_abs_error_sum']}",
                f"fitted={val_fit['winner_accuracy']:.2%}/{val_fit['seat_abs_error_sum']}"
            )
            print(
                "2024 holdout:",
                f"common={hold_common['winner_accuracy']:.2%}/{hold_common['seat_abs_error_sum']}",
                f"fitted={hold_fit['winner_accuracy']:.2%}/{hold_fit['seat_abs_error_sum']}"
            )
            print(
                "2024 country-oracle ceiling:",
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
