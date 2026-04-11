#!/usr/bin/env python3
import json
import os
import time
from pathlib import Path

import requests


def as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def mask_secret(value: str, keep: int = 2) -> str:
    if not value:
        return "<empty>"
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}{'*' * (len(value) - keep * 2)}{value[-keep:]}"


def retry_after_seconds(resp: requests.Response, fallback: float) -> float:
    header = resp.headers.get("Retry-After", "").strip()
    if not header:
        return fallback
    try:
        return max(float(header), fallback)
    except ValueError:
        return fallback


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    timeout: int | float = 30,
    retries: int = 4,
    retry_base_sleep: float = 2.0,
    **kwargs,
) -> requests.Response:
    attempt = 0
    while True:
        resp = session.request(method, url, timeout=timeout, **kwargs)
        if resp.status_code != 429:
            return resp

        if attempt >= retries:
            return resp

        sleep_for = retry_after_seconds(resp, retry_base_sleep * (2**attempt))
        print(f"Rate limited (429). Waiting {sleep_for:.1f}s before retrying {method} {url}...")
        time.sleep(sleep_for)
        attempt += 1


def load_env_file(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and (value is None or value == ""):
        raise ValueError(f"Missing required environment variable: {name}")
    return value if value is not None else ""


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json", "Accept": "application/json"})
    return session


def authenticate(session: requests.Session, base_url: str) -> None:
    token = os.getenv("WQ_API_TOKEN", "").strip()
    if token:
        session.headers.update({"Authorization": f"Bearer {token}"})
        return

    username = env("WQ_USERNAME", "")
    email = env("WQ_EMAIL", "")
    password = env("WQ_PASSWORD", required=True)
    if not username and not email:
        raise ValueError("Missing credentials: set WQ_USERNAME or WQ_EMAIL, plus WQ_PASSWORD")

    login_candidates = [v for v in [username, email] if v]
    auth_path = env("WQ_AUTH_PATH", "/authentication")
    auth_check_path = env("WQ_AUTH_CHECK_PATH", auth_path)
    strict_auth_check = as_bool(env("WQ_STRICT_AUTH_CHECK", "0"))
    debug = as_bool(env("WQ_DEBUG", "0"))

    auth_url = f"{base_url.rstrip('/')}{auth_path}"
    auth_retries = int(env("WQ_AUTH_RETRIES", "5"))
    last_resp = None

    for login in login_candidates:
        if debug:
            print(f"Auth attempt -> url={auth_url}, login={mask_secret(login)}, password_len={len(password)}")

        resp = request_with_retry(
            session,
            "POST",
            auth_url,
            auth=(login, password),
            timeout=30,
            retries=auth_retries,
            retry_base_sleep=3.0,
        )
        last_resp = resp

        if resp.status_code < 400:
            # Keep basic auth available for subsequent requests.
            session.auth = (login, password)
            if debug:
                print(f"Auth accepted for login={mask_secret(login)}")
            break

        if resp.status_code == 401 and len(login_candidates) > 1:
            if debug:
                print(f"Auth 401 for login={mask_secret(login)}; trying next credential field.")
            continue

        break

    if last_resp is None:
        raise RuntimeError("Auth failed: no authentication request executed")

    if last_resp.status_code >= 400:
        if last_resp.status_code == 401:
            raise RuntimeError(
                "Auth failed (401 INVALID_CREDENTIALS). Check WQ_USERNAME/WQ_EMAIL and WQ_PASSWORD, "
                "or use WQ_API_TOKEN."
            )
        raise RuntimeError(f"Auth failed ({last_resp.status_code}): {last_resp.text[:500]}")

    # Optional auth verification endpoint check.
    check_url = f"{base_url.rstrip('/')}{auth_check_path}"
    check_resp = request_with_retry(
        session,
        "GET",
        check_url,
        timeout=30,
        retries=2,
        retry_base_sleep=2.0,
    )
    if check_resp.status_code >= 400:
        # Some deployments deny GET on auth-check endpoint while still allowing login + simulation.
        if check_resp.status_code in {401, 403, 404} and not strict_auth_check:
            if debug:
                print(
                    f"Auth check returned {check_resp.status_code}; continuing because "
                    f"WQ_STRICT_AUTH_CHECK=0"
                )
        else:
            raise RuntimeError(f"Auth check failed ({check_resp.status_code}): {check_resp.text[:500]}")

    # Some deployments return bearer token, others rely on session cookies.
    try:
        payload = last_resp.json()
    except Exception:
        payload = {}

    use_response_token = as_bool(env("WQ_USE_AUTH_RESPONSE_TOKEN", "0"))
    bearer = payload.get("token") or payload.get("access_token")
    if use_response_token and bearer:
        session.headers.update({"Authorization": f"Bearer {bearer}"})
        if debug:
            print("Using bearer token from auth response.")


def submit_simulation(session: requests.Session, base_url: str, expression: str) -> str:
    simulations_path = env("WQ_SIMULATIONS_PATH", "/simulations")
    url = f"{base_url.rstrip('/')}{simulations_path}"

    payload = {
        "type": "REGULAR",
        "settings": {
            "instrumentType": env("WQ_INSTRUMENT_TYPE", "EQUITY"),
            "region": env("WQ_REGION", "USA"),
            "universe": env("WQ_UNIVERSE", "TOP3000"),
            "delay": int(env("WQ_DELAY", "1")),
            "decay": int(env("WQ_DECAY", "0")),
            "neutralization": env("WQ_NEUTRALIZATION", "INDUSTRY"),
            "truncation": float(env("WQ_TRUNCATION", "0.01")),
            "visualization": as_bool(env("WQ_VISUALIZATION", "0")),
            "pasteurization": env("WQ_PASTEURIZATION", "ON"),
            "unitHandling": env("WQ_UNIT_HANDLING", "VERIFY"),
            "nanHandling": env("WQ_NAN_HANDLING", "OFF"),
            "language": env("WQ_LANGUAGE", "FASTEXPR"),
        },
        "regular": expression,
    }

    submit_retries = int(env("WQ_SUBMIT_RETRIES", "3"))
    resp = request_with_retry(
        session,
        "POST",
        url,
        data=json.dumps(payload),
        timeout=60,
        retries=submit_retries,
        retry_base_sleep=2.0,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Simulation submit failed ({resp.status_code}): {resp.text[:1000]}")

    location = resp.headers.get("Location")
    if location:
        sim_id = location.rstrip("/").split("/")[-1]
        return sim_id

    data = resp.json()
    for key in ("id", "simulationId", "alphaId"):
        if key in data:
            return str(data[key])

    raise RuntimeError("Could not determine simulation id from response")


def poll_simulation(session: requests.Session, base_url: str, simulation_id: str) -> dict:
    template = env("WQ_SIMULATION_RESULT_TEMPLATE", "/simulations/{id}")
    url = f"{base_url.rstrip('/')}{template.format(id=simulation_id)}"

    max_attempts = int(env("WQ_POLL_ATTEMPTS", "120"))
    interval_sec = float(env("WQ_POLL_INTERVAL_SEC", "2"))

    for _ in range(max_attempts):
        resp = request_with_retry(
            session,
            "GET",
            url,
            timeout=30,
            retries=2,
            retry_base_sleep=2.0,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Polling failed ({resp.status_code}): {resp.text[:500]}")

        data = resp.json()
        status = str(data.get("status", "")).upper()
        if status in {"COMPLETE", "DONE", "SUCCESS", "FINISHED"}:
            return data
        if status in {"FAILED", "ERROR", "REJECTED"}:
            raise RuntimeError(f"Simulation ended with status={status}: {json.dumps(data)[:1000]}")

        time.sleep(interval_sec)

    raise TimeoutError("Polling timed out before simulation completed")


def main() -> None:
    load_env_file()

    base_url = env("WQ_BASE_URL", "https://api.worldquantbrain.com")
    expression = env("WQ_EXPRESSION", "reverse(returns)")
    debug = as_bool(env("WQ_DEBUG", "0"))

    if debug:
        print(f"Base URL: {base_url}")
        print(f"Expression: {expression}")
        token_present = bool(env("WQ_API_TOKEN", ""))
        print(f"Token auth enabled: {token_present}")
        print(f"Username present: {bool(env('WQ_USERNAME', ''))}")
        print(f"Email present: {bool(env('WQ_EMAIL', ''))}")

    session = make_session()
    authenticate(session, base_url)
    try:
        sim_id = submit_simulation(session, base_url, expression)
    except RuntimeError as exc:
        message = str(exc)
        if "(401)" in message:
            print("Submit returned 401. Re-authenticating once and retrying...")
            session.headers.pop("Authorization", None)
            authenticate(session, base_url)
            sim_id = submit_simulation(session, base_url, expression)
        else:
            raise
    print(f"Submitted simulation: {sim_id}")

    result = poll_simulation(session, base_url, sim_id)
    print("Simulation complete.")
    print(json.dumps(result, indent=2)[:5000])


if __name__ == "__main__":
    main()
