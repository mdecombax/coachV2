# Routine quotidienne `/daily` — boucle de coaching (Claude Code)

Tout part d'**une seule commande**. La seule étape « intelligence » est faite par
Claude Code (toi), en local, sans API.

## Étape 1 — Pipeline déterministe (fetch + analyse + sélection + faits)
```
./.venv/bin/python src/daily.py --depth 12 --n 20
```
Ça récupère les nouvelles parties, les analyse, régénère `web/blunders.json`
(puzzles en 2 sections *aujourdhui* / *recurrent* + objet `briefing` avec les
**faits** : pour chaque partie nouvelle, les motifs comparés au focus mémorisé).

## Étape 2 — Écrire la prose (LLM)
Ouvre `web/blunders.json`. Pour chaque partie listée dans `briefing.games`, tu
disposes des faits (`focus_check`, `motif_counts`, `gaffes`, `impulsive_errors`).
Pour la **continuité coup par coup**, lis aussi le cache d'analyse de la partie :
`data/analysis/<game_id>.json` (chaque coup : motif, éval, temps, ply).

Remplis dans `briefing` :
- **`applied`** : 1-2 phrases sur ce que le joueur a bien appliqué (focus à
  verdict `appliqué`). Nuance « sur cette partie » vs sa tendance (`ref_rate`) —
  ne déclare jamais une faiblesse « résolue » sur une seule partie.
- **`to_work`** : 1-2 phrases sur les focus encore `présent` (avec les coups).
- **`advice_now`** : LA priorité du jour, formulée comme une règle applicable.
- **`continuity`** : liste `[{game_id, text}]`. Pour chaque partie du jour, un
  récit coup par coup : « coup 23 tu as bien protégé ton cavalier ✓ · coup 31
  tu as encore pendu ta tour comme on ciblait ✗ ». Référence des coups réels.

Puis remplis la prose des puzzles de `briefing.games` (section *aujourdhui*) et
de tout id dans `needs_prose` : `why_blunder`, `why_better`, `coach_tip`
(voir consignes ci-dessous). Réécris `web/blunders.json`.

## Étape 3 — Mettre à jour la mémoire
Édite `data/coaching_state.json` :
- avance `last_game_end` au `timestamp` de la dernière partie traitée ;
- ajuste `focus` (un motif à 0 sur plusieurs parties → statut « en bonne voie » ;
  un motif qui remonte → l'ajouter / le repasser « actif ») ;
- ajoute une entrée à `history` : `{date, parties, appliqué, à_travailler, conseil}`.

## Étape 4 — Publier (push GitHub → Pages)
```
git add -A && git commit -m "daily: maj coach" && git push origin main
```
Le push déclenche le déploiement GitHub Pages : la page en ligne se met à jour.

## Consignes de ton (toute la prose)
- Public **débutant ~470**, vocabulaire simple, tutoiement, français.
- Concret et bref, pas de jargon non expliqué, pas de variantes à rallonge.
- **Ne jamais inventer** un coup/une menace : rester cohérent avec les faits moteur.

## Rappel d'architecture
- Déterministe (0 LLM) : `fetch.py`, `analyze.py`, `select_review.py`, `daily.py`,
  `coach_state.py`, `report.py`, `time_analysis.py`.
- LLM (Claude Code) : cette routine — écrit la prose + met à jour la mémoire.
- La page `web/index.html` ne fait que **lire** `web/blunders.json`.

## Plus tard : 100 % automatique
Un cron/launchd local peut lancer toute la boucle sans toi :
```
claude -p "Exécute la routine prompts/daily_coach.md" --cwd <projet>
```
(`claude -p` = Claude Code en mode non-interactif, local, sans API.)
