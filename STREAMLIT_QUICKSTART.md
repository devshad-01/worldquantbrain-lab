# WorldQuant Alpha Lab (Streamlit)

## 1) Install dependencies

```bash
pip install -r requirements-streamlit.txt
```

## 2) Ensure `.env` is configured

The app reuses the same credentials and API settings from your existing `.env`.

## 3) Run app

```bash
streamlit run streamlit_app.py
```

## 4) Use modes

- **Alpha Sweep**: many alphas, one settings profile
- **Settings Sweep**: one alpha, many settings profiles
- **Hybrid**: base run for all, then settings sweep on top-N

## 5) Output

- Live progress updates
- Leaderboard table in app
- Download CSV/JSON

## Notes

- Start with `Parallel workers = 2` or `3` to reduce rate-limit risk.
- Increase workers only if stable.
