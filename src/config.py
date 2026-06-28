"""Configuration partagée du coach d'échecs.

Tout est centralisé ici : pseudo, chemins, et surtout les seuils qui
définissent ce qu'est un "blunder" et comment on classe la gravité.
"""
import os
from pathlib import Path

# --- Joueur ---
USERNAME = "mdecombax"

# --- Chemins ---
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"            # PGN bruts par mois (cache API)
ANALYSIS_DIR = DATA_DIR / "analysis"  # 1 JSON d'analyse par partie (cache Stockfish)
BLUNDERS_FILE = DATA_DIR / "blunders.jsonl"  # tous les blunders, 1 par ligne
GAMES_INDEX = DATA_DIR / "games_index.jsonl"  # méta de chaque partie analysée
REPORTS_DIR = ROOT / "reports"

# --- Stockfish ---
# Surchargeable par env (Mac: /opt/homebrew/bin/stockfish · CI Ubuntu: /usr/games/stockfish).
STOCKFISH_PATH = os.environ.get("STOCKFISH_PATH", "/opt/homebrew/bin/stockfish")
# Profondeur d'analyse par coup. 12-15 suffit largement pour juger un
# blunder à notre niveau, et reste rapide en lot.
ENGINE_DEPTH = 14
ENGINE_THREADS = 4
ENGINE_HASH_MB = 256

# --- Seuils de classification (perte en centipions, du point de vue du joueur) ---
# On raisonne en "perte" = eval_meilleur_coup - eval_coup_joué.
INACCURACY_CP = 50    # imprécision
MISTAKE_CP = 120      # erreur
BLUNDER_CP = 250      # gaffe
# En dessous d'INACCURACY_CP on ignore (bruit).

# Un coup joué en moins de ce temps (secondes) est marqué "impulsif".
IMPULSIVE_SECONDS = 5.0

# Une éval >= ce seuil (cp) est considérée "gagnante" ; on s'en sert pour
# détecter si un blunder a fait BASCULER la partie.
DECISIVE_CP = 200

# Plafonnement des évals de mat pour les rendre comparables en centipions.
MATE_CP = 10000

# User-Agent requis par l'API chess.com (sinon throttling/erreurs).
USER_AGENT = "coachV2/0.1 (chess coach perso; chess.com/member/mdecombax)"
