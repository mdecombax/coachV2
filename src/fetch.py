"""Télécharge les parties de chess.com via l'API publique (sans clé, sans LLM).

Stratégie de cache : chaque archive mensuelle est sauvegardée en JSON dans
data/raw/. Les mois passés ne changent jamais -> on ne les re-télécharge pas.
Le mois en cours est toujours rafraîchi.

Usage:
    python src/fetch.py            # tout l'historique (incrémental)
    python src/fetch.py 2026/06    # un mois précis
"""
import sys
import json
import datetime as dt

import requests

import config


def _get(url: str) -> dict:
    r = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=30)
    r.raise_for_status()
    # L'API renvoie parfois des caractères de contrôle dans les annotations PGN.
    return json.loads(r.text, strict=False)


def list_archives() -> list[str]:
    url = f"https://api.chess.com/pub/player/{config.USERNAME}/games/archives"
    return _get(url)["archives"]


def _archive_path(month_key: str):
    # month_key = "2026/06"
    return config.RAW_DIR / f"{month_key.replace('/', '-')}.json"


def fetch_month(archive_url: str, force: bool = False) -> dict:
    """Télécharge une archive mensuelle, avec cache local."""
    # archive_url se termine par .../games/2026/06
    month_key = "/".join(archive_url.rstrip("/").split("/")[-2:])
    path = _archive_path(month_key)

    if path.exists() and not force:
        return json.loads(path.read_text())

    data = _get(archive_url)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=0))
    return data


def fetch_all(only_month: str | None = None) -> list[dict]:
    """Retourne la liste de toutes les parties (dict bruts de l'API)."""
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    archives = list_archives()

    # Le mois courant est volatil -> on force son rafraîchissement.
    current = f"{dt.date.today():%Y/%m}"

    games: list[dict] = []
    for url in archives:
        month_key = "/".join(url.rstrip("/").split("/")[-2:])
        if only_month and month_key != only_month:
            continue
        force = month_key == current
        data = fetch_month(url, force=force)
        n = len(data.get("games", []))
        flag = " (rafraîchi)" if force else ""
        print(f"  {month_key} : {n} parties{flag}")
        games.extend(data.get("games", []))
    return games


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    print(f"Téléchargement des parties de {config.USERNAME}...")
    games = fetch_all(only_month=only)
    print(f"\nTotal : {len(games)} parties en cache dans {config.RAW_DIR}")
