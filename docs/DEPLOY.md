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
| `RAZORPAY_KEY_ID` | unset | Razorpay key. Use a `rzp_test_...` key for test mode. When unset, the built-in sandbox is used. |
| `RAZORPAY_KEY_SECRET` | unset | Razorpay key secret. Set it as a secret, never in code. |
| `TRIYANA_ADMIN_KEY` | unset | Key for the ops review page at `/admin`. Until it is set, the demo site accepts `demo-admin`. |
| `TRIYANA_REGISTRY_PROVIDER` | `demo` | `hpr` to look doctors up on the ABDM Healthcare Professionals Registry. See `docs/VERIFICATION.md`. |
| `TRIYANA_BACKGROUND_PROVIDER` | `demo` | `idfy` for real ID and court-record checks. See `docs/VERIFICATION.md`. |

## Turn on Razorpay (India)

1. Create a Razorpay account and open **Account & Settings → API Keys** in **Test mode**. Generate a key.
2. In Render, open the `triyana-demo` service → **Environment**, add `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET`, and save. Render redeploys.
3. At checkout the patient now pays in the Razorpay window (UPI, cards, netbanking, wallets). Test mode never moves real money; use Razorpay's test UPI ID `success@razorpay` or their test cards.

Payments are authorised only (manual capture). The order is captured when the pharmacist approves it. If the pharmacist approves less, the difference is refunded immediately. If they reject it, Razorpay refunds the uncaptured payment automatically. Card numbers and UPI PINs never reach Triyana's servers.

## India rules built in

- **Drug schedules:** Schedule X medicines are never sold online (the patient is told to buy in person with the original prescription). Schedule H1 orders can't be approved until the pharmacist confirms the H1 register entry. H and H1 are labelled for patients and pharmacists. Demo classifications must be checked against CDSCO before launch.
- **Doctor registration:** each doctor shows their registration number, medical council and qualification on prescriptions and in booking.
- **DPDP Act 2023:** patients see a consent notice before booking or ordering. Consent is recorded with the notice version and can be withdrawn. Patients can download their data and request erasure or correction.

## Demo-only, not for real patients

With `TRIYANA_DEMO=1`, anyone who opens the site can sign in as any demo account and reset the data. All data is fictional, and the pharmacy, payment and courier adapters are sandboxes. Do not enter real patient information.
