# Deployment Summary — Aircraft Maintenance Assistant

The app is a **Streamlit** web app and can be deployed to the internet in two main ways.

---

## 1. Render (Docker)

- **How:** Push the repo to GitHub, then in [Render](https://dashboard.render.com) create a **Web Service** and connect the repo. Render builds the project’s **Dockerfile** and runs `streamlit run app.py` on the port it provides (`PORT` env, default 10000).
- **Config:** A **Blueprint** is in `render.yaml` (one-click setup). You still add environment variables in the Render dashboard: `OPENAI_API_KEY`, `UNSTRUCTURED_*`, `QDRANT_URL`, `QDRANT_API_KEY`.
- **Result:** App is available at a URL like `https://aircraft-maintenance.onrender.com`. Free tier may spin down after inactivity; Starter ($7/mo) keeps it always on.

---

## 2. Streamlit Community Cloud

- **How:** Push to GitHub, then at [share.streamlit.io](https://share.streamlit.io) sign in with GitHub, create a **New app**, and point it at this repo with main file `app.py`. Add the same keys as **Secrets** (TOML format in Advanced settings).
- **Result:** Streamlit hosts the app; it talks to **Qdrant Cloud** and **OpenAI** — no local Qdrant or VPN needed.

---

## Common points

- **Secrets:** Never commit `.env`. Use platform **environment variables** (Render) or **Streamlit Secrets** (Community Cloud).
- **Backend:** Production uses **Qdrant Cloud** (`QDRANT_URL` / `QDRANT_API_KEY`). The app runs `streamlit run app.py`; no custom server process.
- **Other options:** The README also mentions Railway, Fly.io, or a VPS — run `streamlit run app.py` and expose the port, with keys in env vars.
