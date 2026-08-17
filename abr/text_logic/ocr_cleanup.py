from __future__ import annotations

import re


class OCRTextPostProcessor:
    VOWELS = set("aeiouäöüAEIOUÄÖÜ")
    _SPACED_LETTER_SEQUENCE_RE = re.compile(
        r"(?<!\w)(?:[^\W\d_][^\S\r\n]+){2,}[^\W\d_](?!\w)",
        flags=re.UNICODE,
    )
    _GERMAN_DOCTOR_ABBREVIATION_RE = re.compile(r"(?<!\w)Dr\.(?=\s|$)")
    _GERMAN_NOTRE_DAME_RE = re.compile(r"(?<![\w-])Notre-Dame(?![\w-])")

    def build_paragraph_text(self, line_texts: list[str]) -> str:
        merged = self._merge_line_break_hyphenation(line_texts)
        without_letter_spacing = self.collapse_spaced_letter_sequences(merged)
        with_readable_heading = self.normalize_uppercase_heading(without_letter_spacing)
        without_single_letters = self._remove_isolated_letter_tokens(with_readable_heading)
        without_consonant_fragments = self._remove_short_consonant_fragments(without_single_letters)
        without_orphan_percent = self._remove_orphan_percent_signs(without_consonant_fragments)
        return " ".join(without_orphan_percent.split())

    def collapse_spaced_letter_sequences(self, text: str) -> str:
        """Collapse typographic letter spacing while preserving surrounding whitespace."""

        return self._SPACED_LETTER_SEQUENCE_RE.sub(
            lambda match: re.sub(r"[^\S\r\n]+", "", match.group(0)),
            text,
        )

    def expand_german_spoken_abbreviations(self, text: str) -> str:
        """Expand abbreviations whose punctuation would mislead German TTS."""

        return self._GERMAN_DOCTOR_ABBREVIATION_RE.sub("Doktor", text)

    def normalize_german_spoken_text(self, text: str) -> str:
        """Apply German-only pronunciation substitutions for TTS."""

        expanded = self.expand_german_spoken_abbreviations(text)
        return self._GERMAN_NOTRE_DAME_RE.sub("Notre Damm", expanded)

    @staticmethod
    def is_uppercase_heading(text: str) -> bool:
        stripped = text.strip()
        words = stripped.split()
        letters = [character for character in stripped if character.isalpha()]
        return not (
            not letters
            or not all(character.isupper() for character in letters)
            or len(words) < 2
            or len(words) > 10
            or len(stripped) > 80
        )

    @classmethod
    def normalize_uppercase_heading(cls, text: str) -> str:
        """Use title case for short all-uppercase lines so TTS does not spell them."""

        stripped = text.strip()
        if not cls.is_uppercase_heading(stripped):
            return text
        normalized = stripped.title()
        return text.replace(stripped, normalized, 1)

    def _merge_line_break_hyphenation(self, line_texts: list[str]) -> str:
        if not line_texts:
            return ""

        merged = line_texts[0].strip()
        for next_line in line_texts[1:]:
            normalized_next = next_line.strip()
            if not normalized_next:
                continue

            if merged.rstrip().endswith("-") and self._starts_with_lowercase_letter(normalized_next):
                merged = merged.rstrip()[:-1] + normalized_next
            else:
                merged = f"{merged.rstrip()} {normalized_next}"
        return merged.strip()

    def _remove_isolated_letter_tokens(self, text: str) -> str:
        tokens = text.split()
        filtered_tokens = [token for token in tokens if not self._is_isolated_letter_token(token)]
        return " ".join(filtered_tokens)

    def _remove_short_consonant_fragments(self, text: str) -> str:
        tokens = text.split()
        filtered_tokens = [token for token in tokens if not self._is_short_consonant_fragment(token)]
        return " ".join(filtered_tokens)

    def _remove_orphan_percent_signs(self, text: str) -> str:
        result_chars: list[str] = []
        for char in text:
            if char != "%":
                result_chars.append(char)
                continue

            previous_significant = self._previous_non_space_char(result_chars)
            if previous_significant and previous_significant.isdigit():
                result_chars.append(char)
        return "".join(result_chars)

    @staticmethod
    def _is_isolated_letter_token(token: str) -> bool:
        return len(token) == 1 and token.isalpha()

    @classmethod
    def _is_short_consonant_fragment(cls, token: str) -> bool:
        return (
            len(token) == 2
            and token.isalpha()
            and token.islower()
            and not any(char in cls.VOWELS for char in token)
        )

    @staticmethod
    def _starts_with_lowercase_letter(text: str) -> bool:
        first_char = text[:1]
        return bool(first_char) and first_char.isalpha() and first_char.islower()

    @staticmethod
    def _previous_non_space_char(chars: list[str]) -> str | None:
        for char in reversed(chars):
            if not char.isspace():
                return char
        return None
