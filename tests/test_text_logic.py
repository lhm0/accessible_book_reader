from abr.text_logic import ReadingStreamBuilder, SentenceSegmenter


def test_sentence_segmenter_keeps_fragment() -> None:
    segmenter = SentenceSegmenter()

    chunks = segmenter.split("Er oeffnete langsam die Tuer und blickte hinaus. Dann schwieg er")

    assert chunks == ["Er oeffnete langsam die Tuer und blickte hinaus.", "Dann schwieg er"]
    assert segmenter.is_complete(chunks[0]) is True
    assert segmenter.is_complete(chunks[1]) is False


def test_reading_stream_builder_merges_across_pages() -> None:
    builder = ReadingStreamBuilder()

    first_page = builder.consume_page("page_1", ["Er oeffnete langsam die Tuer und"])
    second_page = builder.consume_page("page_2", ["blickte in den dunklen Raum."])
    tail = builder.flush()

    assert first_page == []
    assert len(second_page) == 1
    assert second_page[0].text == "Er oeffnete langsam die Tuer und blickte in den dunklen Raum."
    assert second_page[0].complete is True
    assert second_page[0].source_pages == ["page_1", "page_2"]
    assert tail is None
