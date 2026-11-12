# Triyana Home — From Doctor Visit to Medicine Delivery

Digital Prescription → Suggested Medicine Cart → Patient Selection → Licensed Pharmacy Approval → One-Tap Payment → Home Delivery.

> **Demo mode.** Every patient, doctor, medicine, pharmacy and payment in this repo is fictional. Pharmacy, payment and delivery integrations are sandbox adapters. Jurisdiction rules are illustrative and must be replaced with reviewed regulatory rules before any real use. Nothing here is medical advice.

## Run it

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload        # http://localhost:8000
python -m pytest -q
```

Or with Docker: `docker build -t triyana . && docker run -p 8000:8000 triyana`. To host a public demo, see [docs/DEPLOY.md](docs/DEPLOY.md).

### Two apps, one backend

| App | URL | Who | What |
|---|---|---|---|
| **Triyana** | `/` | Patients | Service tiles (Doctor now, book a visit, prescriptions, medicine cart, tracking, Yana), live map with ETA |
| **Triyana Partner** | `/provider` | Doctors, couriers, pharmacists, phlebotomists | Go online / offline, nearby request offers with a countdown, accept or decline, turn-by-turn navigation |

Both are installable PWAs (Add to Home Screen) with their own sign-in; a patient token is refused by the Partner app and vice versa (`X-Triyana-App` header).

**Dispatch (DoorDash/Dasher style)**, `services/dispatch.py`: a job goes to **one** provider at a time, nearest first. Only online, verified, not-busy providers within range get on-demand jobs. They have 45 s (`TRIYANA_OFFER_SECONDS`) to accept; a decline or timeout moves it to the next nearest. "Doctor now" visits go to online doctors; booked times go to the chosen doctor and, if declined, to the next nearest doctor free at that time. Packed delivery orders go to the nearest online courier, then pickup → patient.

**Live tracking.** On acceptance a trip starts. GPS is simulated along the route on the server (`TRIYANA_SIM_SPEEDUP`, default 8× faster) and real phone GPS overrides it when the Partner app posts `/api/provider/location`. The Partner app swaps the starter route for a real road route with turn-by-turn steps from the free OSRM demo server when reachable. Maps use Leaflet (vendored in `frontend/vendor/leaflet`) with OpenStreetMap data and CARTO tiles. For production, self-host OSRM or use a licensed routing/tiles provider, since the public demo servers have usage limits.

**Earnings (Partner app)**, `services/earnings.py`: every completed visit or delivery adds a pay line (visit fee, +₹100 for Doctor now; couriers get the pay shown on the request). The Earnings tab shows today, this week by day, each job's breakdown, the balance, Monday payouts and an instant **Cash out** (sandbox UPI).

Demo walk-through: open `/` as Meera and tap **Doctor now**. In another tab open `/provider` as Dr. Carter, accept the request, and watch both maps move. Decline instead to see it go to Dr. Rohan, then Dr. Vikram. Native app-store builds (Capacitor or React Native around the same API) are the next step.

The web app has a demo account switcher (patient, doctor, pharmacist, courier, hospital). Walk the journey: Dr. Carter accepts → starts → completes the visit → writes and signs a prescription → Meera reviews the cart, buys 3 of 5 tablets, removes another item, picks a pharmacy, authorises payment → Ravi reviews and dispenses → Asha delivers with Meera's handover code. Use **Reset demo** to start again.

**Lab tests at home**, `services/labs.py`: patients pick packages or single tests (search, categories, MRP vs price, fasting and sample info), then **Collect now** (nearest online phlebotomist, +₹99) or a one-hour slot (6 AM–7 PM, fasting-friendly morning slots suggested, free collection above ₹499). Payment is cash/UPI at the door or an online hold captured only after collection. The booking is dispatched like the other jobs (nearest first, 45 s for collect-now, decline goes to the next). The phlebotomist navigates to the patient, enters the patient's 4-digit collection code (and confirms fasting) to collect barcoded samples, then navigates to the NABL lab (demo) and hands over. The report appears in the patient app after `TRIYANA_LAB_REPORT_SECONDS` (default 60) with reference ranges, High/Low flags, PDF download, and a "Book a doctor" prompt. Demo: Meera → **Lab tests at home**; Partner app → **Priya · phlebotomist**.
For physiotherapy at home, open **Physio at home** as Meera, pick what hurts and a single session or a 5/10-session package, and choose "As soon as possible". In `/provider` sign in as **Ananya** (nearest online physio), accept, and follow the live map; on arrival start the session and write notes (pain before/after, exercises, home plan). Meera sees the notes under her booking. Arjun's knee package shows two finished sessions with notes.

For drones, sign in as **Nisha (Lotus Hospital)**: open **Coverage** to see which hospitals a drone can reach and why not, then **Send or request** to book a drone from GreenLeaf Pharmacy and follow it on the tracking map.

## How it works

| Area | Where | Key rules |
|---|---|---|
| Prescriptions | `services/prescriptions.py` | Only verified doctors, only after the visit starts. Drafts are invisible to patients. Signing hashes the content and HMAC-signs it; any later change breaks verification. Signed prescriptions are locked; changes go through a signed **amendment** that supersedes the original. |
| Suggested cart | `services/carts.py` | Created automatically on signing; patient is notified. Nothing is ordered or charged. Add, Request different quantity, Remove, Buy later, Ask pharmacist, Contact doctor. Cart changes never touch the prescription. |
| Quantity rules | `services/dispensing_rules.py` | Never more than prescribed. Controlled medicines: no in-app partial fills. Jurisdiction and pharmacy policy checked. Pack sizes validated. Restricted medicines need prescriber authorisation. Every reduction goes to the dispensing pharmacist, with a full-course warning. |
| Pharmacy matching | `services/matching.py` | Verified, licensed pharmacies in the jurisdiction and service area; live vs unconfirmed stock; partial-fill policy; price, fee, tax, ETA, hours, rating. Sort by nearest, price, fastest, rating, pickup. One balanced recommendation. |
| Checkout and payment | `services/orders.py`, `adapters/payments.py` | Idempotent. Re-checks and reserves stock (409 if it changed). Payment is **authorised only**. It is captured after pharmacist acceptance for the approved amount, voided on rejection, and refunded on cancellation. |
| Pharmacist and prescriber | `services/orders.py` | Validate signature, expiry and licence. Approve, adjust down, or reject. Clarification requests to the prescriber (quantity, unavailable, incomplete, substitution, refill). |
| Delivery | `adapters/delivery.py` | Standard, same-day, scheduled, priority, and drone. Tracking timeline, handover code as proof of delivery, ID checks, cold-chain flags. Pickup requires ID. |
| Drone delivery (India) | `services/drones.py`, `adapters/drones.py` | Every drone leg is checked against Drone Rules 2021-style rules: authorised operator, red zones (never flown), yellow zones (ATC permission, pad-to-pad corridors only), drone pads, payload and range limits, 2–8 °C cold box hold time, no controlled medicines, wind. If any check fails the leg goes by road courier and the reason is shown. Drone patient orders are re-checked at packing time; a road fallback refunds the fee difference. Mock operator in the style of Indian medical-drone operators; airspace is fictional. |
| Physiotherapy at home | `services/physio.py`, `routers/physio.py` | Verified physiotherapists only (registration shown to the patient). "As soon as possible" goes to the nearest online physio with a 45 s offer, then the next nearest; a booked time goes to the nearest physio free then. The physio who accepts keeps the whole package; package sessions are every other day and the patient can move any of them. Live map and turn-by-turn like doctor visits. Session notes (pain 0–10 before/after, exercises, home plan, next focus) are encrypted and visible only to the patient and their physio. Physios keep 80% of the session price (demo). |
| Hospital accounts | `services/hospitals.py` | Hospital staff request consignments (medicines, blood, vaccines, lab samples, anti-venom) from a pharmacy, or send to another hospital. A coverage view shows every hospital and pharmacy with drone or road time and the reason a drone can't fly. Live tracking map, eligibility checks, pilot and permission details, cold-chain log; only the receiving hospital confirms receipt. |
| Duplicate dispensing | `services/orders.py` | Ordered items are locked. Dispensed plus open quantities can't exceed quantity × (1 + refills). One dispensing record per order item. |
| My Medicines | `GET /api/patient/medicines` | Prescribed, ordered and dispensed quantities kept separate. Expiry, refill eligibility, messages, follow-up. |
| Yana | `services/yana.py` | Shows prescriptions, finds and compares pharmacies, changes purchase quantity, removes items, tracks orders. Refuses to change prescriptions or doses, suggest stopping a medicine, or approve substitutions. |
| Provider verification | `services/verification.py`, `adapters/verification.py`, `/admin` | New doctors and physios are looked up on the council registry (ABDM HPR) at sign-up. Every provider then adds a PAN (riders and collectors may use a driving licence) with consent, and the ID and a court-record search go to IDfy. Only a masked ID is stored. Triyana ops approve at `/admin` (admin key); approving with a failed or missing check needs an override and a note, and is audited. Demo partners run until keys are set. See `docs/VERIFICATION.md`. |
| Doctor face check before every visit | `services/face_verification.py`, `adapters/face.py`, `face.js`, `/admin` → Identity & security | Doctors enrol a live selfie with biometric consent at sign-up. Before **every** home visit they pass a live check (random liveness prompt + match to the enrolled face) for that visit, or the server refuses Start journey. Patients then see the verified photo, name and credentials and an arrival code the doctor enters at the door. Repeated failures or spoofing lock journeys and alert the security team; ops recover the doctor at `/admin`. Demo stand-in until a real vendor is set. See `docs/FACE_VERIFICATION.md`. |
| Security | `security.py`, `audit.py`, `deps.py` | Role-based access. Cross-patient and cross-pharmacy requests return 404. Health fields are encrypted at rest (Fernet). The audit log is hash-chained. `no-store` headers. |

## Going to production

Replace the sandbox adapters (`backend/app/adapters/`) with real pharmacy, e-prescribing, PSP and courier integrations. Move keys to a KMS. Swap demo bearer tokens for OIDC with clinician MFA. Use Postgres. Load jurisdiction rules from a maintained, reviewed source. For drones, contract a DGCA-authorised operator, pull the live airspace map and permissions from Digital Sky, and get BVLOS and state health-department approvals.
