import concurrent.futures
import datetime as dt
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from worldquant_api_starter import (
    authenticate,
    env,
    load_env_file,
    make_session,
    request_with_retry,
)


@dataclass
class SimResult:
    expression: str
    config_name: str
    simulation_id: str
    alpha_id: str
    status: str
    sharpe: float | None
    fitness: float | None
    turnover: float | None
    returns: float | None
    drawdown: float | None
    config_json: str | None = None
    error: str | None = None


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.replace("%", "").replace("‱", "").strip()
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def find_first_numeric(payload: Any, keys: set[str]) -> float | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.lower() in keys:
                parsed = to_float(value)
                if parsed is not None:
                    return parsed
            nested = find_first_numeric(value, keys)
            if nested is not None:
                return nested
    elif isinstance(payload, list):
        for item in payload:
            nested = find_first_numeric(item, keys)
            if nested is not None:
                return nested
    return None


def extract_metrics(payload: dict) -> tuple[float | None, float | None, float | None, float | None, float | None]:
    sharpe = find_first_numeric(payload, {"sharpe"})
    fitness = find_first_numeric(payload, {"fitness"})
    turnover = find_first_numeric(payload, {"turnover"})
    returns = find_first_numeric(payload, {"returns"})
    drawdown = find_first_numeric(payload, {"drawdown"})
    return sharpe, fitness, turnover, returns, drawdown


def parse_alpha_lines(raw_text: str) -> list[str]:
    out = []
    seen = set()
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        line = re.sub(r"^\d+\s*[:\)\.-]\s*", "", line)
        if line not in seen:
            out.append(line)
            seen.add(line)
    return out


def init_history_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS simulation_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            mode TEXT NOT NULL,
            base_url TEXT NOT NULL,
            expression TEXT NOT NULL,
            config_name TEXT NOT NULL,
            simulation_id TEXT,
            alpha_id TEXT,
            status TEXT,
            sharpe REAL,
            fitness REAL,
            turnover REAL,
            returns REAL,
            drawdown REAL,
            score REAL,
            pass_estimate INTEGER,
            error TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def persist_results(db_path: Path, mode: str, base_url: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    conn = sqlite3.connect(db_path)
    now = dt.datetime.utcnow().isoformat(timespec="seconds")
    rows = []
    for _, row in df.iterrows():
        rows.append(
            (
                now,
                mode,
                base_url,
                str(row.get("expression", "")),
                str(row.get("config_name", "")),
                str(row.get("simulation_id", "")),
                str(row.get("alpha_id", "")),
                str(row.get("status", "")),
                row.get("sharpe"),
                row.get("fitness"),
                row.get("turnover"),
                row.get("returns"),
                row.get("drawdown"),
                row.get("score"),
                int(bool(row.get("pass_estimate", False))),
                str(row.get("error", "")),
            )
        )

    conn.executemany(
        """
        INSERT INTO simulation_runs (
            created_at, mode, base_url, expression, config_name, simulation_id, alpha_id,
            status, sharpe, fitness, turnover, returns, drawdown, score, pass_estimate, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()


def load_recent_history(db_path: Path, limit: int = 200) -> pd.DataFrame:
    if not db_path.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        """
        SELECT created_at, mode, expression, config_name, alpha_id, status,
               sharpe, fitness, turnover, returns, drawdown, score, pass_estimate, error
        FROM simulation_runs
        ORDER BY id DESC
        LIMIT ?
        """,
        conn,
        params=(limit,),
    )
    conn.close()
    return df


def load_best_history(db_path: Path, limit: int = 50) -> pd.DataFrame:
    if not db_path.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        """
        SELECT expression,
               MAX(sharpe) AS best_sharpe,
               MAX(fitness) AS best_fitness,
               MIN(turnover) AS min_turnover,
               MAX(score) AS best_score,
               COUNT(*) AS runs
        FROM simulation_runs
        WHERE status = 'COMPLETE'
        GROUP BY expression
        ORDER BY best_score DESC
        LIMIT ?
        """,
        conn,
        params=(limit,),
    )
    conn.close()
    return df


def build_base_settings() -> dict[str, Any]:
    return {
        "instrumentType": env("WQ_INSTRUMENT_TYPE", "EQUITY"),
        "region": env("WQ_REGION", "USA"),
        "universe": env("WQ_UNIVERSE", "TOP3000"),
        "delay": int(env("WQ_DELAY", "1")),
        "decay": int(env("WQ_DECAY", "0")),
        "neutralization": env("WQ_NEUTRALIZATION", "INDUSTRY"),
        "truncation": float(env("WQ_TRUNCATION", "0.01")),
        "visualization": env("WQ_VISUALIZATION", "0").lower() in {"1", "true", "yes", "on"},
        "pasteurization": env("WQ_PASTEURIZATION", "ON"),
        "unitHandling": env("WQ_UNIT_HANDLING", "VERIFY"),
        "nanHandling": env("WQ_NAN_HANDLING", "OFF"),
        "language": env("WQ_LANGUAGE", "FASTEXPR"),
    }


def submit_simulation_with_settings(session, base_url: str, expression: str, settings: dict[str, Any]) -> str:
    simulations_path = env("WQ_SIMULATIONS_PATH", "/simulations")
    url = f"{base_url.rstrip('/')}{simulations_path}"

    payload = {
        "type": "REGULAR",
        "settings": settings,
        "regular": expression,
    }

    resp = request_with_retry(
        session,
        "POST",
        url,
        data=json.dumps(payload),
        timeout=60,
        retries=int(env("WQ_SUBMIT_RETRIES", "3")),
        retry_base_sleep=2.0,
    )

    if resp.status_code >= 400:
        raise RuntimeError(f"Submit failed ({resp.status_code}): {resp.text[:400]}")

    location = resp.headers.get("Location")
    if location:
        return location.rstrip("/").split("/")[-1]

    data = resp.json()
    for key in ("id", "simulationId", "alphaId"):
        if key in data:
            return str(data[key])

    raise RuntimeError("Submit succeeded but no simulation id found")


def poll_simulation(session, base_url: str, simulation_id: str) -> dict:
    template = env("WQ_SIMULATION_RESULT_TEMPLATE", "/simulations/{id}")
    url = f"{base_url.rstrip('/')}{template.format(id=simulation_id)}"

    attempts = int(env("WQ_POLL_ATTEMPTS", "180"))
    interval = float(env("WQ_POLL_INTERVAL_SEC", "2"))

    for _ in range(attempts):
        resp = request_with_retry(session, "GET", url, timeout=30, retries=2, retry_base_sleep=2.0)
        if resp.status_code >= 400:
            raise RuntimeError(f"Poll failed ({resp.status_code}): {resp.text[:400]}")
        data = resp.json()
        status = str(data.get("status", "")).upper()
        if status in {"COMPLETE", "DONE", "SUCCESS", "FINISHED"}:
            return data
        if status in {"FAILED", "ERROR", "REJECTED"}:
            raise RuntimeError(f"Simulation status={status}: {json.dumps(data)[:400]}")
        time.sleep(interval)

    raise TimeoutError("Polling timed out")


def fetch_alpha_details(session, base_url: str, alpha_id: str) -> dict:
    template = env("WQ_ALPHA_RESULT_TEMPLATE", "/alphas/{id}")
    url = f"{base_url.rstrip('/')}{template.format(id=alpha_id)}"
    resp = request_with_retry(session, "GET", url, timeout=30, retries=2, retry_base_sleep=2.0)
    if resp.status_code >= 400:
        raise RuntimeError(f"Alpha fetch failed ({resp.status_code}): {resp.text[:400]}")
    return resp.json()


def run_one(expression: str, config_name: str, config: dict[str, Any], base_url: str) -> SimResult:
    session = make_session()
    authenticate(session, base_url)

    sim_id = submit_simulation_with_settings(session, base_url, expression, config)
    sim_data = poll_simulation(session, base_url, sim_id)
    alpha_id = str(sim_data.get("alpha", ""))

    sharpe = fitness = turnover = returns = drawdown = None
    if alpha_id:
        details = fetch_alpha_details(session, base_url, alpha_id)
        sharpe, fitness, turnover, returns, drawdown = extract_metrics(details)

    return SimResult(
        expression=expression,
        config_name=config_name,
        simulation_id=sim_id,
        alpha_id=alpha_id,
        status="COMPLETE",
        sharpe=sharpe,
        fitness=fitness,
        turnover=turnover,
        returns=returns,
        drawdown=drawdown,
        config_json=json.dumps(config, sort_keys=True),
    )


def run_parallel(tasks: list[tuple[str, str, dict[str, Any]]], base_url: str, max_workers: int) -> list[SimResult]:
    results: list[SimResult] = []
    progress = st.progress(0.0)
    status = st.empty()

    done = 0
    total = len(tasks)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(run_one, expr, cfg_name, cfg, base_url): (expr, cfg_name, cfg)
            for expr, cfg_name, cfg in tasks
        }

        for future in concurrent.futures.as_completed(future_map):
            expr, cfg_name, cfg = future_map[future]
            try:
                result = future.result()
            except Exception as exc:
                result = SimResult(
                    expression=expr,
                    config_name=cfg_name,
                    simulation_id="",
                    alpha_id="",
                    status="FAILED",
                    sharpe=None,
                    fitness=None,
                    turnover=None,
                    returns=None,
                    drawdown=None,
                    config_json=json.dumps(cfg, sort_keys=True),
                    error=str(exc),
                )
            results.append(result)
            done += 1
            progress.progress(done / total)
            status.write(f"Completed {done}/{total}")

    return results


def default_alpha_seed_text() -> str:
    return "\n".join(
        [
            "rank(ts_mean((vwap - close) / close, 3))",
            "rank(ts_mean((vwap - close) / close, 5))",
            "group_neutralize(rank(ts_mean((vwap - close) / close, 5)), subindustry)",
            "rank(ts_delta(close, 3)/ts_delay(close, 1))",
            "rank(ts_mean(close, 20) - ts_mean(close, 100))",
        ]
    )


def build_settings_grid(base_settings: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {**base_settings, "decay": 0, "truncation": 0.01, "neutralization": "INDUSTRY"},
        {**base_settings, "decay": 2, "truncation": 0.03, "neutralization": "INDUSTRY"},
        {**base_settings, "decay": 4, "truncation": 0.05, "neutralization": "SUBINDUSTRY"},
        {**base_settings, "decay": 6, "truncation": 0.08, "neutralization": "SUBINDUSTRY"},
    ]


def with_derived_metrics(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()

    def to_pct(value: Any) -> float | None:
        num = to_float(value)
        if num is None:
            return None
        return num * 100.0 if num <= 1.5 else num

    out["turnover_pct"] = out["turnover"].apply(to_pct) if "turnover" in out.columns else None
    out["drawdown_pct"] = out["drawdown"].apply(to_pct) if "drawdown" in out.columns else None

    out["pass_estimate"] = (
        (out.get("sharpe", pd.Series([None] * len(out))) >= 1.25)
        & (out.get("fitness", pd.Series([None] * len(out))) >= 1.0)
        & (out.get("turnover_pct", pd.Series([None] * len(out))).between(1.0, 70.0, inclusive="both"))
    )

    score = pd.Series([0.0] * len(out), index=out.index)
    if "sharpe" in out.columns:
        score += out["sharpe"].fillna(-999) * 2.0
    if "fitness" in out.columns:
        score += out["fitness"].fillna(-999) * 0.8
    if "turnover_pct" in out.columns:
        score -= (out["turnover_pct"].fillna(999) - 35.0).clip(lower=0) * 0.02
    if "drawdown_pct" in out.columns:
        score -= (out["drawdown_pct"].fillna(999) - 20.0).clip(lower=0) * 0.05
    out["score"] = score
    return out


def main() -> None:
    st.set_page_config(page_title="WorldQuant Alpha Lab", layout="wide")
    st.title("WorldQuant Alpha Lab")
    st.caption("Bulk alpha simulation, settings sweeps, parallel workers, and leaderboard export")

    load_env_file()
    db_path = Path("alpha_lab_history.db")
    init_history_db(db_path)

    with st.sidebar:
        st.header("Run Controls")
        mode = st.selectbox("Mode", ["Alpha Sweep", "Settings Sweep", "Hybrid (Top-N then Sweep)"])
        max_workers = st.slider("Parallel workers", min_value=1, max_value=8, value=3, step=1)
        max_alphas = st.number_input("Max alphas to run", min_value=1, max_value=2000, value=50, step=1)
        top_n_hybrid = st.number_input("Hybrid top-N", min_value=1, max_value=100, value=10, step=1)
        base_url = st.text_input("API base URL", value=env("WQ_BASE_URL", "https://api.worldquantbrain.com"))
        if st.button("API Health Check"):
            try:
                s = make_session()
                authenticate(s, base_url)
                st.success("Auth check passed")
            except Exception as exc:
                st.error(f"Health check failed: {exc}")

    col_left, col_right = st.columns([2, 1])

    with col_left:
        st.subheader("Alpha Input")
        uploaded = st.file_uploader("Upload txt/csv with one alpha per line", type=["txt", "csv"])
        raw_text = st.text_area("Or paste alphas", value=default_alpha_seed_text(), height=260)
        use_local_samples = st.checkbox("Load from alpha_samples_1000.txt", value=False)
        sample_mode = st.selectbox("Sample mode", ["First N", "Random N"])
        sample_seed = st.number_input("Sample seed", min_value=0, max_value=999999, value=42, step=1)

        if uploaded is not None:
            try:
                uploaded_text = uploaded.read().decode("utf-8")
                raw_text = uploaded_text
                st.info("Using uploaded content")
            except Exception as exc:
                st.error(f"Could not read upload: {exc}")

        if use_local_samples:
            sample_file = Path("alpha_samples_1000.txt")
            if sample_file.exists():
                raw_text = sample_file.read_text(encoding="utf-8")
                st.info("Loaded alpha_samples_1000.txt")
            else:
                st.warning("alpha_samples_1000.txt not found")

        alphas = parse_alpha_lines(raw_text)
        if sample_mode == "Random N" and len(alphas) > int(max_alphas):
            import random

            rng = random.Random(int(sample_seed))
            alphas = rng.sample(alphas, int(max_alphas))
        if len(alphas) > max_alphas:
            alphas = alphas[: max_alphas]

        st.write(f"Parsed alphas: {len(alphas)}")

    with col_right:
        st.subheader("Base Settings")
        base_settings = build_base_settings()
        settings_json = st.text_area(
            "Override base settings as JSON",
            value=json.dumps(base_settings, indent=2),
            height=260,
        )
        try:
            base_settings = json.loads(settings_json)
        except Exception as exc:
            st.error(f"Invalid settings JSON; using env defaults. Error: {exc}")
            base_settings = build_base_settings()

        settings_grid_json = st.text_area(
            "Optional custom settings grid JSON (list of objects)",
            value=json.dumps(build_settings_grid(base_settings), indent=2),
            height=220,
        )
        try:
            custom_grid = json.loads(settings_grid_json)
            if not isinstance(custom_grid, list):
                raise ValueError("Grid must be a JSON list")
        except Exception as exc:
            st.error(f"Invalid grid JSON. Falling back to default grid. Error: {exc}")
            custom_grid = build_settings_grid(base_settings)

    run_clicked = st.button("Run Simulation Batch", type="primary")

    if run_clicked:
        if not alphas:
            st.warning("No alphas found. Paste or upload at least one expression.")
            st.stop()

        tasks: list[tuple[str, str, dict[str, Any]]] = []

        if mode == "Alpha Sweep":
            tasks = [(expr, "base", base_settings) for expr in alphas]

        elif mode == "Settings Sweep":
            if len(alphas) != 1:
                st.warning("Settings Sweep expects exactly one alpha. Using the first one.")
            expr = alphas[0]
            grid = custom_grid
            for i, cfg in enumerate(grid, start=1):
                tasks.append((expr, f"cfg_{i}", cfg))

        else:
            stage1_tasks = [(expr, "base", base_settings) for expr in alphas]
            st.info("Hybrid stage 1: evaluating base settings for all input alphas")
            stage1_results = run_parallel(stage1_tasks, base_url, max_workers)
            stage1_ok = [r for r in stage1_results if r.status == "COMPLETE" and r.sharpe is not None]
            stage1_ok = sorted(stage1_ok, key=lambda x: (x.sharpe or -999, x.fitness or -999), reverse=True)
            selected = stage1_ok[: int(top_n_hybrid)]

            if not selected:
                st.error("Hybrid stage 1 produced no successful alpha results.")
                st.stop()

            st.success(f"Hybrid stage 1 selected {len(selected)} alphas for settings sweep")
            grid = custom_grid
            for pick in selected:
                for i, cfg in enumerate(grid, start=1):
                    tasks.append((pick.expression, f"cfg_{i}", cfg))

        dedup_tasks = []
        seen_task = set()
        for expr, cfg_name, cfg in tasks:
            key = (expr, json.dumps(cfg, sort_keys=True))
            if key in seen_task:
                continue
            seen_task.add(key)
            dedup_tasks.append((expr, cfg_name, cfg))
        tasks = dedup_tasks

        st.info(f"Running {len(tasks)} tasks with max_workers={max_workers}")
        results = run_parallel(tasks, base_url, max_workers)

        df = pd.DataFrame([asdict(r) for r in results])
        for col in ["sharpe", "fitness", "turnover", "returns", "drawdown"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        if "status" in df.columns:
            ok_count = int((df["status"] == "COMPLETE").sum())
            fail_count = int((df["status"] == "FAILED").sum())
            st.write(f"Completed: {ok_count} | Failed: {fail_count}")

        df = with_derived_metrics(df)
        sort_cols = [c for c in ["pass_estimate", "fitness", "sharpe", "score", "returns"] if c in df.columns]
        if sort_cols:
            ascending = [False] * len(sort_cols)
            df = df.sort_values(sort_cols, ascending=ascending)

        persist_results(db_path, mode, base_url, df)

        st.subheader("Quick Stats")
        pass_count = int(df["pass_estimate"].fillna(False).sum()) if "pass_estimate" in df.columns else 0
        c1, c2, c3 = st.columns(3)
        c1.metric("Pass Estimate", pass_count)
        c2.metric("Best Sharpe", f"{df['sharpe'].max():.3f}" if "sharpe" in df.columns and df["sharpe"].notna().any() else "n/a")
        c3.metric("Best Fitness", f"{df['fitness'].max():.3f}" if "fitness" in df.columns and df["fitness"].notna().any() else "n/a")

        st.subheader("Leaderboard")
        st.dataframe(df, width="stretch", height=520)

        csv_bytes = df.to_csv(index=False).encode("utf-8")
        json_bytes = df.to_json(orient="records", indent=2).encode("utf-8")

        c1, c2 = st.columns(2)
        with c1:
            st.download_button(
                label="Download CSV",
                data=csv_bytes,
                file_name="alpha_lab_results.csv",
                mime="text/csv",
            )
        with c2:
            st.download_button(
                label="Download JSON",
                data=json_bytes,
                file_name="alpha_lab_results.json",
                mime="application/json",
            )

    st.divider()
    st.subheader("History")
    h1, h2 = st.tabs(["Recent Runs", "Best Expressions"])
    with h1:
        recent = load_recent_history(db_path, limit=300)
        st.dataframe(recent, width="stretch", height=280)
    with h2:
        best = load_best_history(db_path, limit=100)
        st.dataframe(best, width="stretch", height=280)


if __name__ == "__main__":
    main()
