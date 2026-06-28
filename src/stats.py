"""Stats rétrospectives sur data/game_features.jsonl (graphes ASCII, sans dépendance).

Usage :
    python src/stats.py rolling                # erreurs, fenêtre 10
    python src/stats.py rolling --metric acpl --window 10
    python src/stats.py rolling --metric n_blunder --window 20
"""
import json
import argparse

import features

BLOCKS = "▁▂▃▄▅▆▇█"


def load_rapid():
    rows = [r for r in features.load() if r["time_class"] == "rapid"]
    rows.sort(key=lambda r: r["timestamp"])
    return rows


def rolling_mean(values, window):
    out = []
    for i in range(len(values)):
        a = max(0, i - window + 1)
        seg = [v for v in values[a:i + 1] if v is not None]
        out.append(sum(seg) / len(seg) if seg else None)
    return out


def ascii_chart(series, dates, height=16, width=96, ylabel=""):
    """series : liste de floats (déjà lissés). Trace un nuage de points ASCII."""
    pts = [(d, v) for d, v in zip(dates, series) if v is not None]
    if not pts:
        print("(pas de données)")
        return
    dates = [d for d, _ in pts]
    vals = [v for _, v in pts]

    # downsample à `width` colonnes par moyenne de bucket
    n = len(vals)
    if n > width:
        col_v, col_d = [], []
        for i in range(width):
            a, b = int(i * n / width), int((i + 1) * n / width)
            seg = vals[a:b] or [vals[min(a, n - 1)]]
            col_v.append(sum(seg) / len(seg))
            col_d.append(dates[min(b - 1, n - 1)])
        vals, dates = col_v, col_d
    w = len(vals)

    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    grid = [[" "] * w for _ in range(height)]
    for x, v in enumerate(vals):
        y = int(round((v - lo) / span * (height - 1)))
        grid[height - 1 - y][x] = "●"

    print(f"\n  {ylabel}")
    for r, row in enumerate(grid):
        val = hi - (hi - lo) * r / (height - 1)
        print(f"  {val:6.1f} │ " + "".join(row))
    print("         └" + "─" * w)

    # axe x : ~7 dates réparties uniformément (YY-MM), sans chevauchement
    axis = [" "] * w
    nlab = 7
    for i in range(nlab):
        x = int(i * (w - 1) / (nlab - 1))
        lab = dates[x][2:]                       # "YY-MM"
        start = min(max(x - 2, 0), w - len(lab))
        for j, ch in enumerate(lab):
            axis[start + j] = ch
    print("           " + "".join(axis))


def cmd_rolling(args):
    rows = load_rapid()
    raw = [r.get(args.metric) for r in rows]
    dates = [r["date"] for r in rows]
    sm = rolling_mean(raw, args.window)
    valid = [v for v in sm if v is not None]
    label = {"n_errors": "erreurs (erreur+gaffe)", "n_blunder": "gaffes",
             "acpl": "ACPL", "zeitnot_moves": "coups en zeitnot",
             "impulsive_errors": "coups impulsifs"}.get(args.metric, args.metric)
    print(f"Moyenne glissante /{args.window} parties — {label}  "
          f"({len(rows)} parties rapides)")
    ascii_chart(sm, dates, ylabel=f"{label} (moy. {args.window} parties)")
    if valid:
        print(f"\n  Début : {valid[0]:.1f}   ·   Maintenant : {valid[-1]:.1f}   "
              f"·   Min : {min(valid):.1f}   ·   Max : {max(valid):.1f}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rolling", help="moyenne glissante d'une métrique")
    r.add_argument("--metric", default="n_errors")
    r.add_argument("--window", type=int, default=10)
    r.set_defaults(func=cmd_rolling)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
