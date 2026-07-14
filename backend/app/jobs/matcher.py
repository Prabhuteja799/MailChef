import re

_SUFFIXES = re.compile(
    r"\b(inc|incorporated|llc|corp|corporation|co|ltd|limited|company|"
    r"technologies|technology|tech|group|holdings|plc)\.?\b",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^a-z0-9\s]")
_WHITESPACE = re.compile(r"\s+")


def company_key(company_name: str) -> str:
    """Best-effort normalization for matching the same company across
    differently-worded sender names (e.g. "Citi Scaled Technical Hiring
    NAM" vs "Citi"). Not exact entity resolution — relies mostly on the
    extraction prompt asking for the parent brand name in the first place;
    this just smooths over casing/suffix/punctuation differences.
    """
    key = company_name.lower().strip()
    key = _SUFFIXES.sub("", key)
    key = _NON_ALNUM.sub("", key)
    key = _WHITESPACE.sub(" ", key).strip()
    return key
