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
