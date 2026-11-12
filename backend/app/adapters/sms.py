"""SMS gateway for one-time passwords.

TRIYANA_SMS_PROVIDER picks the gateway:

* ``sandbox`` (default): nothing is sent. The code is logged and, in demo mode
  (TRIYANA_DEMO=1), returned to the app so testers can see it on screen.
* ``msg91``: MSG91 OTP API (India, DLT-registered template). Needs MSG91_AUTH_KEY
  and MSG91_TEMPLATE_ID.
* ``twilio``: Twilio Programmable Messaging. Needs TWILIO_ACCOUNT_SID,
  TWILIO_AUTH_TOKEN and TWILIO_FROM.
"""
from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger("triyana.sms")


class SmsError(Exception):
    pass


def provider_name() -> str:
    return os.environ.get("TRIYANA_SMS_PROVIDER", "sandbox").lower()


def is_sandbox() -> bool:
    return provider_name() == "sandbox"


def send_otp(phone: str, code: str) -> None:
    text = f"{code} is your Triyana verification code. It expires in 10 minutes. Do not share it with anyone."
    name = provider_name()
    if name == "sandbox":
        log.warning("SANDBOX SMS to %s: %s", phone[:-4] + "****", text)
        return
    try:
        if name == "msg91":
            r = httpx.post("https://control.msg91.com/api/v5/otp", timeout=10,
                           headers={"authkey": os.environ["MSG91_AUTH_KEY"]},
                           json={"template_id": os.environ["MSG91_TEMPLATE_ID"], "mobile": phone.lstrip("+"),
                                 "otp": code})
        elif name == "twilio":
            sid = os.environ["TWILIO_ACCOUNT_SID"]
            r = httpx.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", timeout=10,
                           auth=(sid, os.environ["TWILIO_AUTH_TOKEN"]),
                           data={"To": phone, "From": os.environ["TWILIO_FROM"], "Body": text})
        else:
            raise SmsError(f"Unknown SMS provider {name!r}")
        r.raise_for_status()
    except (KeyError, httpx.HTTPError) as e:
        log.error("SMS send failed via %s: %s", name, e)
        raise SmsError("Could not send the SMS") from e
