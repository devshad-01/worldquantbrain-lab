#!/usr/bin/env python3
import argparse
import concurrent.futures
import json
import random
import time
from dataclasses import dataclass
from typing import Any

from worldquant_api_starter import (
    authenticate,
    env,
    load_env_file,
    make_session,
    request_with_retry,
    submit_simulation,
    poll_simulation,
)


@dataclass
class AlphaRun:
    expression: str
    simulation_id: str
    alpha_id: str
    sharpe: float | None
    fitness: float | None
    turnover: float | None
    returns: float | None
    drawdown: float | None
    score: float


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


def fetch_alpha_details(session, base_url: str, alpha_id: str) -> dict:
    template = env("WQ_ALPHA_RESULT_TEMPLATE", "/alphas/{id}")
    url = f"{base_url.rstrip('/')}{template.format(id=alpha_id)}"
    resp = request_with_retry(session, "GET", url, timeout=30, retries=2, retry_base_sleep=2.0)
    if resp.status_code >= 400:
        raise RuntimeError(f"Alpha fetch failed ({resp.status_code}): {resp.text[:500]}")
    return resp.json()


def metrics_from_payload(payload: dict) -> tuple[float | None, float | None, float | None, float | None, float | None]:
    sharpe = find_first_numeric(payload, {"sharpe"})
    fitness = find_first_numeric(payload, {"fitness"})
    turnover = find_first_numeric(payload, {"turnover"})
    returns = find_first_numeric(payload, {"returns"})
    drawdown = find_first_numeric(payload, {"drawdown"})
    return sharpe, fitness, turnover, returns, drawdown


def score_run(sharpe: float | None, fitness: float | None, turnover: float | None, drawdown: float | None) -> float:
    score = 0.0
    if sharpe is not None:
        score += sharpe * 2.0
    if fitness is not None:
        score += fitness * 0.8
    if turnover is not None:
        score -= max(turnover - 35.0, 0) * 0.02
    if drawdown is not None:
        score -= max(drawdown - 20.0, 0) * 0.05
    return score


def base_expressions() -> list[str]:
    return [
        "reverse(returns)",
        "rank(ts_mean(returns,5))",
        "rank(ts_mean(returns,20)-ts_mean(returns,60))",
        "rank(ts_delta(close,3)/ts_delay(close,1))",
        "rank((close-open)/open)",
        "rank(ts_corr(returns, volume, 20))",
        "rank(ts_std_dev(returns,20)) * -1",
        "rank((vwap-close)/close)",
        "rank(ts_rank(returns,10)-ts_rank(returns,60))",
        "rank(group_zscore(returns, industry))",
    ]


def mutate_expression(expr: str, rng: random.Random) -> str:
    variants = [
        f"rank({expr})",
        f"-1*({expr})",
        f"ts_mean({expr}, 3)",
        f"ts_mean({expr}, 5)",
        f"ts_zscore({expr}, 20)",
        f"decay_linear({expr}, 5)",
        f"group_neutralize({expr}, industry)",
        f"rank({expr}) - rank(ts_mean(returns,20))",
        f"rank({expr}) * rank(ts_mean(volume,20))",
        f"if_else(rank(ts_std_dev(returns,20)) > 0.7, {expr}, reverse(returns))",
    ]
    return rng.choice(variants)


def build_round_candidates(previous_best: list[AlphaRun], batch_size: int, rng: random.Random) -> list[str]:
    if not previous_best:
        seeds = base_expressions()
        return seeds[:batch_size] if batch_size <= len(seeds) else seeds + [rng.choice(seeds) for _ in range(batch_size - len(seeds))]

    seeds = [run.expression for run in previous_best[: min(4, len(previous_best))]]
    candidates: list[str] = []
    while len(candidates) < batch_size:
        seed = rng.choice(seeds)
        candidates.append(mutate_expression(seed, rng))
    return candidates


def evaluate_expression(session, base_url: str, expression: str) -> AlphaRun:
    simulation_id = submit_simulation(session, base_url, expression)
    sim_result = poll_simulation(session, base_url, simulation_id)
    alpha_id = str(sim_result.get("alpha", ""))

    sharpe = fitness = turnover = returns = drawdown = None
    if alpha_id:
        details = fetch_alpha_details(session, base_url, alpha_id)
        sharpe, fitness, turnover, returns, drawdown = metrics_from_payload(details)

    score = score_run(sharpe, fitness, turnover, drawdown)
    return AlphaRun(
        expression=expression,
        simulation_id=simulation_id,
        alpha_id=alpha_id,
        sharpe=sharpe,
        fitness=fitness,
        turnover=turnover,
        returns=returns,
        drawdown=drawdown,
        score=score,
    )


def evaluate_expression_with_auth(base_url: str, expression: str) -> AlphaRun:
    session = make_session()
    authenticate(session, base_url)
    return evaluate_expression(session, base_url, expression)


def run_tuning(
    iterations: int,
    batch_size: int,
    target_sharpe: float,
    pause_sec: float,
    seed: int,
    max_workers: int,
) -> list[AlphaRun]:
    load_env_file()
    base_url = env("WQ_BASE_URL", "https://api.worldquantbrain.com")

    rng = random.Random(seed)
    history: list[AlphaRun] = []
    previous_best: list[AlphaRun] = []

    for round_idx in range(1, iterations + 1):
        candidates = build_round_candidates(previous_best, batch_size, rng)
        print(f"\n=== Round {round_idx}/{iterations} | candidates={len(candidates)} ===")

        round_runs: list[AlphaRun] = []
        if max_workers <= 1:
            for idx, expr in enumerate(candidates, start=1):
                print(f"[{round_idx}.{idx}] Simulating: {expr}")
                try:
                    run = evaluate_expression_with_auth(base_url, expr)
                    round_runs.append(run)
                    history.append(run)
                    print(
                        f"  -> alpha={run.alpha_id or '-'} sharpe={run.sharpe} fitness={run.fitness} "
                        f"turnover={run.turnover} score={run.score:.3f}"
                    )
                    if run.sharpe is not None and run.sharpe >= target_sharpe:
                        print(f"Target reached: Sharpe {run.sharpe} >= {target_sharpe}")
                        return sorted(history, key=lambda x: x.score, reverse=True)
                except Exception as exc:
                    print(f"  -> failed: {exc}")

                if pause_sec > 0:
                    time.sleep(pause_sec)
        else:
            print(f"Running in parallel with max_workers={max_workers}")
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {
                    executor.submit(evaluate_expression_with_auth, base_url, expr): (idx, expr)
                    for idx, expr in enumerate(candidates, start=1)
                }

                target_hit = False
                for future in concurrent.futures.as_completed(future_map):
                    idx, expr = future_map[future]
                    print(f"[{round_idx}.{idx}] Completed: {expr}")
                    try:
                        run = future.result()
                        round_runs.append(run)
                        history.append(run)
                        print(
                            f"  -> alpha={run.alpha_id or '-'} sharpe={run.sharpe} fitness={run.fitness} "
                            f"turnover={run.turnover} score={run.score:.3f}"
                        )
                        if run.sharpe is not None and run.sharpe >= target_sharpe:
                            target_hit = True
                    except Exception as exc:
                        print(f"  -> failed: {exc}")

                if target_hit:
                    print(f"Target reached in parallel batch: Sharpe >= {target_sharpe}")
                    return sorted(history, key=lambda x: x.score, reverse=True)

        previous_best = sorted(round_runs, key=lambda x: x.score, reverse=True)[: max(2, batch_size // 3)]

    return sorted(history, key=lambda x: x.score, reverse=True)


def as_dict(run: AlphaRun) -> dict:
    return {
        "expression": run.expression,
        "simulation_id": run.simulation_id,
        "alpha_id": run.alpha_id,
        "sharpe": run.sharpe,
        "fitness": run.fitness,
        "turnover": run.turnover,
        "returns": run.returns,
        "drawdown": run.drawdown,
        "score": run.score,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Iterative WorldQuant alpha tuner")
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--target-sharpe", type=float, default=2.0)
    parser.add_argument("--pause-sec", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--output", type=str, default="alpha_tuning_results.json")
    args = parser.parse_args()

    ranked = run_tuning(
        iterations=args.iterations,
        batch_size=args.batch_size,
        target_sharpe=args.target_sharpe,
        pause_sec=args.pause_sec,
        seed=args.seed,
        max_workers=max(1, args.max_workers),
    )

    top = ranked[: min(10, len(ranked))]
    print("\n=== Top Candidates ===")
    for idx, run in enumerate(top, start=1):
        print(
            f"{idx:02d}. sharpe={run.sharpe} fitness={run.fitness} turnover={run.turnover} "
            f"score={run.score:.3f} alpha={run.alpha_id}"
        )
        print(f"    {run.expression}")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump([as_dict(item) for item in ranked], f, indent=2)
    print(f"\nSaved {len(ranked)} runs to {args.output}")


if __name__ == "__main__":
    main()
