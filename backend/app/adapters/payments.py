"""Sandbox payment gateway.

Authorise-then-capture: money is only *held* at checkout and captured after
the pharmacist accepts the order (for the approved amount). Holds are voided
on rejection; captured payments are refunded on cancellation.

Demo test tokens: any token containing "decline" fails authorisation.
No real card data is ever handled; real integrations must use the PSP's
tokenisation (e.g. Apple Pay / Google Pay tokens, UPI intents, PayPal orders).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

SUPPORTED_METHODS = {
    "apple_pay": "Apple Pay",
    "google_pay": "Google Pay",
    "card": "Credit / debit card",
    "upi": "UPI",
    "paypal": "PayPal",
    "regional_wallet": "Regional wallet",
}


@dataclass
class GatewayResult:
    ok: bool
    ref: str
    message: str = ""


class SandboxPaymentGateway:
    name = "sandbox-payments"

    def authorize(self, method: str, amount: float, token: str) -> GatewayResult:
        if method not in SUPPORTED_METHODS:
            return GatewayResult(False, "", "Unsupported payment method.")
        if "decline" in (token or "").lower():
            return GatewayResult(False, "", "The payment was declined by your bank (sandbox).")
        return GatewayResult(True, f"auth_{uuid.uuid4().hex[:16]}")

    def capture(self, ref: str, amount: float) -> GatewayResult:
        return GatewayResult(True, ref)

    def void(self, ref: str) -> GatewayResult:
        return GatewayResult(True, ref)

    def refund(self, ref: str, amount: float) -> GatewayResult:
        return GatewayResult(True, f"rfnd_{uuid.uuid4().hex[:16]}")
