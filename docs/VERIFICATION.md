# Provider verification partners

Every doctor, physiotherapist, rider and sample collector who signs up in Triyana Partner
starts as **pending** and cannot go online until a person at Triyana approves them. Before
that, two partners check them automatically:

| Check | Who | Partner | When |
|---|---|---|---|
| Council registration | Doctors, physios | ABDM Healthcare Professionals Registry (HPR) | Straight after sign-up |
| ID check | Everyone | IDfy (PAN or driving licence, against the issuing authority) | When the provider adds their ID in the app |
| Court records | Everyone | IDfy court-record search | Same time as the ID check |
| Final review | Everyone | Triyana ops at `/admin` | When the checks are back |

Results show to the provider on their Partner dashboard and to ops at `/admin`, where each
provider is **Ready to approve** (all passed), **Flagged** (something needs a look),
**Checks running** or **Waiting for provider's ID**. Approving a provider whose checks did not
all pass needs an override with a note (for example "Checked the TSMC register by phone"); the
note is saved with the account and the approval is written to the audit log.

Only the ID type, a masked number (`••••••234F`) and the partner's reference are stored. The
provider ticks a consent box before the ID and court-record check runs, and that consent is
written to the audit log (DPDP Act).

## What runs today

Both partners run in **demo mode** until keys are set. Demo rules, so you can try every path:

* Registration numbers containing `FAIL` are not on the register; `MISMATCH` are registered under another name.
* A PAN must be an individual's PAN (4th letter `P`, e.g. `ABCPR1234F`).
* An ID number containing `9999` comes back with a court record to review.

Until `TRIYANA_ADMIN_KEY` is set, the demo site's `/admin` page accepts the key `demo-admin`.
The "Approve me (demo only)" button in the Partner app still works while `TRIYANA_DEMO=1`.

## Keys you need

### 1. Triyana admin key (do this first, free)

Make a long random string and set `TRIYANA_ADMIN_KEY` on Render. From then on `demo-admin` stops working.

### 2. ABDM HPR (free, government)

1. Register Triyana as a Health Information User/Provider on the ABDM sandbox: https://sandbox.abdm.gov.in
   You receive a **Client ID** and **Client Secret** for the sandbox.
2. Set on Render:
   * `TRIYANA_REGISTRY_PROVIDER=hpr`
   * `ABDM_CLIENT_ID`, `ABDM_CLIENT_SECRET`
3. After ABDM approves the sandbox integration (they run a functional test), you get production
   credentials. Point the service at production with `ABDM_GATEWAY_URL` and `HPR_BASE_URL`.

HPR lists doctors and nurses fully; allied-health councils (physiotherapy) are still being added, so a
physio not found on HPR is flagged for a manual check of the state council register instead of being
rejected. The exact HPR search path can be changed with `HPR_SEARCH_PATH` if ABDM's onboarding docs
give a different one; the code reads the name, council, status and HPR ID from the response.

### 3. IDfy (paid, per check)

1. Sign a contract with IDfy (https://www.idfy.com) for **PAN verification**, **driving licence
   verification** and a **court-record / criminal check**. They give you an **Account ID** and an **API key**,
   and the task name for the court-record check on your contract.
2. Set on Render:
   * `TRIYANA_BACKGROUND_PROVIDER=idfy`
   * `IDFY_ACCOUNT_ID`, `IDFY_API_KEY`
   * `IDFY_COURT_TASK` (the court-record task name IDfy gives you). If it is not set, the court-records
     line is flagged for a manual police-verification check.
3. IDfy checks are asynchronous. Triyana fetches results when the provider or ops opens the
   verification screen, and **Re-run registry check** on `/admin` refreshes everything.

**AuthBridge instead of IDfy:** add an `authbridge` branch to `backend/app/adapters/verification.py`
with the same `verify_id`, `court_record_check` and `poll` functions; nothing else changes.

## Before real providers

* Have the consent text in the Partner app reviewed by your lawyer (DPDP Act, and the partner's own terms).
* Decide who on the team holds the admin key, and switch `TRIYANA_DEMO=0` so "Approve me" disappears.
* Check the name-matching rule in `names_match` against real HPR data; it accepts initials ("N Rao" = "Neha Rao").
