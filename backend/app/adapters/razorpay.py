"""Razorpay gateway (India): UPI, cards, netbanking and wallets.

Used when RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are set (test keys start with
"rzp_test_"). Flow, matching Triyana's authorise-then-capture rule:

1. Server creates a Razorpay order with payment_capture=0 (manual capture).
2. The browser opens Razorpay Checkout; the patient pays by UPI or card.
3. Server verifies the checkout signature and that the payment is "authorized"
   for exactly the order total, then places the Triyana order.
4. Pharmacist approves -> capture. Razorpay captures the full authorised amount,
   so a lower approved amount is captured and the difference refunded at once.
5. Pharmacist rejects -> the uncaptured payment is left to Razorpay's automatic
   refund of uncaptured payments (no API "void" exists).
Card numbers and UPI PINs never touch Triyana's servers.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request

from .payments import GatewayResult

API = "https://api.razorpay.com/v1"


def configured() -> bool:
    return bool(os.environ.get("RAZORPAY_KEY_ID") and os.environ.get("RAZORPAY_KEY_SECRET"))


def _http(method: str, path: str, body: dict | None = None) -> dict:
    key, secret = os.environ["RAZORPAY_KEY_ID"], os.environ["RAZORPAY_KEY_SECRET"]
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{key}:{secret}".encode()).decode())
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("error", {}).get("description", "")
        except Exception:  # noqa: BLE001
            detail = ""
        raise RazorpayError(detail or f"Razorpay error {e.code}") from e
    except urllib.error.URLError as e:
        raise RazorpayError("Couldn't reach Razorpay. Please try again.") from e


class RazorpayError(Exception):
    pass


def paise(amount: float) -> int:
    return int(round(amount * 100))


class RazorpayGateway:
    name = "razorpay"
    http = staticmethod(_http)  # replaced in tests

    @property
    def key_id(self) -> str:
        return os.environ.get("RAZORPAY_KEY_ID", "")

    @property
    def test_mode(self) -> bool:
        return self.key_id.startswith("rzp_test_")

    def create_order(self, amount: float, receipt: str, notes: dict) -> dict:
        return self.http("POST", "/orders", {"amount": paise(amount), "currency": "INR", "receipt": receipt[:40],
                                             "payment_capture": 0, "notes": notes})

    @staticmethod
    def signature_ok(order_id: str, payment_id: str, signature: str) -> bool:
        secret = os.environ.get("RAZORPAY_KEY_SECRET", "").encode()
        expected = hmac.new(secret, f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature or "")

    def authorize(self, method: str, amount: float, token: str) -> GatewayResult:
        """token = 'rzp:<order_id>:<payment_id>:<signature>' from the Checkout success handler."""
        parts = (token or "").split(":")
        if len(parts) != 4 or parts[0] != "rzp":
            return GatewayResult(False, "", "Please complete the payment in the Razorpay window.")
        _, order_id, payment_id, signature = parts
        if not self.signature_ok(order_id, payment_id, signature):
            return GatewayResult(False, "", "We couldn't verify this payment. You have not been charged.")
        try:
            pay = self.http("GET", f"/payments/{payment_id}")
        except RazorpayError as e:
            return GatewayResult(False, "", str(e))
        if pay.get("order_id") != order_id or pay.get("status") != "authorized":
            return GatewayResult(False, "", "The payment wasn't authorised. You have not been charged.")
        if int(pay.get("amount", -1)) != paise(amount):
            return GatewayResult(False, "", "The payment amount doesn't match your order. Please try again.")
        return GatewayResult(True, payment_id)

    def capture(self, ref: str, amount: float) -> GatewayResult:
        pay = self.http("GET", f"/payments/{ref}")
        authorized = int(pay["amount"])
        self.http("POST", f"/payments/{ref}/capture", {"amount": authorized, "currency": "INR"})
        extra = authorized - paise(amount)
        if extra > 0:  # pharmacist approved less: return the difference straight away
            self.http("POST", f"/payments/{ref}/refund", {"amount": extra, "notes": {"reason": "pharmacist adjusted order"}})
        return GatewayResult(True, ref)

    def void(self, ref: str) -> GatewayResult:
        # Razorpay has no void: uncaptured payments are refunded automatically by Razorpay.
        return GatewayResult(True, ref, "Released: Razorpay refunds uncaptured payments automatically.")

    def refund(self, ref: str, amount: float) -> GatewayResult:
        res = self.http("POST", f"/payments/{ref}/refund", {"amount": paise(amount)})
        return GatewayResult(True, res.get("id", ""))
