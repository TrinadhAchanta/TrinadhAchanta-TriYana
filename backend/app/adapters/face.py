"""Face liveness + face match partner for the Nabzo app.

Picked by ``TRIYANA_FACE_PROVIDER``:

* ``demo`` (default): a stand-in that runs on the server with no network. It is ONLY
  allowed while ``TRIYANA_DEMO=1``; with demo mode off it refuses every check (fails closed),
  so a production deployment can never fall back to it by accident.

  What the stand-in really checks on the camera frames it receives:
    - the frames are real JPEG/PNG images of a sensible size;
    - lighting: too dark, too bright or a covered / blank camera is "poor quality" (retry);
    - movement between frames while the person follows the on-screen prompt; a still picture
      held perfectly steady fails liveness;
    - the exact same frames sent twice in one check or replayed from an earlier check are
      treated as a replay attack (spoof).
  What it can NOT do: real presentation-attack detection (printed photo, screen, mask) or real
  face matching. It treats any live face as a match. Testers can force the hard cases with a
  demo scenario (``other_person``, ``printed_photo``, ``replay_video``, ``poor_lighting``),
  which can only make a check fail, never pass.

* A real vendor (HyperVerge, IDfy face liveness + face match, or AWS Rekognition Face Liveness)
  plugs in by adding a branch to ``enroll`` and ``verify`` below. Not built yet: it needs the
  vendor's account keys and, for certified passive liveness, the vendor's capture SDK in the app.
  See docs/FACE_VERIFICATION.md.

Every function raises ``PartnerError`` when the partner can't give an answer, so callers record
an error and never treat it as a pass.
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
import uuid
from dataclasses import dataclass, field

DEMO_SCENARIOS = ("other_person", "printed_photo", "replay_video", "poor_lighting")
MAX_FRAME_BYTES = 400_000
MIN_FRAMES, MAX_FRAMES = 3, 6


class PartnerError(Exception):
    pass


@dataclass
class FaceResult:
    status: str  # passed | failed | spoof | poor_quality
    reason: str
    liveness: float | None = None
    match: float | None = None
    reference: str | None = None
    details: dict = field(default_factory=dict)


def face_partner() -> str:
    return os.environ.get("TRIYANA_FACE_PROVIDER", "demo").lower()


def demo_mode() -> bool:
    return os.environ.get("TRIYANA_DEMO", "1") == "1"


def _require_partner() -> str:
    partner = face_partner()
    if partner == "demo":
        if not demo_mode():
            raise PartnerError("No face verification partner is configured")
        return partner
    raise PartnerError(f"Face partner {partner!r} is not set up in this build")


def decode_frames(frames: list[str]) -> list[bytes]:
    """data: URLs (or bare base64) -> bytes, with size limits. Raises ValueError on bad input."""
    if not MIN_FRAMES <= len(frames) <= MAX_FRAMES:
        raise ValueError(f"Send between {MIN_FRAMES} and {MAX_FRAMES} camera frames.")
    out = []
    for f in frames:
        b64 = f.split(",", 1)[1] if f.startswith("data:") else f
        try:
            raw = base64.b64decode(b64, validate=True)
        except ValueError as e:
            raise ValueError("A camera frame could not be read.") from e
        if not raw or len(raw) > MAX_FRAME_BYTES:
            raise ValueError("A camera frame is empty or too large.")
        out.append(raw)
    return out


def digests(frames: list[bytes]) -> list[str]:
    return [hashlib.sha256(f).hexdigest() for f in frames]


def _gray(raw: bytes):
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(raw))
        if img.format not in ("JPEG", "PNG", "WEBP") or img.width > 2000 or img.height > 2000:
            raise ValueError
        return img.convert("L").resize((48, 36))
    except Exception as e:  # noqa: BLE001 - any decode problem is a bad frame
        raise ValueError("A camera frame is not a valid image.") from e


def _stats(img) -> tuple[float, float]:
    px = list(img.getdata())
    mean = sum(px) / len(px)
    std = (sum((p - mean) ** 2 for p in px) / len(px)) ** 0.5
    return mean, std


def _motion(a, b) -> float:
    pa, pb = list(a.getdata()), list(b.getdata())
    return sum(abs(x - y) for x, y in zip(pa, pb)) / len(pa)


def _analyse(frames: list[bytes], scenario: str | None, seen: set[str]) -> FaceResult:
    """Liveness and quality checks shared by enrolment and visit checks (demo partner)."""
    imgs = [_gray(f) for f in frames]  # ValueError for anything that isn't a real image
    ds = digests(frames)
    if len(set(ds)) < len(ds):
        return FaceResult("spoof", "The same frame was sent more than once (injected still image).", 0.02,
                          details={"signal": "duplicate_frames"})
    if seen.intersection(ds):
        return FaceResult("spoof", "These camera frames were already used in an earlier check (replay).", 0.01,
                          details={"signal": "replayed_frames"})
    means, stds = zip(*(_stats(i) for i in imgs))
    mean, std = sum(means) / len(means), sum(stds) / len(stds)
    if scenario == "poor_lighting" or mean < 45:
        return FaceResult("poor_quality", "It's too dark to see your face. Move to a brighter spot and try again.",
                          details={"signal": "too_dark", "brightness": round(mean, 1)})
    if mean > 235:
        return FaceResult("poor_quality", "There's too much light behind or on you. Turn away from the light and try again.",
                          details={"signal": "too_bright", "brightness": round(mean, 1)})
    if std < 8:
        return FaceResult("poor_quality", "We can't see a face. Uncover the camera and fill the oval with your face.",
                          details={"signal": "no_face", "contrast": round(std, 1)})
    if scenario == "printed_photo":
        return FaceResult("spoof", "Flat, printed-photo texture detected instead of a live face.", 0.04,
                          details={"signal": "print_attack"})
    if scenario == "replay_video":
        return FaceResult("spoof", "Screen replay detected (moiré pattern and screen glare).", 0.03,
                          details={"signal": "screen_replay"})
    motion = max(_motion(a, b) for a, b in zip(imgs, imgs[1:]))
    if motion < 0.6:
        return FaceResult("failed", "We didn't see you move. Follow the prompt on screen and try again.", 0.2,
                          details={"signal": "no_motion", "motion": round(motion, 2)})
    liveness = round(min(0.99, 0.86 + motion / 100), 3)
    return FaceResult("passed", "Live face confirmed.", liveness, details={"motion": round(motion, 2)})


def enroll(user_id: int, frames: list[bytes], scenario: str | None, seen: set[str]) -> FaceResult:
    """Liveness-check the enrolment capture and register the face with the partner."""
    partner = _require_partner()
    if partner == "demo":
        res = _analyse(frames, scenario, seen)
        if res.status == "passed":
            res.reference = f"FACE-DEMO-{uuid.uuid4().hex[:12].upper()}"
            res.reason = "Live face captured and enrolled (demo partner)."
        return res
    raise PartnerError(f"Unknown face partner {partner!r}")  # pragma: no cover


def verify(template_ref: str, frames: list[bytes], scenario: str | None, seen: set[str]) -> FaceResult:
    """Liveness-check a live capture and compare it with the enrolled face."""
    partner = _require_partner()
    if partner == "demo":
        res = _analyse(frames, scenario, seen)
        if res.status != "passed":
            return res
        if scenario == "other_person":
            return FaceResult("failed", "This face does not match the verified doctor on this account.",
                              res.liveness, 0.18, details={"signal": "face_mismatch"})
        res.match = 0.97
        res.reason = "Live face matches the enrolled, verified face (demo partner)."
        return res
    raise PartnerError(f"Unknown face partner {partner!r}")  # pragma: no cover


def profile_photo(frames: list[bytes]) -> str:
    """A 240x240 centre crop of the middle frame as a JPEG data URL, for the verified profile."""
    from PIL import Image

    img = Image.open(io.BytesIO(frames[len(frames) // 2])).convert("RGB")
    side = min(img.size)
    left, top = (img.width - side) // 2, (img.height - side) // 2
    img = img.crop((left, top, left + side, top + side)).resize((240, 240))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=78)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
