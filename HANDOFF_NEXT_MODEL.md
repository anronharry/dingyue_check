# Next Model Handoff

## Status

The `bot_async.py` legacy cleanup task is complete.

The runtime path is now consistently assembled from the modular `handlers/` and `services/` factories, and the old unreachable command/message/callback implementations have been removed from `bot_async.py`.

## Current Runtime Shape

- `bot_async.py` now mainly contains:
  - shared initialization and singleton accessors
  - compatibility helpers still used by injected factories
  - service construction
  - handler factory wiring
  - startup / shutdown entrypoints
- `main.py` is a thin entrypoint that imports and runs `bot_async.main`

## Validation Status

The latest cleanup passed:

- `compileall True`
- module import check
- application assembly check
- handler registration count: `21`
- `python -m unittest tests.test_smoke_assembly`

Typical smoke test:

```powershell
python scripts/smoke_assembly.py
python -m unittest tests.test_smoke_assembly
```

## If You Continue From Here

Do not restart the old refactor plan.

Reasonable follow-up work is now ordinary maintenance, for example:

1. tidy formatting / comments in `bot_async.py`
2. standardize mojibake-affected source comments or docstrings if desired
3. further reduce bootstrap coupling only if there is a clear payoff
4. extend the current smoke script / unittest coverage if stronger assembly guarantees are needed

## Important Constraint

Keep the bot runnable after each change and continue validating with compile/import/application assembly checks.
