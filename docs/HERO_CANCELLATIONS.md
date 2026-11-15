# Heros: cancel at the door, with a reason

Once a Hero (doctor of any specialty, sample collector or physiotherapist) has **arrived** at the patient's
address and can't go ahead, the navigation screen shows **Call patient** and **Cancel visit / collection / session**.

## Reasons
| Reason | Needs a call + short wait first | Hero gets wasted-trip pay |
|---|---|---|
| Patient not answering phone or door | yes | yes |
| Patient not at the address | yes | yes |
| Wrong or incomplete address | no | yes |
| Patient refused the visit | no | yes |
| Unsafe to go in | no | yes |
| Other reason (note required) | no | no, ops review |

The wait is `TRIYANA_NO_SHOW_WAIT_MIN` (5 minutes live, 1 minute on the demo). Pay is `TRIYANA_NO_SHOW_PAY` (default ₹100).

## Money (demo choice)
* The patient is never charged: visits charge nothing, lab payment holds are voided, and a missed physio
  session inside a package is replaced at the end of the package (a single session is simply cancelled).
* A no-show fee for patients is **not** switched on. Decide on it (and say so in the terms) before launch.

## Who sees what
* Patient: a notification, the reason on the live map, and a "Cancelled at your door" card on Home for 2 days.
* Triyana Ops: `/admin` → **Hero cancellations** (Hero, job, patient, reason, note, calls, minutes waited, pay).

## Not covered
Medicine deliveries (riders). A failed delivery needs a return-to-pharmacy flow and refund rules for medicines.
