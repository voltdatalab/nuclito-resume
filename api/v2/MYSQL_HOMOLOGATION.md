# Disposable MySQL / image homologation

This is a **CI-only candidate gate**, not deployment or authorization to access an
existing database. No Ghost, CapRover, production DB, registry publishing, or real
OpenAI request is part of it. The production Dockerfile and unpinned production
requirements are intentionally unchanged.

## Entrypoints

From repository root, Python 3.10 in a private environment:

```sh
python3.10 -m venv "$RUNNER_TEMP/summary-tests"
"$RUNNER_TEMP/summary-tests/bin/python" -m pip install -r api/v2/requirements-mysql-test.txt
"$RUNNER_TEMP/summary-tests/bin/python" -m pytest gate_tests -q
(cd api/v2 && PYTHONPATH=. "$RUNNER_TEMP/summary-tests/bin/python" -m pytest tests -q)
```

The last command remains the independent 46-test offline/SQLite suite. It does
not discover `mysql_tests`. Native mysqlclient installation needs a compiler,
Python headers, MySQL/MariaDB client headers and pkg-config; the workflow installs
those only on its disposable GitHub-hosted runner. All additional direct test
dependencies are exactly pinned; mysqlclient 2.3.0 was checked against PyPI and
built/imported in a private Python 3.10 environment during preparation.

Against **only** the workflow's disposable service:

```sh
cd api/v2
export PYTHONPATH=.
export NUCLITO_MYSQL_TEST_DSN='mysql+mysqldb://root:fixture-root-only@127.0.0.1:3306/nuclito_ci'
"$RUNNER_TEMP/summary-tests/bin/python" -m pytest mysql_tests -q --strict-markers --timeout=30 --junitxml="$RUNNER_TEMP/mysql-results.xml"
"$RUNNER_TEMP/summary-tests/bin/python" ../../scripts/check_mysql_receipt.py "$RUNNER_TEMP/mysql-results.xml"
```

Any missing or different DSN errors, never skips. Each test owns a random
`nuclito_fixture_*` database and drops that exact database in teardown. The
missing-Post test gets its own fresh database, without dropping another test's
tables. Credentials are public synthetic fixtures, not Actions secrets.

## What is gated

15 collected real-MySQL test cases use **`Post.metadata.create_all`**, the real
`Post.__table__`, and **`provision`** for inbox and cursor. No substitute Post DDL.
They check InnoDB/MySQL 8, idempotent provisioning, simultaneous duplicate
admission and claims, identical-content watermark advancement (also concurrent
with final-attempt completion), edited/private/draft/deleted/unpublished fencing,
lease recovery after a separate claiming process exits abruptly, actual transaction rollback after
materialization but before acknowledgment, absent Post table fail-closed atomic
admission, real row-lock timeout with sanitized Inbox error and successful retry,
and a real two-transaction InnoDB deadlock with exactly one victim and rollback.
The deadlock test exercises server/engine transaction behavior, not automatic
Inbox deadlock retry: the application currently returns a retryable rejection on
SQL errors. Fault injection in the finish rollback test aborts only the final
acknowledgment statement; all earlier SQL executes on the actual server.

Driver connect/read/write bounds, pool timeout, a 2-second InnoDB lock wait,
5-second SELECT execution cap, 30-second pytest timeout and 20-minute job ceiling
bound failures. JUnit verification requires all 15 cases with **zero skips,
failures or errors**; changing inventory must update the verifier and its tests.

## Exact production image

`.github/workflows/summary-homologation.yml` builds `api/v2/Dockerfile` with
`api/v2` as context, loads a runner-local image and never pushes it. It runs the
image's real shell CMD (`python /app/main.py`) without overriding the entrypoint.
`container_smoke.py` refuses non-GitHub-hosted execution, uses a new internal-only
Docker network and a separate `nuclito_runtime` fixture DB, publishes no ports,
drops capabilities, and imposes memory/CPU/PID limits. Only the disposable MySQL
service is attached as `mysql`. The runtime cannot reach Ghost/OpenAI/Internet.

The smoke waits at most 60 seconds for actual HTTP `/` = 200 with the existing
`{"Hello":"World"}` response; checks the real entrypoint created only `posts`;
prints Python/package versions; explicitly provisions inbox/cursor via the
production CLI; reads schema back; requires `/post/` = 200 with an empty list and
a synthetic missing post = 404. No POST, worker, CMS fetch or generation runs.
Synthetic OpenAI and webhook keys are passed only to the CI container.

## Execution/approval boundary

The workflow runs on `pull_request`, selected feature/test/fix/CI branch pushes
and manual dispatch. Permissions are only `contents: read`; checkout credentials
are not persisted. Actions use immutable release SHAs resolved through GitHub's
API. No production environment, deploy step, packages permission, GHCR publishing
or repository write token is configured.

Local preparation verifies imports, test collection, absent-DSN refusal, the
46 offline tests, gate-tool tests and actionlint. **It does not certify MySQL or
the production image.** After parent review/push, require the hosted run's exact
head SHA to pass both MySQL and image smoke. If the unmodified Dockerfile or its
unbounded dependencies fail to build/start, preserve that CI failure, reproduce
it in isolated CI and add a narrow regression before fixing; do not guess at
production dependency updates. No commit/push/PR is performed by this task.
