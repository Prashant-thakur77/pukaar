# PROGRESS.md

## Status

Preparation run (before M0). See CODEMAP.md for the code as found.

## Test baseline (starting codebase, fd64bc3)

Backend: `cd backend && .venv/bin/python -m pytest -q --continue-on-collection-errors`
(Python 3.12.13, `uv pip install -e '.[dev]'`)

| Result | Count |
|---|---|
| Passed | 22 |
| Failed | 1 (`test_deterministic_firewall.py::test_elevated_without_crossing`) |
| Skipped | 0 |
| Collection errors | 13 test files (SyntaxError from `api/deps.py` and the renamed adapters) |

Without `--continue-on-collection-errors` pytest stops at collection and runs nothing.

Frontend: `cd frontend && npm ci --legacy-peer-deps && npm test`

| Result | Count |
|---|---|
| vitest passed | 5 / 5 (`src/store.test.ts`) |
| `tsc -b` / `npm run build` | fails: `Pukaar AIReasoning` in `CommandCenter.tsx` and `Dashboard.tsx` |

## Needs human

(none yet)
