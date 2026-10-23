# Runbook

How the scheduled runs work, what to check each morning, and what to do when something fails. Commands run from the repository root in WSL; Jenkins is at http://127.0.0.1:8080 (user `admin`, password `JENKINS_ADMIN_PASSWORD` from `.env`).

## Scheduled jobs

| Job | When (Paris time) | Stages | Writes |
|---|---|---|---|
| `market-risk-nightly` ([`Jenkinsfile`](../Jenkinsfile)) | Monday to Friday, 23:00 | lint, tests, ingest, quality gate, transform, book, volatility (all models but the GRU), VaR and backtest, volumes and costs, regimes, anomaly detector, publish | raw, quality, silver and gold tables, `data/gold/*.parquet` |
| `market-risk-retrain` ([`jenkins/Jenkinsfile.retrain`](../jenkins/Jenkinsfile.retrain)) | Saturday, 09:00 | champion and challenger for the parametric VaR, then VaR, backtest and publish | MLflow registry alias `champion`, `fact_var`, `fact_backtest`, `fact_promotion` |

After every run, success or failure, `pipeline.monitor` appends the run to `data/monitoring/runs.parquet`, measures drift and rolling errors after a successful night run, and exports `fact_runs`, `fact_drift`, `fact_model_monitor` and `fact_promotion` to `data/gold/`. Each stage rebuilds its tables from scratch, so rerunning a job is safe.

Jenkins builds the committed `main` branch of the local repository (`/repo` in the container): uncommitted changes are not run. A run started by hand while a job is running writes to the same database and `data/` folder; wait for the job to finish.

## Morning check

Open the Production page of the report (refresh first):

1. **Last night run**: status `SUCCESS`, finished after 23:00 the previous weekday. A missing run means the machine or Docker was off at 23:00; start it with *Build Now*.
2. **Failed quality rules**: critical rules stop the run; warning rules (late sources, stale values, suspect ticks) do not, and are listed on the Data quality page.
3. **Input drift**: a PSI above 0.25 marks a significant shift of the book's returns or realised variance against 2008-2017. It calls for a look at the rolling errors and the backtest, not for a retrain by itself.
4. **Rolling errors**: GJR-GARCH against HAR on the book's volatility, XGBoost against the 20-day ADV on volume. A model above its baseline for several weeks is a candidate for review; the Saturday job handles the VaR champion.

## Incidents

### The night run failed at the quality gate

A critical rule failed (schema, duplicate key, non-positive price, yield out of range) and every later stage was skipped, so the report still shows the previous run.

1. Read the console of the failed build (*Console Output*): the gate prints each failed critical rule with the series, the number of failing rows and an example. The flagged rows are in `data/dq/dq_flags.parquet`.
2. If the raw file is wrong (a bad download), start *Build with Parameters* with `INGEST` ticked to download again.
3. If the error is in the source itself, wait for the provider to correct it; the gate will keep failing until then, which is intended.

### A source is late or down

Late sources are warnings (`freshness` rules): the run continues with the last complete values and the report shows the source as late. Known cases:

- FRED maintenance (21 October 2026): the VIX and the US curve slope stop updating. Once the API is back, download them alone with `.venv/bin/python -m pipeline.ingest --sources fred`, then rerun the night job with `INGEST` unticked.
- Yahoo partial bar: a Paris stock with no close at download time is not used; the previous complete close stays and the series is reported late. The next night run picks up the close.

### Lint or tests failed

A commit on `main` broke a check; GitHub Actions shows the same failure on the pushed commit. Fix it, commit, and start *Build Now*.

### A model stage failed

Read the console for the traceback. The report reads `data/gold/`, which only changes at the publish stage, so it stays on the previous run (apart from the monitoring tables). After the fix, rerun with `INGEST` unticked: the raw files of the night are reused.

### Promotion

The Saturday job compares the EWMA, GARCH and GJR-GARCH 1-day forecasts over the last 250 days. A challenger replaces the champion only if its QLIKE is lower and the Basel zone of its VaR is no worse. To run it outside the schedule, start `market-risk-retrain` with *Build Now*. The decision is in `fact_promotion` and in MLflow (experiment `var-volatility-promotion`, model `var-volatility`):

```bash
.venv/bin/mlflow ui --backend-store-uri sqlite:///data/mlflow.db --port 5001   # http://127.0.0.1:5001
```

### Jenkins or PostgreSQL is down

Both containers restart with Docker after a reboot; a run scheduled while the machine was off is skipped, not caught up.

```bash
docker compose ps                         # state of db and jenkins
docker compose up -d                      # start both
docker compose logs --tail 100 jenkins    # or db
```

The database lives in the `pgdata` volume and the Jenkins configuration in `jenkins_home`: restarting a container loses neither. After a change to `.env` (a new password or FRED key), recreate Jenkins so it reads the new secrets: `docker compose up -d --force-recreate jenkins`.

### The report does not refresh

- The `DataFolder` parameter must point to `\\wsl.localhost\Ubuntu-24.04\home\moha\market-risk-monitor\data\gold` and WSL must be running.
- A file being rewritten during a refresh (a night run in progress) can make one table fail; refresh again once the run is over.
- An error that disappears after closing and reopening the project comes from Power BI Desktop's session, not from the files.

## Manual runs

The GRU is not part of the scheduled runs (about 30 minutes on a GPU, 70 on a CPU). To refresh its forecasts:

```bash
.venv/bin/python -m pipeline.vol_models --models gru   # replaces the GRU rows, keeps the other models
.venv/bin/python -m pipeline.regimes                   # forecast errors by regime
.venv/bin/python -m pipeline.publish
```

Any stage can be run alone the same way, in the order of the [quick start](../README.md#quick-start). From a script, Jenkins builds are started through its API with a crumb from `/crumbIssuer/api/json` and a POST to `/job/market-risk-nightly/buildWithParameters?INGEST=false`.
