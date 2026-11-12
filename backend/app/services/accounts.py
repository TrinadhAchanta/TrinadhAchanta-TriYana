"""Email + password accounts for both apps (DoorDash-style sign-up and sign-in).

* Patients register in the Triyana app; doctors, couriers and sample collectors
  register in Triyana Partner. One email = one account = one app.
* Everything a person does (visits, prescriptions, orders, lab tests, earnings)
  hangs off their User / Patient / Doctor row, so it is there every time they sign in.
* Providers start ``pending`` and cannot go online until Triyana verifies them
  (doctors: medical council registration; couriers / collectors: ID and vehicle).
* Passwords are hashed with scrypt; sessions are random bearer tokens of which only
  a SHA-256 hash is stored, valid for 30 days and revocable.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import time

import phonenumbers
from phonenumbers import PhoneNumberType
from phonenumbers import geocoder
from collections import defaultdict, deque
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import Conflict, DomainError, Forbidden, NotFound, Unprocessable
from ..adapters import sms
from ..models import AuthSession, Doctor, Patient, PhoneOtp, Physiotherapist, Role, User, utcnow

SESSION_DAYS = 30
SESSION_PREFIX = "tys_"
# New accounts are placed in the demo service area until they share a location.
DEFAULT_POINT = (17.4440, 78.3600)
DEFAULT_JURISDICTION = "DEMO-IN"
PROVIDER_SIGNUP_ROLES = {"doctor": Role.doctor, "physio": Role.physio, "courier": Role.courier,
                         "phlebotomist": Role.phlebotomist}
PROVIDER_ROLES = (Role.doctor, Role.courier, Role.pharmacist, Role.phlebotomist, Role.physio)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class TooManyAttempts(DomainError):
    status_code = 429


# ----------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def check_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        _, n, r, p, salt, dk = stored.split("$")
        test = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                              dklen=len(base64.b64decode(dk)))
        return hmac.compare_digest(test, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


def validate_password(password: str) -> None:
    if len(password) < 8:
        raise Unprocessable("weak_password", "Use at least 8 characters for your password.")
    if password.isdigit() or password.isalpha():
        raise Unprocessable("weak_password", "Mix letters with numbers or symbols in your password.")


def normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise Unprocessable("invalid_email", "Enter a valid email address.")
    return email


# --------------------------------------------------------------- phone + OTP
OTP_MINUTES, OTP_RESEND_S, OTP_MAX_SENDS_PER_HOUR, OTP_MAX_TRIES = 10, 30, 5, 5


def _country_names() -> dict[str, str]:
    names = {}
    for region in phonenumbers.SUPPORTED_REGIONS:
        ex = phonenumbers.example_number_for_type(region, PhoneNumberType.MOBILE) or phonenumbers.example_number(region)
        name = geocoder.country_name_for_number(ex, "en") if ex else ""
        names[region] = name or region
    return names


COUNTRY_NAMES = _country_names()


def normalize_phone(phone: str, country: str | None = None) -> str:
    """Any country's mobile number to E.164, e.g. ('98480 12345', 'IN') -> '+919848012345'.

    Numbers typed with a leading + use their own country code; otherwise ``country``
    (ISO 3166 alpha-2, default India) says which country the number belongs to.
    """
    region = (country or "IN").upper()
    try:
        num = phonenumbers.parse((phone or "").strip(), region)
    except phonenumbers.NumberParseException:
        num = None
    ok_types = (PhoneNumberType.MOBILE, PhoneNumberType.FIXED_LINE_OR_MOBILE)
    if not num or not phonenumbers.is_valid_number(num) or phonenumbers.number_type(num) not in ok_types:
        where = COUNTRY_NAMES.get(region)
        where = where if where and where != region else None
        raise Unprocessable("invalid_phone", f"Enter a valid mobile number{f' for {where}' if where else ''}.")
    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)


def countries() -> list[dict]:
    """Every country we can text, with its dial code and an example mobile number."""
    out = []
    for region in sorted(phonenumbers.SUPPORTED_REGIONS):
        if region == "001":
            continue
        ex = phonenumbers.example_number_for_type(region, PhoneNumberType.MOBILE)
        out.append({"iso": region, "dial": f"+{phonenumbers.country_code_for_region(region)}",
                    "name": COUNTRY_NAMES.get(region, region),
                    "example": phonenumbers.format_number(ex, phonenumbers.PhoneNumberFormat.NATIONAL) if ex else ""})
    return sorted(out, key=lambda c: c["name"])


def _phone_taken(db: Session, phone: str, except_user: int | None = None) -> bool:
    q = select(User).where(User.phone == phone, User.phone_verified_at.isnot(None))
    if except_user:
        q = q.where(User.id != except_user)
    return db.scalars(q).first() is not None


def _code_hash(phone: str, code: str) -> str:
    return hashlib.sha256(f"{phone}:{code}:{os.environ.get('TRIYANA_SECRET', 'triyana-demo-secret-change-me')}".encode()).hexdigest()


def send_phone_otp(db: Session, phone: str, *, country: str | None = None, for_user: User | None = None) -> dict:
    phone = normalize_phone(phone, country)
    if _phone_taken(db, phone, for_user.id if for_user else None):
        raise Conflict("phone_taken", "This mobile number is already linked to another Triyana account.")
    now = utcnow()
    recent = db.scalars(select(PhoneOtp).where(PhoneOtp.phone == phone, PhoneOtp.created_at > now - timedelta(hours=1))
                        .order_by(PhoneOtp.id.desc())).all()
    if recent and (now - recent[0].created_at).total_seconds() < OTP_RESEND_S:
        wait = OTP_RESEND_S - int((now - recent[0].created_at).total_seconds())
        raise TooManyAttempts("otp_wait", f"Please wait {wait} seconds before asking for a new code.")
    if len(recent) >= OTP_MAX_SENDS_PER_HOUR:
        raise TooManyAttempts("otp_limit", "Too many codes sent to this number. Try again in an hour.")
    code = f"{secrets.randbelow(10**6):06d}"
    db.add(PhoneOtp(phone=phone, code_hash=_code_hash(phone, code), created_at=now,
                    expires_at=now + timedelta(minutes=OTP_MINUTES)))
    db.commit()
    try:
        sms.send_otp(phone, code)
    except sms.SmsError:
        raise DomainError("sms_failed", "We couldn't send the SMS. Check the number and try again.")
    cc = "+" + str(phonenumbers.parse(phone).country_code)
    out = {"phone": phone, "masked": cc + " " + "•" * (len(phone) - len(cc) - 4) + phone[-4:],
           "expires_in": OTP_MINUTES * 60, "resend_in": OTP_RESEND_S}
    if sms.is_sandbox() and os.environ.get("TRIYANA_DEMO", "1") == "1":
        out["demo_code"] = code  # no real SMS in the demo, so show the code in the app
    return out


def check_phone_otp(db: Session, phone: str, code: str) -> str:
    phone = normalize_phone(phone)
    code = re.sub(r"\D", "", code or "")
    otp = db.scalars(select(PhoneOtp).where(PhoneOtp.phone == phone, PhoneOtp.used_at.is_(None))
                     .order_by(PhoneOtp.id.desc())).first()
    if not otp or otp.expires_at < utcnow():
        raise Unprocessable("otp_expired", "That code has expired. Ask for a new one.")
    if otp.attempts >= OTP_MAX_TRIES:
        raise TooManyAttempts("otp_locked", "Too many wrong codes. Ask for a new one.")
    if not hmac.compare_digest(otp.code_hash, _code_hash(phone, code)):
        otp.attempts += 1
        db.commit()
        raise Unprocessable("otp_wrong", "That code is not right. Check the SMS and try again.")
    otp.used_at = utcnow()
    db.flush()
    return phone


def change_phone(db: Session, user: User, phone: str, code: str) -> None:
    phone = check_phone_otp(db, phone, code)
    if _phone_taken(db, phone, user.id):
        raise Conflict("phone_taken", "This mobile number is already linked to another Triyana account.")
    user.phone, user.phone_verified_at = phone, utcnow()
    db.commit()


# ------------------------------------------------------------ brute force guard
_failures: dict[str, deque] = defaultdict(deque)
MAX_FAILURES, WINDOW_S = 8, 15 * 60


def _check_rate(key: str) -> None:
    q = _failures[key]
    now = time.monotonic()
    while q and now - q[0] > WINDOW_S:
        q.popleft()
    if len(q) >= MAX_FAILURES:
        raise TooManyAttempts("too_many_attempts", "Too many wrong passwords. Try again in 15 minutes.")


def _fail(key: str) -> None:
    _failures[key].append(time.monotonic())


# ------------------------------------------------------------------ sessions
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def open_session(db: Session, user: User, app: str) -> str:
    token = SESSION_PREFIX + secrets.token_urlsafe(32)
    now = utcnow()
    db.add(AuthSession(user_id=user.id, token_hash=_hash_token(token), app=app, created_at=now, last_seen_at=now,
                       expires_at=now + timedelta(days=SESSION_DAYS)))
    db.commit()
    return token


def user_for_token(db: Session, token: str) -> User | None:
    if token.startswith(SESSION_PREFIX):
        s = db.scalars(select(AuthSession).where(AuthSession.token_hash == _hash_token(token))).first()
        if not s or s.revoked or s.expires_at < utcnow():
            return None
        now = utcnow()
        if (now - s.last_seen_at).total_seconds() > 3600:
            s.last_seen_at = now
            db.commit()
        return db.get(User, s.user_id)
    # Built-in demo accounts keep their fixed tokens so testers can switch persona.
    if token.startswith("demo-"):
        return db.scalars(select(User).where(User.token == token)).first()
    return None


def close_session(db: Session, token: str) -> None:
    s = db.scalars(select(AuthSession).where(AuthSession.token_hash == _hash_token(token))).first()
    if s:
        s.revoked = True
        db.commit()


def check_app(user: User, app: str) -> None:
    if app == "provider" and user.role not in PROVIDER_ROLES:
        raise Forbidden("wrong_app", "This email is a patient account. Patients sign in to the Triyana app.")
    if app == "patient" and user.role in PROVIDER_ROLES:
        raise Forbidden("wrong_app", "This email is a Triyana Partner account. Sign in to Triyana Partner instead.")


# ---------------------------------------------------------------- register
def _email_taken(db: Session, email: str) -> bool:
    return db.scalars(select(User).where(func.lower(User.email) == email)).first() is not None


def register(db: Session, body: dict) -> tuple[User, str]:
    app = body["app"]
    email = normalize_email(body["email"])
    validate_password(body["password"])
    name = (body.get("name") or "").strip()
    if len(name) < 2:
        raise Unprocessable("name_required", "Enter your full name.")
    if _email_taken(db, email):
        raise Conflict("email_taken", "An account with this email already exists. Sign in instead.")
    if not body.get("phone") or not body.get("otp"):
        raise Unprocessable("phone_required", "Verify your mobile number with the code we send you.")
    phone = check_phone_otp(db, body["phone"], body["otp"])
    if _phone_taken(db, phone):
        raise Conflict("phone_taken", "This mobile number is already linked to another Triyana account.")
    lat, lng = body.get("lat"), body.get("lng")
    if lat is None or lng is None:
        lat, lng = DEFAULT_POINT

    user = User(name=name, email=email, password_hash=hash_password(body["password"]),
                phone=phone, phone_verified_at=utcnow(), token="acct-" + secrets.token_hex(24),
                created_at=utcnow())
    if app == "patient":
        address = (body.get("address") or "").strip()
        if len(address) < 5:
            raise Unprocessable("address_required", "Enter your home address so doctors and riders can reach you.")
        patient = Patient(name=name, patient_ref="PT-" + secrets.token_hex(4).upper(),
                          date_of_birth=(body.get("date_of_birth") or "").strip() or "not given",
                          address=address, lat=lat, lng=lng, jurisdiction=DEFAULT_JURISDICTION,
                          gender=(body.get("gender") or None))
        db.add(patient)
        db.flush()
        user.role, user.patient_id, user.verification_status = Role.patient, patient.id, "verified"
    else:
        role = PROVIDER_SIGNUP_ROLES.get(body.get("role") or "")
        if not role:
            raise Unprocessable("role_required", "Choose whether you are a doctor, courier or sample collector.")
        user.role, user.verification_status = role, "pending"
        user.lat, user.lng = lat, lng
        user.vehicle = (body.get("vehicle") or ("Car" if role == Role.doctor else "Bike")).strip()[:40]
        if role == Role.doctor:
            d = body.get("doctor") or {}
            licence = (d.get("license_no") or "").strip().upper()
            council = (d.get("medical_council") or "").strip()
            if len(licence) < 4 or not council:
                raise Unprocessable("registration_required",
                                    "Enter your medical council and registration number so we can verify you.")
            if db.scalars(select(Doctor).where(Doctor.license_no == licence)).first():
                raise Conflict("licence_taken", "A doctor with this registration number already has an account.")
            year = d.get("registration_year")
            doctor = Doctor(name=name if name.lower().startswith("dr") else f"Dr. {name}",
                            specialty=(d.get("specialty") or "General Medicine").strip()[:80],
                            license_no=licence, license_verified=False, medical_council=council[:120],
                            qualification=(d.get("qualification") or "MBBS").strip()[:120],
                            registration_year=year, jurisdiction=DEFAULT_JURISDICTION,
                            experience_years=max(0, utcnow().year - year) if year else 0,
                            visit_fee=float(d.get("visit_fee") or 500), languages=d.get("languages") or ["English"],
                            about=(d.get("about") or "").strip()[:300], lat=lat, lng=lng,
                            area=(body.get("address") or "").strip()[:80])
            db.add(doctor)
            db.flush()
            user.doctor_id = doctor.id
            user.name = doctor.name
        elif role == Role.physio:
            d = body.get("doctor") or {}
            reg = (d.get("license_no") or "").strip().upper()
            council = (d.get("medical_council") or "").strip()
            if len(reg) < 4 or not council:
                raise Unprocessable("registration_required",
                                    "Enter your council and registration number so we can verify you.")
            if db.scalars(select(Physiotherapist).where(Physiotherapist.registration_no == reg)).first():
                raise Conflict("licence_taken", "A physiotherapist with this registration number already has an account.")
            year = d.get("registration_year")
            ph = Physiotherapist(name=name, qualification=(d.get("qualification") or "BPT").strip()[:120],
                                 registration_no=reg, council=council[:120], verified=False,
                                 jurisdiction=DEFAULT_JURISDICTION, focus=[], languages=["English"],
                                 experience_years=max(0, utcnow().year - year) if year else 0,
                                 lat=lat, lng=lng, area=(body.get("address") or "").strip()[:80])
            db.add(ph)
            db.flush()
            user.physio_id = ph.id
    db.add(user)
    db.flush()
    audit.record(db, user, "account.registered", "user", user.id, app=app, role=user.role.value)
    db.commit()
    if user.role in (Role.doctor, Role.physio):
        from . import verification
        verification.run_registry_check(db, user)
    return user, open_session(db, user, app)


def login(db: Session, email: str, password: str, app: str) -> tuple[User, str]:
    email = (email or "").strip().lower()
    _check_rate(email)
    user = db.scalars(select(User).where(func.lower(User.email) == email)).first() if email else None
    if not user or not check_password(password, user.password_hash):
        _fail(email)
        raise DomainError("bad_credentials", "That email and password don't match.")
    check_app(user, app)
    _failures.pop(email, None)
    return user, open_session(db, user, app)


def change_password(db: Session, user: User, current: str, new: str) -> None:
    if not check_password(current, user.password_hash):
        raise DomainError("bad_credentials", "Your current password is not right.")
    validate_password(new)
    user.password_hash = hash_password(new)
    db.commit()


# ------------------------------------------------------------- verification
def account_dict(db: Session, user: User) -> dict:
    out = {"id": user.id, "name": user.name, "email": user.email, "phone": user.phone,
           "phone_verified": user.phone_verified_at is not None, "role": user.role.value,
           "demo": user.email is None, "verification_status": user.verification_status or "verified",
           "verification_note": user.verification_note,
           "member_since": user.created_at.date().isoformat() if user.created_at else None}
    if user.patient_id:
        p = db.get(Patient, user.patient_id)
        out["patient"] = {"address": p.address, "date_of_birth": p.date_of_birth, "patient_ref": p.patient_ref,
                          "gender": p.gender,
                          "lat": p.lat, "lng": p.lng}
    if user.doctor_id:
        d = db.get(Doctor, user.doctor_id)
        out["doctor"] = {"specialty": d.specialty, "license_no": d.license_no, "medical_council": d.medical_council,
                         "qualification": d.qualification, "registration_year": d.registration_year,
                         "license_verified": d.license_verified, "visit_fee": d.visit_fee}
    if user.physio_id:
        ph = db.get(Physiotherapist, user.physio_id)
        out["physio"] = {"qualification": ph.qualification, "license_no": ph.registration_no,
                         "medical_council": ph.council, "verified": ph.verified}
    return out


def set_verification(db: Session, user_id: int, status: str, note: str = "", actor: User | None = None,
                     *, override: bool = False, require_checks: bool = False) -> User:
    if status not in ("verified", "rejected", "pending"):
        raise Unprocessable("bad_status", "Status must be verified, rejected or pending.")
    user = db.get(User, user_id)
    if not user or user.role not in PROVIDER_ROLES:
        raise NotFound("not_found", "Provider not found.")
    if status == "verified" and require_checks:
        from . import verification
        if not verification.all_passed(db, user):
            if not override:
                raise Conflict("checks_incomplete", "Some checks have not passed. Approve with an override "
                                                    "and a note if you have verified this provider by hand.")
            if len((note or "").strip()) < 5:
                raise Unprocessable("note_required", "Add a note saying how you verified this provider.")
            note = "Override: " + note.strip()
    user.verification_status, user.verification_note = status, (note or None)
    if user.doctor_id:
        db.get(Doctor, user.doctor_id).license_verified = status == "verified"
    if user.physio_id:
        db.get(Physiotherapist, user.physio_id).verified = status == "verified"
    if status != "verified":
        user.on_duty = False
    audit.record(db, actor, f"provider.verification.{status}", "user", user.id, note=note)
    db.commit()
    return user


def pending_providers(db: Session, status: str = "pending") -> list[dict]:
    from . import verification
    rows = db.scalars(select(User).where(User.verification_status == status).order_by(User.id)).all()
    out = []
    for u in rows:
        verification.refresh(db, u)
        out.append(account_dict(db, u) | {"verification": verification.status(db, u)})
    return out


def registered_accounts_exist(db: Session) -> bool:
    return db.scalars(select(User.id).where(User.email.isnot(None)).limit(1)).first() is not None
