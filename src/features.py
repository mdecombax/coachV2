"""Features par partie + base de référence glissante.

On enregistre, pour CHAQUE partie analysée, un vecteur de features riche
(`data/game_features.jsonl`) : qualité (ACPL), erreurs par gravité/motif/phase,
impulsivité, horloge (zeitnot, temps moyen, temps final), résultat, ratings...

La base de référence (`rolling_baseline`) agrège les N dernières parties → c'est
la "normale du joueur", qui sert d'étalon au coaching. Elle est recalculée à
chaque run (fenêtre glissante) pour suivre le niveau réel.

Aucun moteur : on lit le cache d'analyse + les horloges du PGN.
"""
import io
import json
from collections import Counter

import chess.pgn

import config
from analyze import parse_clocks, parse_time_control, think_times, game_id as game_id_of

FEATURES_FILE = config.DATA_DIR / "game_features.jsonl"
MOTIFS = ["piece_pendue", "mat_rate", "mat_permis", "gain_manque", "erreur_positionnelle"]


CP_CAP = 1000   # plafond de perte par coup pour l'ACPL


def _capped_acpl(meta: dict, blunders: list) -> float | None:
    """ACPL avec perte par coup plafonnée à CP_CAP, déduit sans réanalyser :
    total_cp_loss (non plafonné) - somme des dépassements au-delà du plafond."""
    n = meta.get("n_user_moves")
    total = meta.get("total_cp_loss")
    if not n or total is None:
        return None
    overflow = sum(max(b["cp_loss"] - CP_CAP, 0) for b in blunders)
    return round((total - overflow) / n, 1)


def _raw_games_map():
    m = {}
    for f in sorted(config.RAW_DIR.glob("*.json")):
        for g in json.loads(f.read_text()).get("games", []):
            m[game_id_of(g)] = g
    return m


def compute_game_features(meta: dict, blunders: list, raw: dict | None) -> dict:
    errs = [b for b in blunders if b["severity"] in ("erreur", "gaffe")]
    motif_c = Counter(b["motif"] for b in errs)
    phase_c = Counter(b["phase"] for b in errs)

    feat = {
        "game_id": meta["game_id"], "date": meta["date"], "timestamp": meta["timestamp"],
        "time_class": meta["time_class"], "time_control": meta.get("time_control"),
        "my_color": meta["my_color"], "my_rating": meta["my_rating"],
        "opp_rating": meta.get("opp_rating"), "result": meta["result"],
        "n_moves": meta["n_moves"], "n_user_moves": meta.get("n_user_moves"),
        # ACPL plafonné à 1000cp/coup : un mat raté (~9000) ne fausse pas la moyenne.
        "acpl": _capped_acpl(meta, blunders),
        # erreurs par gravité
        "n_inaccuracy": sum(1 for b in blunders if b["severity"] == "imprecision"),
        "n_mistake": sum(1 for b in blunders if b["severity"] == "erreur"),
        "n_blunder": sum(1 for b in blunders if b["severity"] == "gaffe"),
        "n_errors": len(errs),
        "impulsive_errors": sum(1 for b in errs if b["impulsive"]),
        # erreurs par phase
        "err_ouverture": phase_c.get("ouverture", 0),
        "err_milieu": phase_c.get("milieu", 0),
        "err_finale": phase_c.get("finale", 0),
    }
    for m in MOTIFS:
        feat["m_" + m] = motif_c.get(m, 0)

    # --- features d'horloge (depuis le PGN) ---
    avg_think = zeitnot = final_clock = None
    lost_on_time = False
    if raw and raw.get("pgn"):
        game = chess.pgn.read_game(io.StringIO(raw["pgn"]))
        if game is not None:
            clocks = parse_clocks(game)
            base, inc = parse_time_control(raw.get("time_control"))
            tt = think_times(clocks, base, inc)
            user_white = meta["my_color"] == "blanc"
            user_plies = [i for i in range(len(clocks)) if (i % 2 == 0) == user_white]
            thinks = [tt[i] for i in user_plies if i < len(tt) and tt[i] is not None]
            rems = [clocks[i] for i in user_plies if clocks[i] is not None]
            if thinks:
                avg_think = round(sum(thinks) / len(thinks), 1)
            zeitnot = sum(1 for r in rems if r < 60)
            if rems:
                final_clock = rems[-1]
        side = "white" if meta["my_color"] == "blanc" else "black"
        if raw.get(side, {}).get("result") == "timeout":
            lost_on_time = True

    feat["avg_think_s"] = avg_think
    feat["zeitnot_moves"] = zeitnot
    feat["final_clock_s"] = final_clock
    feat["lost_on_time"] = lost_on_time
    return feat


def build() -> list[dict]:
    """(Re)construit data/game_features.jsonl depuis le cache d'analyse complet."""
    raw = _raw_games_map()
    rows = []
    for f in sorted(config.ANALYSIS_DIR.glob("*.json")):
        payload = json.loads(f.read_text())
        meta = payload["meta"]
        rows.append(compute_game_features(meta, payload["blunders"], raw.get(meta["game_id"])))
    rows.sort(key=lambda r: r["timestamp"])
    FEATURES_FILE.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
    return rows


def load() -> list[dict]:
    if not FEATURES_FILE.exists():
        return build()
    return [json.loads(l) for l in FEATURES_FILE.read_text().splitlines() if l.strip()]


def rolling_baseline(rows: list[dict], n: int = 50, time_class: str = "rapid") -> dict:
    """Moyennes sur les N dernières parties = la 'normale' du joueur."""
    r = sorted((x for x in rows if x["time_class"] == time_class),
               key=lambda x: x["timestamp"])
    w = r[-n:]
    k = len(w) or 1

    def avg(key):
        vals = [x[key] for x in w if x.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    return {
        "n_games": len(w),
        "acpl": avg("acpl"),
        "errors_per_game": avg("n_errors"),
        "gaffes_per_game": avg("n_blunder"),
        "impulsive_per_game": avg("impulsive_errors"),
        "zeitnot_per_game": avg("zeitnot_moves"),
        "avg_think_s": avg("avg_think_s"),
        "win_rate": round(sum(1 for x in w if x["result"] == "victoire") / k, 2),
        "avg_rating": avg("my_rating"),
        "motif_rates": {m: round(sum(x["m_" + m] for x in w) / k, 3) for m in MOTIFS},
    }


def features_by_id() -> dict:
    return {r["game_id"]: r for r in load()}


if __name__ == "__main__":
    rows = build()
    base = rolling_baseline(rows)
    print(f"{len(rows)} parties -> {FEATURES_FILE}")
    print("Base de référence (50 dernières rapides) :")
    print(json.dumps(base, ensure_ascii=False, indent=2))
