# Eval results

| File | Produced by |
|------|-------------|
| `calibration_20261024T015005Z.md` | `python eval/run_eval.py`: Jev (`jev-1.14.0`) and the LLM (`claude-opus-5-5`) on the 60 labeled messages, nine intents |
| `triage_probs.json` | `python eval/sweep_thresholds.py --refresh`: raw Jev triage result per message (`jev-1.14.0`) |
| `threshold_sweep.md` | `python eval/sweep_thresholds.py`: chosen constants, templates taken, top-20 Pareto front, nearest messages to each threshold |
| `threshold_sweep_full.csv` | `python eval/sweep_thresholds.py`: all 1,800 threshold combinations, sorted by non-LLM share |

Calibration uses the probability each classifier gave its chosen answer (Jev:
`probabilities[choice]`, `max(p, 1-p)` for a Noul, the argmax level for a Score), not Jev's
Choice `.confidence`. The fake Jev never writes here.
