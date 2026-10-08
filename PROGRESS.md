# PROGRESS.md

## Status

Preparation run (before M0) done: code map, test baseline, fixes for code that
did not import or build, cleanup groups (a)-(g). See CODEMAP.md (section 9 for
the state after cleanup) and DECISIONS.md. Next: M0 step 3 onward (compare map
with PLAN.md 5/5a beyond what is recorded, tool and AWS checks, probes, refs).

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

## Fixes before cleanup

| Commit | Fix | Backend tests after |
|---|---|---|
| `17c852a` | Invalid Python class/module names | 97 passed, 3 failed, 1 collection error |
| `d2e7b23` | Invalid component name (frontend build) | frontend `tsc -b` and build pass |
| `1ad1294` | CAP test expectations | 98 passed, 2 failed, 1 collection error |
| `a802f0b` | Reports router registered twice | same |
| `9c40389` | `PUKAAR_IMAGE_ENABLED` read with wrong case | (during group e) |

Tests run against the versions pinned in `backend/uv.lock`
(`uv sync --frozen --extra dev`); unpinned latest sqlmodel fails 14 more tests.

## Cleanup (step 3) results

| Group | Commits | Files deleted | Lines removed | Lines added |
|---|---|---|---|---|
| (a) PLAN.md "Delete" list | `8821524` camera backend, `c96a7ec` camera frontend, `ea68a6c` LiteRT, `69a3e6e` + `1eb1cc4` edge sync, `ee1c971` Android, `5d7b297` demo artifacts/notebooks/datasets, `47c34e2` scripts + docker-compose, `226fb53` old docs/design bundle/fixtures/shared | 345 | 32,035 | 180 |
| (b) Dead code | `dedb775`, plus `0e6a5db` national-schema export route | 1 | 247 | 1 |
| (c) Unused files | `fe2c978` | 9 | 1,905 | 0 |
| (d) Unused dependencies | `b54effc` Python, `99921b7` npm | 0 | 657 (mostly lock files) | 60 |
| (e) Unused settings / env vars | `db7da2f` | 0 | 28 | 41 |
| (f) Old documentation | `c61cd11` | 2 (+ `backend/README.md` rewritten) | 374 | 20 |
| (g) Stale comments | `eb258e8` | 0 | 28 | 19 |

Group (a) file count excludes `backend/data/historical_context.sqlite`, which
`8821524` committed by mistake and `69a3e6e` removed. Binary files (media,
zip, PDFs) count as files but not lines. Tracked files: 447 at
`Starting codebase`, 93 after cleanup.

| Tests | Before (fd64bc3) | After cleanup |
|---|---|---|
| Backend pytest | 22 passed, 1 failed, 0 skipped, 13 files fail to collect | 53 passed, 0 failed, 0 skipped, all files collect |
| Frontend vitest | 5 passed | 5 passed |
| Frontend `tsc -b` / `npm run build` | fail | pass |
| Frontend `npm run lint` | 7 errors | 5 errors (pre-existing `any`/impure-render in `Dashboard.tsx`) |

Removed tests and why: camera/LiteRT/sync/dialect tests went with their code
(`test_pukaar_assessment`, `test_deterministic_firewall`, `test_fusion_engine`,
`test_pukaar_provider`, `test_litert_node`, `test_litert_benchmark`,
`test_rioplatense`, `test_sinagir_export`, and the camera/LiteRT/sync cases in
`test_api`, `test_actuators`, `test_image_assessment`, `test_decision_engine`).
Decision-engine scenarios that used camera readings now use volunteer reports
and hydromet snapshots that reach the same levels.

Commit history note: the tree at `69a3e6e` does not import (it already deletes
`api/routers/sync.py`); `1eb1cc4` completes the change. History is not
rewritten.

## Steps 4-6 (preparation run)

- Secrets: `.gitignore` now also covers `.cloud-keys.local`, `.aws/`,
  `.aws-sam/`, `.venv/`, caches and model weight files. A scan of every
  tracked file and of the full history found no key or token. The original
  `.env.example` (in `Starting codebase`) held a personal Gmail address with a
  placeholder password; no secret.
- README.md written for Pukaar.
- `cloud/setup.sh` tested in a clean clone with an empty home directory and a
  PEP 668 system Python: AWS CLI 1.46, SAM CLI 1.167, backend and frontend
  installed in 25 s; both test suites pass in that clone.

## Needs human

- AWS: the AWS CLI on the preparation machine had no credentials, so the
  `pukaar-cloud` IAM user was not created. Configure the CLI with an admin
  identity, create the user with the permissions SAM needs (CloudFormation,
  Lambda, ECR, DynamoDB, Step Functions, API Gateway, Cognito, S3, EventBridge
  Scheduler, SQS, SSM, CloudWatch, Amplify, Bedrock, Polly, Transcribe, IAM
  role management), create one access key, store it in `.cloud-keys.local`
  (git-ignored), and enter it in the cloud environment (cloud/ENVIRONMENT.md).
- Cloud network: if `*.amazonaws.com` is not covered by the default allowed
  domains, add it.
- `Project.md` (old submission criteria) and `LICENSE` (CC BY 4.0): decide to
  keep, rewrite or delete; PLAN.md rule 11 stops the agent from doing it.
- Write the README acknowledgements section before submitting.
- From PLAN.md 13 (later milestones): Bedrock model access, Telegram bot token
  in SSM at `/pukaar/telegram_token`, native-speaker review of Hindi text,
  verifying village coordinates, sourcing any figure quoted, recording the
  demo video and submitting.
