from __future__ import annotations

from typing import Iterable, List

import nltk

_punkt_ready = False


def ensure_punkt() -> None:
    global _punkt_ready
    if _punkt_ready:
        return
    try:
        nltk.data.find("tokenizers/punkt")
        nltk.data.find("tokenizers/punkt_tab")
    except LookupError:
        nltk.download("punkt", quiet=True)
        nltk.download("punkt_tab", quiet=True)
    _punkt_ready = True


def chunk_sentences(
    sentences: Iterable[str],
    max_sentences: int = 3,
    max_characters: int = 1200,
) -> List[str]:
    chunks: List[str] = []
    buffer: list[str] = []
    char_count = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        projected_chars = char_count + len(sentence)
        if buffer and (len(buffer) >= max_sentences or projected_chars > max_characters):
            chunks.append(" ".join(buffer))
            buffer = []
            char_count = 0

        buffer.append(sentence)
        char_count += len(sentence)

    if buffer:
        chunks.append(" ".join(buffer))

    return chunks


def _sentence_is_informative(
    sentence: str,
    *,
    min_words: int,
    min_alpha_ratio: float,
    language: str,
) -> bool:
    tokens = nltk.word_tokenize(sentence, language=language)
    word_tokens = [token for token in tokens if token.isalpha()]
    if len(word_tokens) < min_words:
        return False

    alnum_chars = sum(ch.isalnum() for ch in sentence)
    alpha_chars = sum(ch.isalpha() for ch in sentence)
    if alnum_chars == 0:
        return False
    if alpha_chars / alnum_chars < min_alpha_ratio:
        return False

    return True


def segment_text(
    text: str,
    max_sentences: int = 3,
    max_characters: int = 1200,
    language: str = "russian",
    min_words: int = 3,
    min_alpha_ratio: float = 0.5,
) -> List[str]:
    ensure_punkt()
    sentences = nltk.sent_tokenize(text, language=language)
    filtered = [
        sentence
        for sentence in sentences
        if _sentence_is_informative(
            sentence,
            min_words=min_words,
            min_alpha_ratio=min_alpha_ratio,
            language=language,
        )
    ]
    return chunk_sentences(
        filtered,
        max_sentences=max_sentences,
        max_characters=max_characters,
    )
