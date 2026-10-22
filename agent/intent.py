from __future__ import annotations

import re

FORMAT_LABELS = {"docx": "Word", "pdf": "PDF", "xlsx": "Excel"}

_FORMAT_PATTERNS = (
    ("docx", re.compile(r"\b(docx?|(ms|microsoft) word|word (doc|docs|document|file|format|version)|(as|to|in|into) (a )?word)\b")),
    ("pdf", re.compile(r"\bpdfs?\b")),
    ("xlsx", re.compile(r"\b(xlsx|xls|excel|spreadsheet)\b")),
)
_BARE_FORMATS = {
    "word": ["docx"],
    "docx": ["docx"],
    "doc": ["docx"],
    "pdf": ["pdf"],
    "excel": ["xlsx"],
    "xlsx": ["xlsx"],
    "both": ["docx", "pdf"],
    "all": ["docx", "pdf", "xlsx"],
    "all three": ["docx", "pdf", "xlsx"],
}
_EXPORT_WORDS = re.compile(
    r"\b(export|download|save (it|this|that|them|the \w+)? ?(as|to|in|into)"
    r"|convert (it|this|that|them)? ?(to|into)"
    r"|(turn|put) (it|this|that) (into|in) (a |an )?(pdf|docx?|word|excel|xlsx|file)"
    r"|(give|send|make|get) me (a|an|the) (pdf|docx?|word|excel|xlsx)"
    r"|as (a |an )?(pdf|docx|xlsx)( file)?)\b"
)
_COMMAND_START = re.compile(
    r"^(export|download|save|convert|turn (it|this|that) into|put (it|this|that) in"
    r"|(give|send|make|get) me (a|an|the) (pdf|docx?|word|excel|xlsx)|as (a |an )?(pdf|docx?|word|excel|xlsx))\b"
)
_LEADING_FILLER = re.compile(
    r"^((please|pls|ok|okay|now|and|then|also|great|thanks|thank you|cool|nice|perfect)[,!.]?\s+"
    r"|(can|could|would|will) you (please )?|i (want|need|would like) (you )?to |let'?s )+"
)
_AFFIRMATIVE = re.compile(r"^(yes|yeah|yep|yup|sure|ok|okay|do it|go ahead|please do|please|y)\b")
_NEGATIVE = re.compile(r"^(no|nope|nah|don'?t|do not|cancel|stop|never ?mind)\b")
_SMALL_TALK = {
    "hi",
    "hello",
    "hey",
    "thanks",
    "thank you",
    "thx",
    "ok",
    "okay",
    "cool",
    "great",
    "nice",
    "bye",
    "good morning",
    "good night",
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def export_formats(text: str) -> list[str]:
    lowered = normalize(text).strip(" .!?")
    if lowered in _BARE_FORMATS:
        return list(_BARE_FORMATS[lowered])
    found = [name for name, pattern in _FORMAT_PATTERNS if pattern.search(lowered)]
    if re.search(r"\bboth\b", lowered) and not found:
        return ["docx", "pdf"]
    return found


def mentions_export(text: str) -> bool:
    return bool(_EXPORT_WORDS.search(normalize(text)))


def is_export_command(text: str) -> bool:
    lowered = _LEADING_FILLER.sub("", normalize(text)).strip(" .!?")
    if not lowered or len(lowered.split()) > 14:
        return False
    return bool(_COMMAND_START.match(lowered)) and mentions_export(lowered)


def export_requested(text: str) -> bool:
    """True when some clause of the message is a direct export command, e.g. "...and export it as pdf"."""
    clauses = re.split(r"[.!?,;\n]+|\b(?:and|then|also)\b", normalize(text))
    return any(is_export_command(clause) for clause in clauses if clause and clause.strip())


_GENERIC_WORDS = {
    "a", "an", "the", "me", "my", "for", "please", "pls", "can", "could", "you", "help", "i", "need", "want",
    "to", "write", "draft", "make", "create", "do", "give", "generate", "prepare", "build", "start", "new",
    "short", "long", "full", "quick", "simple", "good", "nice", "one", "some", "essay", "paper", "outline",
    "report", "care", "plan", "concept", "map", "teaching", "sbar", "reflection", "post", "discussion", "email",
    "mail", "letter", "lab", "assignment", "summary", "table", "spreadsheet", "chart", "document", "story",
    "speech", "poem", "article", "blog", "memo", "notice", "resume", "cv", "cover", "application", "statement",
    "personal", "purpose", "proposal", "formal", "informal", "professional", "creative", "official",
    "page", "pages", "word", "words", "paragraph", "paragraphs", "it", "this", "that", "about", "on", "of",
}

# Checked in order, so "cover letter" wins over "letter".
_WRITING_KINDS = (
    ("cover_letter", r"\bcover letter\b"),
    ("statement", r"\b(personal statement|statement of purpose|sop|motivation letter|admission essay)\b"),
    ("email", r"\b(e-?mail|mail to)\b"),
    ("letter", r"\b(letter|application for|leave application|application to)\b"),
    ("resume", r"\b(resume|résumé|cv|curriculum vitae)\b"),
    ("memo", r"\b(memo|memorandum|notice|circular)\b"),
    ("poem", r"\b(poem|poetry|haiku|sonnet|limerick|verse)\b"),
    ("story", r"\b(story|short story|narrative|fable|fiction)\b"),
    ("speech", r"\b(speech|toast|eulogy|address to|presentation script)\b"),
    ("post", r"\b(discussion post|discussion board|forum post|reply to (a |my )?(classmate|peer)|peer response)\b"),
    ("outline", r"\boutline\b"),
    ("report", r"\b(report|lab report|case study)\b"),
    ("essay", r"\b(essay|paper|article|blog|term paper|research paper|thesis|reflection)\b"),
)
_TOPIC_QUESTIONS = {
    "cover_letter": "Which job or program is the cover letter for, and what should it highlight about you?",
    "letter": "Who is the letter to, and what should it say?",
    "email": "Who is the email to, and what is it about?",
    "statement": "Which program or school is it for, and what experiences or goals should I include?",
    "resume": "What role is the resume for, and what education, experience, and skills should I include?",
    "memo": "Who is it for, and what should it announce or ask?",
    "poem": "What should the poem be about, and do you want a particular style?",
    "story": "What should the story be about? Any characters, setting, or length in mind?",
    "speech": "What is the speech for, who is the audience, and how long should it be?",
}
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "a": 1, "single": 1, "half": 0.5,
}
_COUNT = r"(\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|a|single|half)"
_WORDS_TARGET = re.compile(r"\b(\d[\d,]*)(?:\s*(?:-|–|to)\s*(\d[\d,]*))?[\s-]*words?\b")
_PAGES_TARGET = re.compile(r"\b" + _COUNT + r"[\s-]*pages?\b")
_PARAGRAPHS_TARGET = re.compile(r"\b" + _COUNT + r"[\s-]*(?:short\s+|long\s+)?paragraphs?\b")
WORDS_PER_PAGE = 300
WORDS_PER_PARAGRAPH = 120


_REQUEST_LEAD = r"(\b(?:write|draft|compose|prepare|create|make|give me|need|want|an?|short|long|formal|\d+[\s-]*words?)\s+)"
_TYPOS = (
    (re.compile(r"\b(essey|eassy|esay|essy|essya|eassay|essage|assay)s?\b", re.I), "essay"),
    (re.compile(_REQUEST_LEAD + r"easy\b(?!\s+(way|to|steps?|explanation|summary|language|english|words?|version|notes?|terms?|and)\b)", re.I), r"\1essay"),
    (re.compile(r"\b(leter|lettr|leeter|lettar|letar)s?\b", re.I), "letter"),
    (re.compile(_REQUEST_LEAD + r"latter\b", re.I), r"\1letter"),
    (re.compile(r"\b(emial|emali|e mail|emal)\b", re.I), "email"),
    (re.compile(r"\b(peom|poam|pome)\b", re.I), "poem"),
    (re.compile(r"\b(paragragh|pargraph|paragrph|pragraph)(s?)\b", re.I), r"paragraph\2"),
    (re.compile(r"\b(applicaton|aplication|applcation)\b", re.I), "application"),
)


def fix_typos(text: str) -> str:
    """Correct common misspellings of writing requests, e.g. "write easy on asthma" -> "write essay on asthma"."""
    for pattern, replacement in _TYPOS:
        text = pattern.sub(replacement, text)
    return text


def missing_topic(text: str) -> bool:
    """True for requests like "write an essay" that name a kind of piece but no subject."""
    words = re.findall(r"[a-z']+", normalize(fix_typos(text)))
    return bool(words) and all(word in _GENERIC_WORDS for word in words)


def writing_kind(*texts: str) -> str:
    for text in texts:
        lowered = normalize(fix_typos(text or ""))
        for kind, pattern in _WRITING_KINDS:
            if re.search(pattern, lowered):
                return kind
    return "general"


def topic_question(text: str, intent: str) -> str:
    kind = writing_kind(text)
    if kind in _TOPIC_QUESTIONS:
        return _TOPIC_QUESTIONS[kind]
    noun = "table" if intent == "table" else kind.replace("_", " ") if kind != "general" else "piece"
    return f"What topic should the {noun} be about, and is there an assignment prompt I should follow?"


def _count(token: str) -> float:
    return _NUMBER_WORDS.get(token, None) or float(token)


def requested_words(*texts: str) -> int | None:
    """Target length from phrases like "500-word", "300 to 500 words", "2 pages", or "three paragraphs"."""
    for text in texts:
        lowered = normalize(text or "")
        words = _WORDS_TARGET.search(lowered)
        if words:
            value = int((words.group(2) or words.group(1)).replace(",", ""))
            if 20 <= value <= 20000:
                return value
        pages = _PAGES_TARGET.search(lowered)
        if pages:
            return int(_count(pages.group(1)) * WORDS_PER_PAGE)
        paragraphs = _PARAGRAPHS_TARGET.search(lowered)
        if paragraphs:
            return int(_count(paragraphs.group(1)) * WORDS_PER_PARAGRAPH)
    return None


def is_affirmative(text: str) -> bool:
    return bool(_AFFIRMATIVE.match(normalize(text)))


def is_negative(text: str) -> bool:
    return bool(_NEGATIVE.match(normalize(text)))


def is_small_talk(text: str) -> bool:
    return normalize(text).strip(" .!?") in _SMALL_TALK


def format_list(formats: list[str]) -> str:
    labels = [FORMAT_LABELS.get(name, name) for name in formats]
    if len(labels) <= 1:
        return "".join(labels)
    return ", ".join(labels[:-1]) + " and " + labels[-1]
