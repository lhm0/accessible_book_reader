from abr.text_logic import OCRTextPostProcessor


def test_postprocessor_merges_hyphenated_line_breaks() -> None:
    processor = OCRTextPostProcessor()

    result = processor.build_paragraph_text(["Sie sprachen ueber Krieg-", "reden und Frieden."])

    assert result == "Sie sprachen ueber Kriegreden und Frieden."


def test_postprocessor_keeps_non_hyphenated_line_breaks_when_next_line_not_lowercase() -> None:
    processor = OCRTextPostProcessor()

    result = processor.build_paragraph_text(["Ende des Kapi-", "Tels war erreicht."])

    assert result == "Ende des Kapi- Tels war erreicht."


def test_postprocessor_removes_isolated_letter_tokens() -> None:
    processor = OCRTextPostProcessor()

    result = processor.build_paragraph_text(["Das ist a ein Test b mit Fehlern."])

    assert result == "Das ist ein Test mit Fehlern."


def test_postprocessor_removes_short_consonant_fragments() -> None:
    processor = OCRTextPostProcessor()

    result = processor.build_paragraph_text(["nn An diesem Nachmittag beginnt der Test."])

    assert result == "An diesem Nachmittag beginnt der Test."


def test_postprocessor_keeps_two_letter_words() -> None:
    processor = OCRTextPostProcessor()

    result = processor.build_paragraph_text(["Im Nu ist es zu Ende."])

    assert result == "Im Nu ist es zu Ende."


def test_postprocessor_removes_orphan_percent_signs() -> None:
    processor = OCRTextPostProcessor()

    result = processor.build_paragraph_text(["Das kostet % viel, aber 10 % sind erlaubt und abc% nicht."])

    assert result == "Das kostet viel, aber 10 % sind erlaubt und abc nicht."


def test_postprocessor_collapses_spaced_uppercase_word_before_removing_single_letters() -> None:
    processor = OCRTextPostProcessor()

    result = processor.build_paragraph_text(["Die Ü B E R S C H R I F T. Danach geht es weiter."])

    assert result == "Die ÜBERSCHRIFT. Danach geht es weiter."


def test_postprocessor_collapses_spaced_lowercase_word_and_preserves_following_space() -> None:
    processor = OCRTextPostProcessor()

    result = processor.build_paragraph_text(["Das ist g e s p e r r t geschrieben."])

    assert result == "Das ist gesperrt geschrieben."


def test_postprocessor_does_not_join_only_two_isolated_letters() -> None:
    processor = OCRTextPostProcessor()

    result = processor.collapse_spaced_letter_sequences("Die Initialen A B bleiben getrennt.")

    assert result == "Die Initialen A B bleiben getrennt."


def test_postprocessor_does_not_join_letters_across_line_or_paragraph_boundaries() -> None:
    processor = OCRTextPostProcessor()

    result = processor.collapse_spaced_letter_sequences("A B\nC D\n\nE F")

    assert result == "A B\nC D\n\nE F"


def test_postprocessor_converts_all_uppercase_heading_to_title_case() -> None:
    processor = OCRTextPostProcessor()

    result = processor.build_paragraph_text(["ERLEBNIS IN DER KNABENZEIT"])

    assert result == "Erlebnis In Der Knabenzeit"


def test_postprocessor_keeps_normal_sentence_case_unchanged() -> None:
    processor = OCRTextPostProcessor()

    result = processor.normalize_uppercase_heading("Der Schlosser Mohr ging nach Hause.")

    assert result == "Der Schlosser Mohr ging nach Hause."


def test_postprocessor_expands_german_doctor_abbreviation_for_speech() -> None:
    processor = OCRTextPostProcessor()

    result = processor.expand_german_spoken_abbreviations("Dr. Müller sprach mit Dr. Weber.")

    assert result == "Doktor Müller sprach mit Doktor Weber."


def test_postprocessor_does_not_expand_doctor_abbreviation_inside_a_word() -> None:
    processor = OCRTextPostProcessor()

    result = processor.expand_german_spoken_abbreviations("Die Datei Dr.med bleibt unverändert.")

    assert result == "Die Datei Dr.med bleibt unverändert."


def test_postprocessor_normalizes_notre_dame_for_german_speech() -> None:
    processor = OCRTextPostProcessor()

    result = processor.normalize_german_spoken_text("Sie gingen zur Notre-Dame in Paris.")

    assert result == "Sie gingen zur Notre Damm in Paris."


def test_postprocessor_does_not_normalize_notre_dame_inside_a_word() -> None:
    processor = OCRTextPostProcessor()

    result = processor.normalize_german_spoken_text("Der Dateiname lautet Notre-Dame-Foto.")

    assert result == "Der Dateiname lautet Notre-Dame-Foto."
