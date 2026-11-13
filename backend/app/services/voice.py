"""Voice booking: turn what an elderly patient says ("bukhar hai, abhi doctor chahiye") into a booking request.

The browser does the speech-to-text (Web Speech API, in en-IN, hi-IN, te-IN or ta-IN). This module only finds
the reason, the time and any emergency words, in English, Hindi, Telugu or Tamil, written in their own script or
in Latin letters. The patient always confirms before anything is booked.
"""
from __future__ import annotations

import re

LANGS = ("en", "hi", "te", "ta")

# Each reason: the English label used for the booking, then words that point to it.
REASONS = [
    ("Fever or cold", ["fever", "temperature", "bukhar", "bukhaar", "बुखार", "ताप", "jwaram", "జ్వరం",
                       "kaichal", "காய்ச்சல்", "cold", "cough", "khansi", "खांसी", "खाँसी", "सर्दी", "जुकाम",
                       "దగ్గు", "జలుబు", "இருமல்", "சளி"]),
    ("Blood pressure check", ["bp", "blood pressure", "pressure", "ब्लड प्रेशर", "रक्तचाप", "बीपी", "బీపీ",
                              "రక్తపోటు", "பிபி", "ரத்த அழுத்தம்", "இரத்த அழுத்தம்"]),
    ("Sugar (diabetes) check", ["sugar", "diabetes", "शुगर", "मधुमेह", "डायबिटीज", "షుగర్", "చక్కెర", "మధుమేహం",
                                "சர்க்கரை", "சுகர்", "நீரிழிவு"]),
    ("Stomach upset", ["stomach", "vomit", "vomiting", "loose motion", "diarrhoea", "diarrhea", "ulti", "उल्टी",
                       "पेट", "दस्त", "వాంతి", "వాంతులు", "కడుపు", "విరోచనాలు", "வாந்தி", "வயிறு", "பேதி"]),
    ("Joint or back pain", ["pain", "knee", "joint", "dard", "दर्द", "कमर", "घुटना", "घुटने", "noppi",
                            "నొప్పి", "నడుము", "మోకాలు", "vali", "வலி", "முதுகு", "முழங்கால்"]),
    ("General check-up", ["checkup", "check-up", "check up", "जांच", "जाँच", "चेकअप", "పరీక్ష", "చెకప్",
                          "பரிசோதனை", "செக்கப்"]),
]

EMERGENCY = ["chest pain", "heart attack", "can't breathe", "cannot breathe", "breathing", "unconscious", "fainted",
             "stroke", "seizure", "bleeding", "सीने में दर्द", "छाती में दर्द", "सांस", "साँस", "बेहोश", "दौरा",
             "saans", "behosh", "ఛాతీ నొప్పి", "ఊపిరి", "స్పృహ", "మూర్ఛ", "நெஞ்சு வலி", "மூச்சு",
             "மயக்கம்", "வலிப்பு", "ரத்தம்"]

NOW = ["now", "urgent", "immediately", "right away", "asap", "quick", "abhi", "turant", "jaldi", "अभी", "तुरंत",
       "जल्दी", "ippude", "ventane", "ఇప్పుడే", "ఇప్పుడు", "వెంటనే", "త్వరగా", "ippove", "udane", "இப்போதே",
       "இப்போது", "உடனே", "அவசரம்"]
DAYS = {
    "today": ["today", "aaj", "आज", "ఈరోజు", "ఈ రోజు", "eeroju", "இன்று", "indru"],
    "tomorrow": ["tomorrow", "kal", "कल", "repu", "రేపు", "naalai", "நாளை"],
}
PARTS = {
    "morning": ["morning", "subah", "सुबह", "ఉదయం", "udayam", "காலை", "kaalai"],
    "afternoon": ["afternoon", "dopahar", "दोपहर", "మధ్యాహ్నం", "madhyahnam", "மதியம்", "mathiyam"],
    "evening": ["evening", "shaam", "शाम", "సాయంత్రం", "sayantram", "மாலை", "maalai"],
}


def _has(text: str, words: list[str]) -> bool:
    for w in words:
        if w.isascii():
            if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", text):
                return True
        elif w in text:  # Indic scripts: words join with suffixes, so match inside the word
            return True
    return False


def understand(text: str, lang: str = "en") -> dict:
    t = " ".join(text.lower().split())
    reasons = [label for label, words in REASONS if _has(t, words)]
    day = next((d for d, w in DAYS.items() if _has(t, w)), None)
    part = next((p for p, w in PARTS.items() if _has(t, w)), None)
    emergency = _has(t, EMERGENCY)
    # A named day or time of day means "book for then"; otherwise an elderly caller wants a doctor now.
    action = "book" if (day or part) and not _has(t, NOW) else "now"
    if action == "book" and day is None:
        day = "today"
    reason = reasons[0] if reasons else "General check-up"
    if emergency:  # never file chest pain under "joint pain": send their own words with it
        action, reason = "now", f"Urgent: {text.strip()[:120]}"
    return {"text": text.strip(), "lang": lang if lang in LANGS else "en", "action": action,
            "reason": reason, "reasons": reasons,
            "day": day if action == "book" else None, "part": part if action == "book" else None,
            "emergency": emergency, "understood": bool(reasons or day or part or _has(t, NOW))}
