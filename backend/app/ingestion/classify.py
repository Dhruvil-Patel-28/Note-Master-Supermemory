import re

_PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
_AADHAAR_RE = re.compile(r"\b[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}\b")
_ACCOUNT_RE = re.compile(r"\b(?:account|a/c|acc)[^\d]{0,20}\d{9,18}\b")
_ID_KEYWORDS = [
    "pan",
    "pan card",
    "aadhaar",
    "aadhar",
    "aadhaar number",
    "passport",
    "driving licence",
    "driving license",
    "voter id",
    "it returns",
    "income tax return",
]
_FINANCIAL_KEYWORDS = [
    "bank statement",
    "statement",
    "salary slip",
    "payslip",
    "invoice",
    "receipt",
    "bill",
    "emi",
    "loan",
    "credit card",
    "cibil",
    "sip",
    "mutual fund",
    "tax",
    "net worth",
]
_MODERATE_KEYWORDS = [
    "meeting",
    "birthday",
    "doctor",
    "prescription",
    "address",
    "phone number",
    "mobile number",
]


def _has_keyword(text: str, keywords: list[str]) -> bool:
    return any(re.search(rf"\b{re.escape(k)}\b", text) for k in keywords)


def classify(content: str, filename: str = "", note: str = "") -> str:
    """Sensitivity tier from content PLUS user-facing labels (filename/note).

    Labels are matched too because OCR text is unreliable: a passport photo
    page rarely contains the literal word "passport", but its filename
    ("Dhruvil PASSPORT_2.jpg") or note ("passport") does. Rules stay pure and
    word-bounded either way."""
    text = (content or "").lower()
    labels = f"{filename or ''} {note or ''}".strip()
    haystack = f"{content or ''} {labels}"
    # Keywords match against a word space (non-alphanumerics → spaces) so
    # filenames like "passport_2.jpg" or "Aadhaar-2026.png" keep word
    # boundaries intact; the regexes above still run on the raw haystack.
    words_space = re.sub(r"[^a-z0-9]+", " ", f"{text} {labels.lower()}")
    if _PAN_RE.search(haystack) or _AADHAAR_RE.search(haystack) or _ACCOUNT_RE.search(haystack):
        return "high"
    if _has_keyword(words_space, _ID_KEYWORDS) or _has_keyword(words_space, _FINANCIAL_KEYWORDS):
        return "high"
    if _has_keyword(words_space, _MODERATE_KEYWORDS):
        return "moderate"
    return "none"