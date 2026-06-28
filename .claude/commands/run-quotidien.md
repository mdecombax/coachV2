---
description: Run quotidien du coach d'échecs (fetch + analyse + prose + push GitHub Pages)
---

Tu es le coach. Exécute le **run quotidien complet**, dans l'ordre, sans rien demander.

## 1. Déterministe (Bash)
```
./.venv/bin/python src/daily.py --depth 12 --n 20
```
Ça fait : fetch des nouvelles parties → analyse Stockfish incrémentale → sélection
des puzzles en 2 sections (aujourdhui / recurrent) → faits du briefing, le tout
dans `web/blunders.json`. Lis le résumé imprimé (nb de parties nouvelles).

## 2. Rien de neuf ?
Si `briefing.n_new_games == 0` ET aucun nouveau puzzle dans la section
*aujourdhui* : dis-le simplement et **arrête-toi** (pas de commit inutile).

## 3. Prose LLM (toi)
Ouvre `web/blunders.json`. Pour chaque partie de `briefing.games`, lis son cache
d'analyse `data/analysis/<game_id>.json` (chaque coup : motif, éval, temps, ply).
Remplis :
- `briefing.applied` / `to_work` / `advice_now` — nuance « sur cette partie » vs la
  tendance (`ref_rate`) ; ne déclare jamais une faiblesse résolue sur une partie.
- `briefing.continuity` = `[{game_id, text}]` : récit **coup par coup** (coups réels)
  de ce qui a été appliqué / répété par rapport au focus.
- la prose des puzzles listés dans `needs_prose` : `why_blunder`, `why_better`,
  `coach_tip`.
Recalcule `needs_prose`, réécris `web/blunders.json`.

**Ton** : débutant ~470, français, tutoiement, simple et concret, sans jargon non
expliqué, **sans jamais inventer** un coup ou une menace (reste fidèle aux faits).

## 4. Mémoire
Édite `data/coaching_state.json` : avance `last_game_end` au `timestamp` de la
dernière partie traitée ; ajuste `focus` (motif à 0 sur plusieurs parties →
« en bonne voie » ; motif qui remonte → « actif ») ; ajoute une entrée à `history`.

## 5. Publier (Bash)
```
git add -A && git commit -m "daily: maj coach $(date +%F)" && git push origin main
```
Le push redéploie GitHub Pages.

## 6. Résumé
Donne un résumé court : parties nouvelles, ce qui a été appliqué / à travailler, et
le lien **https://mdecombax.github.io/coachV2/**.
