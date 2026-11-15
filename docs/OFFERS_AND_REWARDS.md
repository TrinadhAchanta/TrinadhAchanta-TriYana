# Offers, membership, insurance, referrals and partners

Patient app: **Offers & rewards** (sidebar on desktop, home banner on phones). Ops: `/admin` → **Partners**.

| Feature | How it works | Setting |
|---|---|---|
| First visit ₹99 | A patient with no earlier (non-cancelled) visit pays ₹99 for their first one. | `TRIYANA_FIRST_VISIT_PRICE` |
| Triyana Family | Yearly plan. Visit fees covered for every visit booked from the account. | `TRIYANA_MEMBERSHIP_PRICE` (4999) |
| Cashless insurance | Patient adds a policy; at booking they tick "Cashless" and the visit is billed to the insurer. | sandbox adapter `adapters/insurance.py` |
| Refer a friend | Each patient has a code and a link `/?ref=CODE`. When the friend's first visit is completed, both get ₹200 credit, spent automatically on the next visit. | `TRIYANA_REFERRAL_REWARD` |
| Partner organisations | Societies, offices and old-age homes get a join code, a discount % and an optional priority label on doctor offers. | `/admin` → Partners |
| Promise kept | A "Doctor in 10 min" visit where the doctor reaches the door late is free automatically, and the patient is told. | `TRIYANA_PROMISE_MIN` |

Only one price offer applies per visit (membership, then first visit, then partner discount), then insurance, then credit.
**Doctors are always paid their full fee**: every discount is Triyana's cost.

## Before going live (needs business setup)
- **Payments:** membership uses the sandbox gateway. Hook it to Razorpay (subscriptions) before charging real money.
- **Insurance:** cashless OPD home visits need contracts with each insurer or TPA plus their pre-auth/claim APIs. The insurer list is just a picker today.
- **Unlimited visits:** "unlimited" on a yearly fee needs a fair-use policy and pricing check.
- **Promise kept:** decide if late free visits have limits (for example, traffic or patient-side delays), and put it in the terms.
- **Referral credit:** add terms (expiry, abuse checks such as one reward per device or phone).

## Promo codes

Patients type a code at the payment step: the doctor-visit price box (booking and "Doctor now"), prescription
checkout and the shop basket. Triyana Ops makes, schedules and pauses codes at `/admin` → Promo codes
(₹ off or % off with a cap, minimum bill, visits / medicines / both, uses per patient, total uses,
new customers only, start and end dates). Logic: `backend/app/services/promos.py`.

* Doctor visits: one offer per visit. The code competes with the ₹99 first visit or a partner discount and the
  patient gets whichever saves more (an unused code stays available). Not used with Triyana Family or cashless.
  Triyana credit is used after the code.
* Medicines: comes off the medicine price (before tax and delivery). If the pharmacist approves less, a % code
  shrinks with the bill.
* A use is given back when the visit/order is cancelled or rejected, or the visit is free because the doctor was late.
* Demo codes: DOC100 (₹100 off visits from ₹500), MEDS20 (20% off medicines up to ₹150, from ₹200), TRIYANA50.
* Before launch: decide fraud rules (one code per phone/device, not just per account) and GST treatment of discounts.
