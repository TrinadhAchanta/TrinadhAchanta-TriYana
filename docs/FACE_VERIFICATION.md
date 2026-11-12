# Doctor face verification before every home visit

No doctor can start a home-visit journey without passing a live face check **for that specific
visit**, or an equivalent check approved by Triyana's identity team. The server enforces this; the
Partner app only runs the camera and shows the result.

## How it works

### 1. At registration

1. The doctor signs up in Triyana Partner (`/provider`). Their council registration (ABDM HPR), PAN and
   court records are checked by the existing partners (see [VERIFICATION.md](VERIFICATION.md)).
2. They give **biometric consent** (versioned text, stored as a `biometric_face` consent record) and take
   a live selfie. The face partner checks liveness and enrols the face. This adds a **Live face enrolment**
   check to their verification list.
3. Ops approves the account at `/admin` and sees the enrolment photo next to the checks to compare with the ID.
   A doctor can't be approved without an enrolled face, even with an override.
4. Until approval, they can't go online, accept a visit or start a journey.

### 2. Before every visit

1. The doctor accepts the visit. For "Doctor now" the journey no longer starts automatically.
2. **Verify face & start journey** opens the in-app camera. The server issues a one-time challenge (2 minutes,
   single use, tied to that doctor's account and that visit) with a random prompt (turn left, nod, blink…).
3. The app captures 4 frames while the doctor follows the prompt and sends them with the challenge.
4. The partner checks liveness and compares the face with the enrolled face.
5. On a pass, `POST /api/provider/visits/{id}/depart` is allowed for 15 minutes (`TRIYANA_FACE_PASS_MINUTES`).
   Without a pass it returns `403 face_check_required`, whatever the app sends.
6. At the door the doctor types the patient's 4-digit **arrival code** to start the visit.

### 3. What the patient sees

- A notification once the doctor is verified.
- In the live map: **Identity verified** badge, the verified profile photo, name, qualification,
  registration number and council, and the time and method of the check.
- The arrival code, and confirmation when the doctor enters it.
- Never: scores, templates, ID numbers or documents. The photo shows only during that patient's open,
  verified visit.

### 4. When it fails

| Situation | What happens |
|---|---|
| Poor lighting, covered camera | "Try again" with a tip. Doesn't count as a failed attempt. |
| Wrong face / not live | Counts. 3 per visit, then the doctor is locked out and a case opens. |
| Printed photo, screen replay, repeated or identical frames | Treated as spoofing: locked out on every visit, taken offline, high-severity alert. |
| Network drop, slow upload | Challenge expires. Nothing passes. Start again. |
| Camera permission denied, no camera, accessibility need | "Ask for another way to verify" opens a request for the identity team. |
| 5 wrong arrival codes | Locked out, case opens, alert. |

Every alert is written to the hash-chained audit log, logged as a warning, and posted to
`TRIYANA_SECURITY_WEBHOOK_URL` (Slack, Teams, PagerDuty…) when that is set. Only IDs and the alert type are sent.

### 5. Recovery (Ops → Identity & security)

Each case shows the doctor, their enrolled photo, recent checks and scores. A note is always required.

- **Allow retries**: clears the counter.
- **Approve alternative check for this visit**: after verifying the doctor another way (for example a video call
  with ID). Unlocks that one visit for 60 minutes and the patient sees "Approved alternative check".
- **Require re-enrolment**: revokes the enrolled face. The doctor enrols again and ops approves the new face.
- **Suspend account**.

The **Face check log** tab lists every check with result, scores and time. No images.

## Data kept

| Data | Where | Retention (proposed, needs legal sign-off) |
|---|---|---|
| Face template | Face partner only (`template_ref` in Triyana) | Until consent is withdrawn or the account closes |
| Profile photo (240 px) | `face_enrollments.photo`, encrypted at rest | Same; deleted on withdrawal, re-enrolment or revocation |
| Visit check frames | **Not stored** | — |
| SHA-256 of each frame | `face_checks.frame_digests` | 30 days, to catch replays |
| Outcome, scores, times | `face_checks` + audit log | Per audit policy |

Doctors can withdraw consent in Account → Face verification. That deletes the photo and revokes the
enrolment; they can't take visits until they enrol again or ops approves an alternative.

## The demo stand-in and the real vendor

`TRIYANA_FACE_PROVIDER=demo` (default) runs only while `TRIYANA_DEMO=1`. With demo mode off and no real
vendor configured, every check fails closed.

The stand-in really checks: image validity and size, lighting, a blank or covered camera, movement between
frames, and identical or replayed frames. It **cannot** detect a good printed photo or screen, and it does not
really compare faces: any live face "matches". On the demo site, testers pick a failure case under
"Demo: test a failure case" in the camera screen (someone else's face, printed photo, video replay, poor
lighting). These can only make a check fail.

### To go live you need

1. **A face liveness + face match vendor** with ISO 30107-3 (iBeta level 2) certified liveness. Options that
   serve India:
   - **HyperVerge**: face liveness, face match, selfie-to-ID match. Web and native SDKs.
   - **IDfy**: already the ID/court-record partner, so adding face liveness and face match to that contract
     may be simplest.
   - **AWS Rekognition Face Liveness + CompareFaces**: global, needs an AWS account and the Amplify
     liveness component in the app.
2. Their **capture SDK in the Partner app** for certified passive liveness, which works best in a native app.
3. API keys as environment variables, and a new branch in `backend/app/adapters/face.py` (`enroll` and
   `verify`), with the same outcomes: `passed`, `failed`, `spoof`, `poor_quality`.
4. **Selfie-to-ID match at enrolment**, for example against the DigiLocker Aadhaar photo or driving licence
   photo, so the enrolled face is tied to the government ID.
5. Per-person staff accounts with roles for `/admin` instead of one shared admin key, so only the security team
   sees faces and resolves cases.
6. `TRIYANA_SECURITY_WEBHOOK_URL` pointing at the security team's channel.

## For legal review (not a compliance claim)

- **DPDP Act 2023 and DPDP Rules 2025**: a face template is personal data. Check the consent notice
  (free, specific, informed, itemised, withdrawable), purpose limitation, retention and erasure periods, breach
  notice, the processor contract with the face vendor, and whether Triyana could be a Significant Data Fiduciary.
- **IT Act SPDI Rules 2011**: biometrics are sensitive personal data (written consent, a published policy)
  until DPDP replaces them.
- **Consent tied to work**: doctors can't take visits without it. Check that consent is still valid when it is a
  condition of work, and that the alternative check is a real option.
- **Retention periods** in the table above are proposals.
- **US state biometric laws** (Illinois BIPA, Texas CUBI, Washington) apply only if Triyana serves those states.
  BIPA needs a public retention schedule and written release.
- **Accessibility**: the alternative check covers doctors who can't use a camera or follow the prompts.
  Check that it meets the RPwD Act 2016.
- **Patients' view of the doctor's photo**: check that showing it during a verified visit is covered by the
  doctor's consent text.
- **Cross-border transfer** if the vendor processes faces outside India.
