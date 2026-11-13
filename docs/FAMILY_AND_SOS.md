# Family booking, SOS and the verified doctor card

## Family booking
- Patients add family members under **Family & SOS** (desktop sidebar, or the "Family care" tile on Home).
  Each member is their own patient record with their own home (same as the account, or a pin on the map).
- "Who is this for?" appears in **Doctor in 10 min** and **Book a home visit**. The nearest doctor to the
  member's home is sent. API: `member_id` on `POST /api/patient/visits/now` and `POST /api/patient/visits`,
  `?member=` on `/api/doctors`, `/api/visit-slots`, `/api/patient/online-nearby`.
- The managing account sees the member's visits, live map and visit notes, and gets every update
  (titles are prefixed with the member's first name).
- **Share live**: a read-only link `/track/<token>` (12 hours, can be turned off). It shows the doctor's
  position, ETA, name, registration and checks. It never shows the reason, notes, arrival code or the photo.

## SOS
- Red SOS button on every patient screen. One tap on "Send SOS now" starts a "Doctor now" visit marked SOS:
  no 10-minute check (nearest doctor however far), offer shown first to the doctor with a 30-second timer,
  and if nobody accepts the patient is told to call 108.
- Emergency contacts get an SMS with the live link (`adapters/sms.send_text`). Sandbox logs it; Twilio sends it;
  **MSG91 needs a DLT-registered SOS template before it can send**.
- Red-flag symptoms (chest pain, breathing trouble, stroke signs, unconscious, heavy bleeding, seizure, serious
  injury) show "Call 108 now". "Request ambulance" calls `adapters/ambulance.request`, which is a **sandbox**:
  108 has no public API, so a private ambulance partner with a B2B API still has to be chosen.
- If no doctor is online the SOS still alerts family and tells the patient to call 108.

## Verified doctor card
Shown on the live map once a doctor is assigned: photo (enrolled face photo, only after they accept), name,
specialty, qualification, experience, rating, languages, and three checks: medical registration (HPR or council),
ID and background check (ops approved), and the live face check for this visit (with the time it passed).

## Demo data
Meera manages her mother **Kamala** (own home, 4 Neem Street) and father **Raghav** (lives with her), and has two
emergency contacts. All fictional.

## Before a real launch
- Pick an ambulance partner and an SMS template (DLT) for SOS texts.
- Legal review: consent for managing an adult family member's health data (DPDP), and emergency disclaimers.
