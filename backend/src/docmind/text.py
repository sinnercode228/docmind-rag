"""Language-light text utilities (English + Russian): tokenization, stemming, sentences."""

from __future__ import annotations

import re

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_SENTENCE = re.compile(r"[^\n]+?(?:[.!?]+(?=\s)|$)", re.UNICODE | re.MULTILINE)
_CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)

STOPWORDS = frozenset(
    """
    a an the and or but if then else of to in on at by for with about from into over after
    before is are was were be been being do does did have has had i you he she it we they me
    my your our their this that these those what which who whom how when where why can could
    should would will shall may might must not no yes as so than too very just also there
    here any all some each more most other such only own same s t don doesn и в во не что он
    на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было вот от
    меня еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас
    нибудь опять уж вам ведь там потом себя ничего ей может они тут где есть надо ней для мы
    тебя их чем была сам чтоб без будто чего раз тоже себе под будет ж тогда кто этот того
    потому этого какой совсем ним здесь этом один почти мой тем чтобы нее сейчас были куда
    зачем всех никогда можно при наконец два об другой хоть после над больше тот через эти
    нас про всего них какая много разве три эту моя впрочем хорошо свою этой перед иногда
    лучше чуть том нельзя такой им более всегда конечно всю между это как
    """.split()  # noqa: SIM905
)

_RU_SUFFIXES = tuple(
    sorted(
        """
        иями ями ами ией ого ему ому ыми ими ешь ишь ете ите ются ится ется ать ять ить еть
        уть ала ила ыла ела али или ыли ели ует уют ова ева ам ям ах ях ой ей ий ый ая яя ое
        ее ую юю ом ем ов ев ы и а я о е у ю ь
        """.split(),  # noqa: SIM905
        key=len,
        reverse=True,
    )
)
_EN_SUFFIXES = (
    "ational", "fulness", "ingly", "ation", "ments", "ment", "ings", "ing", "edly",
    "ies", "ied", "ed", "es", "ly", "s",
)  # fmt: skip


def is_cyrillic(text: str) -> bool:
    return bool(_CYRILLIC.search(text))


def stem(token: str) -> str:
    """Very small suffix stripper; good enough to match inflected forms for retrieval."""
    token = token.lower().replace("ё", "е")
    suffixes = _RU_SUFFIXES if is_cyrillic(token) else _EN_SUFFIXES
    for suffix in suffixes:
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)]
    return token


def tokenize(text: str) -> list[str]:
    return [t.lower().replace("ё", "е") for t in _TOKEN.findall(text)]


def content_terms(text: str) -> list[str]:
    """Stemmed tokens without stopwords or single characters."""
    return [stem(t) for t in tokenize(text) if t not in STOPWORDS and len(t) > 1]


def sentences(text: str) -> list[tuple[int, int]]:
    """``[start, end)`` spans of sentences/lines in ``text`` (whitespace-trimmed)."""
    spans: list[tuple[int, int]] = []
    for match in _SENTENCE.finditer(text):
        start, end = match.start(), match.end()
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end - start > 1:
            spans.append((start, end))
    return spans


def best_sentence(text: str, query: str) -> tuple[int, int] | None:
    """Span of the sentence in ``text`` sharing the most (stemmed) terms with ``query``.

    Headings are skipped, and sentences carrying concrete facts (digits) get a small bonus,
    because they are usually the actual answer rather than a cross-reference.
    """
    query_terms = set(content_terms(query))
    if not query_terms:
        return None
    best: tuple[float, tuple[int, int]] | None = None
    for start, end in sentences(text):
        if text[start] == "#":
            continue
        terms = content_terms(text[start:end])
        if not terms:
            continue
        overlap = len(query_terms.intersection(terms))
        if overlap == 0:
            continue
        has_fact = any(ch.isdigit() for ch in text[start:end])
        score = overlap + overlap / (len(terms) ** 0.5) + (0.5 if has_fact else 0.0)
        if best is None or score > best[0]:
            best = (score, (start, end))
    return best[1] if best else None
