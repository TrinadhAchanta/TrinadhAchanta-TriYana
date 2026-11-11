# Triyana Home — From Doctor Visit to Medicine Delivery

Digital Prescription → Suggested Medicine Cart → Patient Selection → Licensed Pharmacy Approval → One-Tap Payment → Home Delivery.

> **Demo mode.** Every patient, doctor, medicine, pharmacy and payment in this repo is fictional. Pharmacy, payment and delivery integrations are sandbox adapters. Jurisdiction rules are illustrative and must be replaced with reviewed regulatory rules before any real use. Nothing here is medical advice.

## Run it

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload        # http://localhost:8000
python -m pytest -q                  # 29 tests
```

The web app has a demo account switcher (patient, doctor, pharmacist, courier). Walk the journey: Dr. Kavya accepts → starts → completes the visit → writes and signs a prescription → Meera reviews the cart, buys 3 of 5 tablets, removes another item, picks a pharmacy, authorises payment → Ravi reviews and dispenses → Asha delivers with Meera's handover code. Use **Reset demo** to start again.

## How it works

| Area | Where | Key rules |
|---|---|---|
| Prescriptions | `services/prescriptions.py` | Only verified doctors, only after the visit starts. Drafts are invisible to patients. Signing hashes the content and HMAC-signs it; any later change breaks verification. Signed prescriptions are locked; changes go through a signed **amendment** that supersedes the original. |
| Suggested cart | `services/carts.py` | Created automatically on signing; patient is notified. Nothing is ordered or charged. Add, Request different quantity, Remove, Buy later, Ask pharmacist, Contact doctor. Cart changes never touch the prescription. |
| Quantity rules | `services/dispensing_rules.py` | Never more than prescribed. Controlled medicines: no in-app partial fills. Jurisdiction and pharmacy policy checked. Pack sizes validated. Restricted medicines need prescriber authorisation. Every reduction goes to the dispensing pharmacist, with a full-course warning. |
| Pharmacy matching | `services/matching.py` | Verified, licensed pharmacies in the jurisdiction and service area; live vs unconfirmed stock; partial-fill policy; price, fee, tax, ETA, hours, rating. Sort by nearest, price, fastest, rating, pickup. One balanced recommendation. |
| Checkout and payment | `services/orders.py`, `adapters/payments.py` | Idempotent. Re-checks and reserves stock (409 if it changed). Payment is **authorised only**. It is captured after pharmacist acceptance for the approved amount, voided on rejection, and refunded on cancellation. |
| Pharmacist and prescriber | `services/orders.py` | Validate signature, expiry and licence. Approve, adjust down, or reject. Clarification requests to the prescriber (quantity, unavailable, incomplete, substitution, refill). |
| Delivery | `adapters/delivery.py` | Standard, same-day, scheduled, priority, and drone (only where policy permits and not for cold-chain items). Tracking timeline, handover code as proof of delivery, ID checks, cold-chain flags. Pickup requires ID. |
| Duplicate dispensing | `services/orders.py` | Ordered items are locked. Dispensed plus open quantities can't exceed quantity × (1 + refills). One dispensing record per order item. |
| My Medicines | `GET /api/patient/medicines` | Prescribed, ordered and dispensed quantities kept separate. Expiry, refill eligibility, messages, follow-up. |
| Yana | `services/yana.py` | Shows prescriptions, finds and compares pharmacies, changes purchase quantity, removes items, tracks orders. Refuses to change prescriptions or doses, suggest stopping a medicine, or approve substitutions. |
| Security | `security.py`, `audit.py`, `deps.py` | Role-based access. Cross-patient and cross-pharmacy requests return 404. Health fields are encrypted at rest (Fernet). The audit log is hash-chained. `no-store` headers. |

## Going to production

Replace the sandbox adapters (`backend/app/adapters/`) with real pharmacy, e-prescribing, PSP and courier integrations. Move keys to a KMS. Swap demo bearer tokens for OIDC with clinician MFA. Use Postgres. Load jurisdiction rules from a maintained, reviewed source.
