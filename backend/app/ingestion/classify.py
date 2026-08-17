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


def classify(content: str) -> str:
    text = (content or "").lower()
    if _PAN_RE.search(content or "") or _AADHAAR_RE.search(content or "") or _ACCOUNT_RE.search(content or ""):
        return "high"
    if _has_keyword(text, _ID_KEYWORDS) or _has_keyword(text, _FINANCIAL_KEYWORDS):
        return "high"
    if _has_keyword(text, _MODERATE_KEYWORDS):
        return "moderate"
    return "none"