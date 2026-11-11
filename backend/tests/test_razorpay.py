"""Razorpay (test mode) against a fake Razorpay API: authorise -> capture / partial refund / reuse protection."""
import hashlib
import hmac

import pytest

from app.adapters.razorpay import RazorpayGateway


class FakeRazorpay:
    def __init__(self):
        self.orders, self.payments, self.calls = {}, {}, []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "POST" and path == "/orders":
            oid = f"order_{len(self.orders) + 1:04d}"
            self.orders[oid] = body
            return {"id": oid, "amount": body["amount"], "currency": "INR"}
        if method == "GET" and path.startswith("/payments/"):
            return self.payments[path.split("/")[2]]
        if path.endswith("/capture"):
            self.payments[path.split("/")[2]]["status"] = "captured"
            return {}
        if path.endswith("/refund"):
            return {"id": f"rfnd_{len(self.calls)}"}
        raise AssertionError(path)

    def pay(self, order_id, payment_id="pay_0001"):
        """Simulate the patient paying in Razorpay Checkout (UPI)."""
        self.payments[payment_id] = {"id": payment_id, "order_id": order_id, "status": "authorized",
                                     "amount": self.orders[order_id]["amount"], "method": "upi"}
        sig = hmac.new(b"test_secret", f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
        return f"rzp:{order_id}:{payment_id}:{sig}"


@pytest.fixture()
def rzp(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_demo")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "test_secret")
    fake = FakeRazorpay()
    monkeypatch.setattr(RazorpayGateway, "http", staticmethod(fake))
    return fake


def _intent_and_pay(patient, rzp, cart_id, gl, pid="pay_0001"):
    intent = patient.post(f"/api/carts/{cart_id}/payment-intent",
                          {"pharmacy_id": gl, "fulfillment": "delivery", "delivery_option": "standard"}).json()
    assert intent["gateway"] == "razorpay" and intent["test_mode"] and intent["key_id"] == "rzp_test_demo"
    assert rzp.orders[intent["order_id"]]["payment_capture"] == 0  # manual capture = hold only
    return intent, rzp.pay(intent["order_id"], pid)


def _checkout(patient, cart_id, gl, token, key, total):
    return patient.post(f"/api/carts/{cart_id}/checkout", {
        "pharmacy_id": gl, "fulfillment": "delivery", "delivery_option": "standard", "payment_method": "upi",
        "payment_token": token, "idempotency_key": key, "expected_total": total})


def test_razorpay_authorise_then_capture_with_partial_refund(env, as_, signed_rx, rzp):
    patient, pharmacist = as_("patient"), as_("pharmacist")
    gl = env["ids"]["pharmacies"]["greenleaf"]
    assert patient.get("/api/payment-config").json()["gateway"] == "razorpay"
    intent, token = _intent_and_pay(patient, rzp, signed_rx["cart_id"], gl)
    r = _checkout(patient, signed_rx["cart_id"], gl, token, "rzp-0001", intent["amount"])
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["payment"]["status"] == "authorized" and o["payment"]["authorized"] == intent["amount"]
    dolo = next(i for i in o["items"] if i["medicine"] == "Dolo 650 mg")
    r = pharmacist.post(f"/api/pharmacy/orders/{o['id']}/review",
                        {"decision": "adjust", "notes": "Only 4 available", "adjustments": {dolo["id"]: 4}}).json()
    captured = r["payment"]["captured"]
    assert captured < intent["amount"]
    capture = next(c for c in rzp.calls if c[1].endswith("/capture"))
    refund = next(c for c in rzp.calls if c[1].endswith("/refund"))
    assert capture[2]["amount"] == intent["amount_paise"]
    assert refund[2]["amount"] == intent["amount_paise"] - round(captured * 100)


def test_razorpay_rejects_bad_signature_wrong_amount_and_reuse(env, as_, signed_rx, rzp):
    patient = as_("patient")
    gl = env["ids"]["pharmacies"]["greenleaf"]
    intent, token = _intent_and_pay(patient, rzp, signed_rx["cart_id"], gl)
    forged = token.rsplit(":", 1)[0] + ":" + "0" * 64
    r = _checkout(patient, signed_rx["cart_id"], gl, forged, "rzp-bad-01", intent["amount"])
    assert r.status_code == 402 and "verify" in r.json()["detail"]["message"]
    rzp.payments["pay_0001"]["amount"] -= 100  # paid less than the order total
    assert _checkout(patient, signed_rx["cart_id"], gl, token, "rzp-bad-02", intent["amount"]).status_code == 402
    rzp.payments["pay_0001"]["amount"] += 100
    ok = _checkout(patient, signed_rx["cart_id"], gl, token, "rzp-ok-001", intent["amount"])
    assert ok.status_code == 201
    # Cancel puts items back; the same payment can't be used again for a new order.
    patient.post(f"/api/orders/{ok.json()['id']}/cancel", {"reason": "test"})
    r = _checkout(patient, signed_rx["cart_id"], gl, token, "rzp-reuse1", intent["amount"])
    assert r.status_code == 402 and r.json()["detail"]["code"] == "payment_reused"


def test_sandbox_when_no_keys(env, as_, signed_rx, monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    patient = as_("patient")
    assert patient.get("/api/payment-config").json()["gateway"] == "sandbox-payments"
    r = patient.post(f"/api/carts/{signed_rx['cart_id']}/payment-intent",
                     {"pharmacy_id": env["ids"]["pharmacies"]["greenleaf"], "fulfillment": "delivery",
                      "delivery_option": "standard"}).json()
    assert r["gateway"] == "sandbox"
    assert [m["code"] for m in patient.get("/api/payment-methods").json()] == ["upi", "card", "netbanking", "wallet"]
