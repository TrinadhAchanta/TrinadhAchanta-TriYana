# Deploying the Triyana demo

The demo is a single container: the FastAPI backend serves the API and the web app on one port.

## Run locally with Docker

```bash
docker build -t triyana .
docker run -p 8000:8000 -e TRIYANA_SECRET="$(openssl rand -hex 32)" -v triyana-data:/data triyana
# open http://localhost:8000
```

## Host it (Render, Railway, Fly.io, Cloud Run …)

1. Point the service at this repo; it will detect the `Dockerfile`.
2. Set environment variables:
   - `TRIYANA_SECRET`: a long random string. Keep it stable, because it encrypts stored health fields and signs prescriptions.
   - `PORT`: usually set by the host automatically.
3. Optional: mount a persistent volume at `/data` so demo data survives restarts.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `TRIYANA_SECRET` | demo value | Encryption and signature key material. **Always set in any hosted environment.** |
| `TRIYANA_DATABASE_URL` | `sqlite:////data/triyana_demo.db` | SQLAlchemy URL. Use Postgres for anything beyond a demo. |
| `TRIYANA_DEMO` | `1` | Enables the demo account switcher and **Reset demo**. Set to `0` to hide both. |

## Demo-only, not for real patients

With `TRIYANA_DEMO=1`, anyone who opens the site can sign in as any demo account and reset the data. All data is fictional, and the pharmacy, payment and courier adapters are sandboxes. Do not enter real patient information.
