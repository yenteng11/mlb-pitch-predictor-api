from __future__ import annotations

import csv
import io
import math
import os
import time
from collections import Counter, defaultdict
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
MLB_PLAYERS_URL = "https://statsapi.mlb.com/api/v1/sports/1/players"
SAVANT_URL = "https://baseballsavant.mlb.com/statcast_search/csv"

app = FastAPI(title="MLB Pitch Predictor")

# Public read-only API. Restrict this in production by setting ALLOWED_ORIGINS
# to a comma-separated list such as https://yourusername.github.io,https://yourdomain.com
allowed_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

PITCH_NAMES = {
    "FF": "4-Seam Fastball",
    "SI": "Sinker",
    "FC": "Cutter",
    "SL": "Slider",
    "ST": "Sweeper",
    "CU": "Curveball",
    "KC": "Knuckle Curve",
    "CH": "Changeup",
    "FS": "Splitter",
    "FO": "Forkball",
    "SV": "Slurve",
    "SC": "Screwball",
    "KN": "Knuckleball",
    "EP": "Eephus",
    "CS": "Slow Curve",
    "PO": "Pitchout",
}

# Tiny in-memory cache so repeated count/hand changes do not hammer Savant.
_pitch_cache: dict[tuple[int, int], tuple[float, list[dict[str, Any]]]] = {}
CACHE_SECONDS = 60 * 30


def current_season() -> int:
    return date.today().year


@lru_cache(maxsize=8)
def get_pitchers(season: int) -> list[dict[str, Any]]:
    try:
        response = requests.get(
            MLB_PLAYERS_URL,
            params={"season": season, "gameType": "R"},
            timeout=20,
            headers={"User-Agent": "MLB-Pitch-Predictor/1.0"},
        )
        response.raise_for_status()
        people = response.json().get("people", [])
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"MLB player list unavailable: {exc}") from exc

    pitchers = []
    for p in people:
        pos = (p.get("primaryPosition") or {}).get("abbreviation", "")
        # MLB uses P, SP, RP and two-way player variants depending on endpoint state.
        if pos in {"P", "SP", "RP"} or "Pitcher" in (p.get("primaryPosition") or {}).get("name", ""):
            pitchers.append({
                "id": p.get("id"),
                "name": p.get("fullName"),
                "team": (p.get("currentTeam") or {}).get("name"),
                "throws": (p.get("pitchHand") or {}).get("code"),
            })
    pitchers.sort(key=lambda x: (x["name"] or ""))
    return pitchers


def fetch_savant_pitcher(pitcher_id: int, season: int) -> list[dict[str, Any]]:
    key = (pitcher_id, season)
    cached = _pitch_cache.get(key)
    now = time.time()
    if cached and now - cached[0] < CACHE_SECONDS:
        return cached[1]

    params = {
        "all": "true",
        "hfPT": "",
        "hfAB": "",
        "hfBBT": "",
        "hfPR": "",
        "hfZ": "",
        "stadium": "",
        "hfBBL": "",
        "hfNewZones": "",
        "hfGT": "R|PO|S|",
        "hfC": "",
        "hfSea": f"{season}|",
        "hfSit": "",
        "player_type": "pitcher",
        "hfOuts": "",
        "opponent": "",
        "pitcher_throws": "",
        "batter_stands": "",
        "hfSA": "",
        "game_date_gt": "",
        "game_date_lt": "",
        "pitchers_lookup[]": str(pitcher_id),
        "team": "",
        "position": "",
        "hfRO": "",
        "home_road": "",
        "hfFlag": "",
        "metric_1": "",
        "hfInn": "",
        "min_pitches": "0",
        "min_results": "0",
        "group_by": "name",
        "sort_col": "pitches",
        "player_event_sort": "api_p_release_speed",
        "sort_order": "desc",
        "min_abs": "0",
        "type": "details",
    }

    try:
        response = requests.get(
            SAVANT_URL,
            params=params,
            timeout=45,
            headers={
                "User-Agent": "Mozilla/5.0 MLB-Pitch-Predictor/1.0",
                "Accept": "text/csv,*/*;q=0.8",
            },
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Baseball Savant unavailable: {exc}") from exc

    text = response.text.lstrip("\ufeff").strip()
    if not text or "pitch_type" not in text.splitlines()[0]:
        raise HTTPException(status_code=502, detail="Baseball Savant returned an unexpected response.")

    rows = list(csv.DictReader(io.StringIO(text)))
    # Savant can occasionally return blanks / non-pitch records.
    rows = [r for r in rows if r.get("pitch_type") and r.get("balls") not in (None, "") and r.get("strikes") not in (None, "")]
    _pitch_cache[key] = (now, rows)
    return rows


def safe_float(value: Any) -> float | None:
    try:
        if value in (None, "", "null", "None"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(r["pitch_type"] for r in rows)
    speeds: dict[str, list[float]] = defaultdict(list)
    spins: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        pt = r["pitch_type"]
        v = safe_float(r.get("release_speed"))
        s = safe_float(r.get("release_spin_rate"))
        if v is not None:
            speeds[pt].append(v)
        if s is not None:
            spins[pt].append(s)

    total = sum(counts.values())
    result = []
    for pt, n in counts.most_common():
        result.append({
            "code": pt,
            "name": PITCH_NAMES.get(pt, pt),
            "count": n,
            "probability": round(100 * n / total, 1) if total else 0,
            "avg_velocity": round(sum(speeds[pt]) / len(speeds[pt]), 1) if speeds[pt] else None,
            "avg_spin": round(sum(spins[pt]) / len(spins[pt])) if spins[pt] else None,
        })
    return result


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/pitchers")
def pitchers(season: int = Query(default_factory=current_season, ge=2015, le=2100)):
    return {"season": season, "pitchers": get_pitchers(season)}


@app.get("/api/predict")
def predict(
    pitcher_id: int,
    batter_stands: str = Query(pattern="^[LR]$"),
    balls: int = Query(ge=0, le=3),
    strikes: int = Query(ge=0, le=2),
    season: int = Query(default_factory=current_season, ge=2015, le=2100),
):
    rows = fetch_savant_pitcher(pitcher_id, season)

    hand_rows = [r for r in rows if r.get("stand") == batter_stands]
    exact = [
        r for r in hand_rows
        if int(r.get("balls", -1)) == balls and int(r.get("strikes", -1)) == strikes
    ]

    # Exact split is the primary prediction. We also return a larger hand-only baseline
    # to show how much the count changes the pitcher's tendencies.
    exact_summary = summarize(exact)
    hand_summary = summarize(hand_rows)

    # Confidence is intentionally simple and transparent: based on exact-split sample size.
    n = len(exact)
    confidence = "high" if n >= 80 else "medium" if n >= 30 else "low"

    pitcher_name = next((r.get("player_name") for r in rows if r.get("player_name")), None)
    return {
        "pitcher_id": pitcher_id,
        "pitcher_name": pitcher_name,
        "season": season,
        "batter_stands": batter_stands,
        "balls": balls,
        "strikes": strikes,
        "sample_size": n,
        "hand_sample_size": len(hand_rows),
        "confidence": confidence,
        "pitches": exact_summary,
        "hand_baseline": hand_summary,
        "method": "Observed pitch frequency for this pitcher, batter side, and count in Baseball Savant Statcast data.",
    }


@app.get("/health")
def health():
    return {"status": "ok"}
