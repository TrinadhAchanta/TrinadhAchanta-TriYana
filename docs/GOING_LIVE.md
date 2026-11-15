# Going live: demo mode vs live mode

One setting decides it: `TRIYANA_DEMO`.

| | Demo (`TRIYANA_DEMO=1`, default) | Live (`TRIYANA_DEMO=0`) |
|---|---|---|
| Demo accounts (Dr. Carter, Meera…) | Listed on the sign-in screen | Hidden; their fixed tokens no longer sign anyone in; demo doctors/riders are taken off duty and unverified so real patients are never sent to them |
| "Approve me (demo only)" | Shown | Gone. Only an admin in `/admin` can approve a provider |
| "Reset demo" | Shown (until real people sign up) | Gone |
| SMS codes | Shown on screen when no SMS gateway is set | Never shown. Without a real gateway nobody can sign up or reset a password |
| Face check before visits | Demo stand-in | Refuses every check until a real vendor is connected (fails closed) |
| `TRIYANA_SECRET` | Default allowed (warning) | **Required**, at least 32 random characters, or the app will not start |

`/admin` → **Launch check** shows which of these are ready, without showing any secret values.

## The secret key

`TRIYANA_SECRET` derives the key that encrypts health records at rest, the prescription e-signatures,
and the push-alert key. Make one with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

* Set it **before** any real data exists, keep a copy in a password manager, and don't change it casually:
  data written with one secret can't be read with another.
* To rotate: move the old value into `TRIYANA_OLD_SECRETS` and put the new one in `TRIYANA_SECRET`.
  Old records and prescriptions stay readable and verifiable.

## Order of switching on

1. `TRIYANA_SECRET` (safe to set on the demo right away).
2. `TRIYANA_DATABASE_URL` → Postgres, so accounts survive deploys.
3. `TRIYANA_ADMINS=you@x.in:password;partner@x.in:password` so `/admin` logins exist from the first boot.
4. SMS: `TRIYANA_SMS_PROVIDER=msg91`, `MSG91_AUTH_KEY`, `MSG91_TEMPLATE_ID` (DLT-approved OTP template).
5. Payments: `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` (live keys after KYC).
6. Face check vendor (see `FACE_VERIFICATION.md`). Until then doctors can't start visits in live mode.
7. Finally `TRIYANA_DEMO=0`. If the secret is missing the deploy fails and the previous version keeps running.

## Forgot password

Both apps have **Forgot password?** on the sign-in screen. We text a 6-digit code to the mobile
number the person verified at sign-up (same SMS gateway and limits as sign-up codes: 30 s between
sends, 5 per hour, 5 wrong tries per code, plus a per-email lockout). The new password signs out
every other device and stops push alerts to them; the person gets a "Your password was changed"
notice. People without a verified number are told to contact support.

## Push alerts (doctors' phones ring while locked)

* Standard Web Push: no Firebase project, app store build or extra keys needed. The push key is
  derived from `TRIYANA_SECRET` (or set `TRIYANA_VAPID_PRIVATE_KEY`).
* After sign-in the app offers **Turn on alerts**; it's also in Account → **Alerts on this phone**,
  with a test button.
* Every in-app notification is pushed: new visit/delivery offers ring loudly (high urgency, stays on
  screen, expires with the offer), patients get "Doctor accepted / on the way / arrived".
* **Android / desktop Chrome, Edge, Firefox**: works in the browser.
* **iPhone**: Apple only allows it for apps added to the Home Screen (iOS 16.4+). The app tells
  iPhone users to tap Share → Add to Home Screen first.
* Signing out removes that phone's alerts. If a phone uninstalls or blocks alerts, the push
  service reports it and we drop that phone.
* Render's free plan sleeps when idle; a push is sent when the request that creates it arrives,
  which wakes the server, so this is fine.
