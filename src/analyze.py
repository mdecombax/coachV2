"""Analyse Stockfish des parties : détection + enrichissement des blunders.

Principe : on évalue CHAQUE position de la partie une seule fois (cache par
partie). Pour chaque coup joué par le joueur, on en déduit :
    perte_cp = eval(meilleur_coup) - eval(coup_joué)
puis on enrichit le blunder avec un maximum de features (motif, pièce pendue,
tactique ratée, temps passé, bascule de partie...).

Usage:
    python src/analyze.py                 # tout l'historique (incrémental)
    python src/analyze.py --since 2026/03  # à partir d'un mois
    python src/analyze.py --limit 5        # seulement 5 parties (test rapide)
    python src/analyze.py --depth 12       # profondeur Stockfish
"""
import io
import re
import sys
import json
import argparse
import datetime as dt

import chess
import chess.pgn
import chess.engine

import config

# Valeurs matérielles classiques (le roi n'a pas de valeur d'échange).
PIECE_VALUE = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0,
}
PIECE_NAME_FR = {
    chess.PAWN: "pion", chess.KNIGHT: "cavalier", chess.BISHOP: "fou",
    chess.ROOK: "tour", chess.QUEEN: "dame", chess.KING: "roi",
}

CLOCK_RE = re.compile(r"\[%clk\s+(\d+):(\d+):(\d+(?:\.\d+)?)\]")


def parse_time_control(tc: str | None) -> tuple[int | None, int]:
    """'900+10' -> (900, 10) · '600' -> (600, 0) · '1/86400' (daily) -> (None, 0)."""
    if not tc:
        return None, 0
    if "/" in tc:           # correspondance (daily) : temps/coup non pertinent
        return None, 0
    if "+" in tc:
        base, inc = tc.split("+")
        return int(base), int(inc)
    try:
        return int(tc), 0
    except ValueError:
        return None, 0


def think_times(clocks: list, base: int | None, inc: int) -> list:
    """Temps de réflexion par demi-coup, incrément compris.

    L'horloge enregistrée est APRÈS ajout de l'incrément, donc :
        réflexion = (temps restant précédent du joueur) - (restant actuel) + inc
    Pour le 600 (inc=0), résultat identique à l'ancien calcul.
    """
    times = [None] * len(clocks)
    prev = {True: base, False: base}   # restant pour blanc (True) / noir (False)
    for ply, rem in enumerate(clocks):
        mover = (ply % 2 == 0)         # les blancs jouent sur les plies pairs
        if rem is not None and prev[mover] is not None:
            times[ply] = round(max(prev[mover] - rem + inc, 0.0), 1)
        if rem is not None:
            prev[mover] = rem
    return times


# ---------------------------------------------------------------------------
# Helpers PGN / position
# ---------------------------------------------------------------------------

def parse_clocks(game: chess.pgn.Game) -> list[float]:
    """Retourne le temps restant (s) après chaque demi-coup, dans l'ordre."""
    clocks = []
    node = game
    while node.variations:
        node = node.variation(0)
        m = CLOCK_RE.search(node.comment or "")
        if m:
            h, mn, s = m.groups()
            clocks.append(int(h) * 3600 + int(mn) * 60 + float(s))
        else:
            clocks.append(None)
    return clocks


def material_balance(board: chess.Board, color: bool) -> int:
    """Balance matérielle (en points) du point de vue de `color`."""
    bal = 0
    for piece_type, val in PIECE_VALUE.items():
        bal += val * len(board.pieces(piece_type, color))
        bal -= val * len(board.pieces(piece_type, not color))
    return bal


def non_pawn_material(board: chess.Board) -> int:
    total = 0
    for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
        total += PIECE_VALUE[pt] * (len(board.pieces(pt, chess.WHITE))
                                    + len(board.pieces(pt, chess.BLACK)))
    return total


def game_phase(board: chess.Board) -> str:
    if board.fullmove_number <= 12:
        return "ouverture"
    if non_pawn_material(board) <= 14:   # ~ deux tours + un mineur chacun ou moins
        return "finale"
    return "milieu"


def score_to_cp(score: chess.engine.PovScore, color: bool) -> int:
    """Score en centipions du point de vue de `color`, mats plafonnés."""
    pov = score.pov(color)
    if pov.is_mate():
        m = pov.mate()
        if m > 0:
            return config.MATE_CP - m
        return -config.MATE_CP - m
    return pov.score()


# ---------------------------------------------------------------------------
# Analyse moteur d'une partie (avec cache)
# ---------------------------------------------------------------------------

def analyse_positions(board_moves: list[chess.Move], engine, depth: int) -> list[dict]:
    """Évalue chaque position de la partie. Retourne une liste alignée sur les
    plies : l'élément i décrit la position AVANT le i-ème demi-coup."""
    board = chess.Board()
    out = []
    for mv in board_moves:
        info = engine.analyse(board, chess.engine.Limit(depth=depth))
        pv = info.get("pv", []) or []
        out.append({
            "fen": board.fen(),
            "turn": board.turn,  # True = blanc au trait
            "cp_white": score_to_cp(info["score"], chess.WHITE),
            "best_uci": pv[0].uci() if pv else None,
            "best_san": board.san(pv[0]) if pv else None,
            "pv_uci": [m.uci() for m in pv[:8]],
        })
        board.push(mv)
    # Position finale (après le dernier coup). Si elle est terminale (mat / pat),
    # NE PAS interroger le moteur (score au signe non fiable) : on l'attribue par
    # la règle. Sinon un mat donné par le joueur passerait pour un blunder.
    if board.is_checkmate():
        # le camp au trait est maté
        cp_white = -config.MATE_CP if board.turn == chess.WHITE else config.MATE_CP
    elif board.is_stalemate() or board.is_insufficient_material() or board.can_claim_draw():
        cp_white = 0
    else:
        info = engine.analyse(board, chess.engine.Limit(depth=depth))
        cp_white = score_to_cp(info["score"], chess.WHITE)
    out.append({
        "fen": board.fen(), "turn": board.turn,
        "cp_white": cp_white,
        "best_uci": None, "best_san": None, "pv_uci": [],
    })
    return out


# ---------------------------------------------------------------------------
# Détection du motif d'un blunder
# ---------------------------------------------------------------------------

def detect_motif(board_before: chess.Board, move_played: chess.Move,
                 pos_before: dict, pos_after: dict, user: bool) -> dict:
    """Enrichit un blunder : motif, pièce pendue, tactique ratée, swing matériel."""
    enrich = {
        "motif": "imprecision", "piece_hung": None, "missed_tactic": None,
        "missed_mate_in": None, "allowed_mate_in": None, "material_swing": 0,
    }

    # Mat raté : on avait un mat, on ne l'a pas joué.
    cp_best = pos_before["cp_white"] if user == chess.WHITE else -pos_before["cp_white"]
    if cp_best >= config.MATE_CP - 50:
        enrich["motif"] = "mat_rate"
        enrich["missed_mate_in"] = config.MATE_CP - cp_best
        return enrich

    # Mat permis : après notre coup, l'adversaire a un mat.
    cp_after = pos_after["cp_white"] if user == chess.WHITE else -pos_after["cp_white"]
    if cp_after <= -config.MATE_CP + 50:
        enrich["motif"] = "mat_permis"
        enrich["allowed_mate_in"] = config.MATE_CP + cp_after
        return enrich

    # Swing matériel : on joue la réfutation de l'adversaire (PV de pos_after)
    # sur quelques demi-coups et on mesure ce qu'on perd net.
    board = board_before.copy()
    board.push(move_played)
    mat_start = material_balance(board, user)
    pv = [chess.Move.from_uci(u) for u in pos_after["pv_uci"]]
    first_capture_victim = None
    b2 = board.copy()
    for i, mv in enumerate(pv[:6]):
        if mv not in b2.legal_moves:
            break
        if b2.is_capture(mv) and first_capture_victim is None and b2.turn != user:
            victim = b2.piece_at(mv.to_square)
            if victim is not None:
                first_capture_victim = victim.piece_type
        b2.push(mv)
    mat_end = material_balance(b2, user)
    swing = mat_end - mat_start
    enrich["material_swing"] = swing

    if swing <= -2:
        enrich["motif"] = "piece_pendue"
        if first_capture_victim is not None:
            enrich["piece_hung"] = PIECE_NAME_FR[first_capture_victim]
        return enrich

    # Gain manqué : on était gagnant (matériellement) via le meilleur coup,
    # mais le coup joué laisse filer. Si le meilleur coup était une capture.
    if cp_best >= 150 and (cp_best - cp_after) >= config.BLUNDER_CP:
        best_mv_uci = pos_before["best_uci"]
        if best_mv_uci:
            best_mv = chess.Move.from_uci(best_mv_uci)
            if board_before.is_capture(best_mv):
                enrich["motif"] = "gain_manque"
                victim = board_before.piece_at(best_mv.to_square)
                enrich["missed_tactic"] = "capture gagnante"
                return enrich

    enrich["motif"] = "erreur_positionnelle"
    return enrich


def severity(cp_loss: int) -> str | None:
    if cp_loss >= config.BLUNDER_CP:
        return "gaffe"
    if cp_loss >= config.MISTAKE_CP:
        return "erreur"
    if cp_loss >= config.INACCURACY_CP:
        return "imprecision"
    return None


# ---------------------------------------------------------------------------
# Analyse d'une partie -> liste de blunders enrichis + méta
# ---------------------------------------------------------------------------

def game_id(g: dict) -> str:
    return g.get("uuid") or g["url"].rstrip("/").split("/")[-1]


def analyse_game(g: dict, engine, depth: int) -> tuple[dict, list[dict]] | None:
    if g.get("rules") != "chess":
        return None  # on ignore les variantes (chess960, bughouse...)
    pgn = g.get("pgn")
    if not pgn:
        return None
    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None:
        return None

    white = g["white"]["username"].lower()
    black = g["black"]["username"].lower()
    me = config.USERNAME.lower()
    if me == white:
        user = chess.WHITE
        my_rating = g["white"]["rating"]
        opp_rating = g["black"]["rating"]
        my_res = g["white"]["result"]
    elif me == black:
        user = chess.BLACK
        my_rating = g["black"]["rating"]
        opp_rating = g["white"]["rating"]
        my_res = g["black"]["result"]
    else:
        return None

    result = "victoire" if my_res == "win" else (
        "nulle" if my_res in ("agreed", "repetition", "stalemate", "insufficient",
                              "50move", "timevsinsufficient") else "défaite")

    moves = list(game.mainline_moves())
    if len(moves) < 6:
        return None
    clocks = parse_clocks(game)
    base, inc = parse_time_control(g.get("time_control"))
    tt = think_times(clocks, base, inc)

    positions = analyse_positions(moves, engine, depth)

    ts = g.get("end_time", 0)
    date = dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m-%d") if ts else ""

    meta = {
        "game_id": game_id(g),
        "url": g.get("url"),
        "date": date, "timestamp": ts,
        "time_class": g.get("time_class"),     # rapid / blitz / bullet / daily
        "time_control": g.get("time_control"),
        "my_color": "blanc" if user == chess.WHITE else "noir",
        "my_rating": my_rating, "opp_rating": opp_rating,
        "result": result,
        "n_moves": len(moves),
    }

    blunders = []
    total_cp_loss = 0   # somme des pertes (>=0) sur tous TES coups -> ACPL
    n_user_moves = 0
    board = chess.Board()
    for ply, mv in enumerate(moves):
        is_user_move = (board.turn == user)
        if is_user_move:
            # Un coup qui donne mat est forcément le meilleur : jamais un blunder.
            tmp = board.copy(stack=False)
            tmp.push(mv)
            if tmp.is_checkmate():
                board.push(mv)
                continue
            pos_before = positions[ply]
            pos_after = positions[ply + 1]
            cp_before = pos_before["cp_white"] if user == chess.WHITE else -pos_before["cp_white"]
            cp_after = pos_after["cp_white"] if user == chess.WHITE else -pos_after["cp_white"]
            cp_loss = cp_before - cp_after
            n_user_moves += 1
            total_cp_loss += max(cp_loss, 0)
            sev = severity(cp_loss)
            if sev is not None:
                # temps passé sur le coup (incrément compris)
                time_spent = tt[ply]
                enrich = detect_motif(board, mv, pos_before, pos_after, user)
                # bascule : on passait de non-perdant à perdant
                flipped = cp_before > -config.DECISIVE_CP and cp_after <= -config.DECISIVE_CP
                blunders.append({
                    **{k: meta[k] for k in ("game_id", "url", "date", "timestamp",
                                            "time_class", "my_color", "my_rating",
                                            "opp_rating", "result")},
                    "move_number": board.fullmove_number,
                    "ply": ply,
                    "fen_before": pos_before["fen"],
                    "move_played": board.san(mv),
                    "best_move": pos_before["best_san"],
                    "best_line": pos_before["pv_uci"],
                    "eval_before_cp": cp_before,
                    "eval_after_cp": cp_after,
                    "cp_loss": cp_loss,
                    "severity": sev,
                    "phase": game_phase(board),
                    "time_spent_s": time_spent,
                    "impulsive": (time_spent is not None and time_spent < config.IMPULSIVE_SECONDS),
                    "flipped_game": flipped,
                    **enrich,
                })
        board.push(mv)

    meta["n_user_moves"] = n_user_moves
    meta["total_cp_loss"] = total_cp_loss
    meta["acpl"] = round(total_cp_loss / n_user_moves, 1) if n_user_moves else None
    return meta, blunders


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def load_all_games() -> list[dict]:
    games = []
    for f in sorted(config.RAW_DIR.glob("*.json")):
        data = json.loads(f.read_text())
        games.extend(data.get("games", []))
    return games


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="mois de départ AAAA/MM")
    ap.add_argument("--limit", type=int, help="nombre max de parties (test)")
    ap.add_argument("--depth", type=int, default=config.ENGINE_DEPTH)
    ap.add_argument("--force", action="store_true", help="réanalyse même si en cache")
    args = ap.parse_args()

    config.ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

    games = load_all_games()
    # tri chronologique
    games.sort(key=lambda g: g.get("end_time", 0))
    if args.since:
        since_ts = dt.datetime.strptime(args.since, "%Y/%m").timestamp()
        games = [g for g in games if g.get("end_time", 0) >= since_ts]
    if args.limit:
        games = games[-args.limit:]

    engine = chess.engine.SimpleEngine.popen_uci(config.STOCKFISH_PATH)
    engine.configure({"Threads": config.ENGINE_THREADS, "Hash": config.ENGINE_HASH_MB})

    all_meta, all_blunders = [], []
    try:
        for i, g in enumerate(games, 1):
            gid = game_id(g)
            cache = config.ANALYSIS_DIR / f"{gid}.json"
            if cache.exists() and not args.force:
                payload = json.loads(cache.read_text())
            else:
                res = analyse_game(g, engine, args.depth)
                if res is None:
                    continue
                meta, blunders = res
                payload = {"meta": meta, "blunders": blunders}
                cache.write_text(json.dumps(payload, ensure_ascii=False))
            all_meta.append(payload["meta"])
            all_blunders.extend(payload["blunders"])
            nb = len(payload["blunders"])
            print(f"[{i}/{len(games)}] {payload['meta']['date']} "
                  f"{payload['meta']['time_class']:6} {payload['meta']['result']:9} "
                  f"-> {nb} blunders")
    finally:
        engine.quit()

    config.BLUNDERS_FILE.write_text(
        "\n".join(json.dumps(b, ensure_ascii=False) for b in all_blunders))
    config.GAMES_INDEX.write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in all_meta))

    print(f"\n{len(all_meta)} parties · {len(all_blunders)} blunders "
          f"-> {config.BLUNDERS_FILE.name}")


if __name__ == "__main__":
    main()
