from dataclasses import replace
import json

import pytest

from abr.book import BookStore, PageIngestor
from abr.book.chapter_assembler import ChapterAssembler
from abr.book.models import PageRecord
from abr.book.page_number_repair import repair_previous_spread
from abr.book.store import _write_json


def setup_book(tmp_path):
    store = BookStore(tmp_path / 'library')
    store.ensure_book('book', language='de')
    old = tuple(PageRecord(
        page_id=f'page_{i}', scan_id='old', created_at='2026-09-01T12:00:00Z',
        side=side, clean_text='' if i == 1 else 'Anfang.', speak_text='' if i == 1 else 'Anfang.',
        metadata={'report_page_id': f'page_{i}', 'language': 'de',
                  'page_number_sequence_valid': False},
    ) for i, side in enumerate(('left', 'right'), 1))
    for page in old:
        store.save_page('book', page)
    current = tuple(replace(page, page_id=f'page_{n:04d}', page_number=n,
                            scan_id='new', created_at='2026-09-01T12:01:00Z')
                    for page, n in zip(old, (7, 8)))
    return store, old, current


def test_repairs_references_and_preserves_prose_and_source_ids(tmp_path):
    store, old, current = setup_book(tmp_path)
    root = store.book_dir('book')
    boundary = {'page_id': 'page_1', 'page_number': None, 'scan_id': 'old', 'side': 'left', 'offset': 0}
    store.save_runtime_state('book', 'chapter_assembler_state.json',
                             {'current_start': boundary, 'next_sequence': 2})
    store.save_runtime_state('book', 'pending_right_tail_fragment.json',
                             {'page_id': 'page_2', 'page_number': None, 'tail_fragment': 'page_1'})
    _write_json(root / 'scans/old/manifest.json',
                {'scan_id': 'old', 'left_page_id': 'page_1', 'right_page_id': 'page_2'})
    _write_json(root / 'scans/unrelated/manifest.json',
                {'scan_id': 'unrelated', 'left_page_id': 'page_1', 'right_page_id': 'page_2'})
    chapter = {'chapter_id': 'chapter_0001', 'page_ids': ['page_1', 'page_2'],
               'page_numbers': [], 'start_page': None, 'end_page': None,
               'metadata': {'start_boundary': boundary, 'next_start_boundary': boundary}}
    _write_json(root / 'chapters/chapter_0001/chapter.json', chapter)
    _write_json(root / 'summaries/chapter_0001_summary.json',
                {'text': 'page_1 remains prose.', 'metadata': {'chapter_id': 'chapter_0001',
                 'start_page': None, 'end_page': None}})
    result = repair_previous_spread(store, 'book', current)
    assert [p.page_number for p in result] == [5, 6]
    assert store.load_page('book', 'page_1') is None
    assert store.load_page('book', 'page_2') is None
    assert store.load_page('book', 5).clean_text == ''
    assert store.load_page('book', 6).metadata['report_page_id'] == 'page_2'
    assert store.load_page('book', 6).metadata['page_number_inferred'] is True
    read = lambda path: json.loads((root / path).read_text())
    assert read('scans/old/manifest.json')['left_page_id'] == 'page_0005'
    assert read('scans/unrelated/manifest.json')['left_page_id'] == 'page_1'
    updated = read('chapters/chapter_0001/chapter.json')
    assert updated['page_ids'] == ['page_0005', 'page_0006']
    assert updated['page_numbers'] == [5, 6]
    assert updated['start_page'] == 5 and updated['end_page'] == 6
    assert updated['metadata']['next_start_boundary']['page_number'] == 5
    summary = read('summaries/chapter_0001_summary.json')
    assert summary['metadata']['start_page'] == 5
    assert summary['text'] == 'page_1 remains prose.'
    assert read('state/pending_right_tail_fragment.json') == {
        'page_id': 'page_0006', 'page_number': 6, 'tail_fragment': 'page_1'}
    assert ChapterAssembler(store).collect_pending_content('book').page_numbers == (6,)
    before = {p: p.read_bytes() for p in root.rglob('*.json')}
    assert repair_previous_spread(store, 'book', current) == ()
    assert before == {p: p.read_bytes() for p in root.rglob('*.json')}


@pytest.mark.parametrize('condition', ['single', 'unnumbered', 'gap', 'too_low', 'missing_left',
    'missing_right', 'occupied_left', 'occupied_right', 'different_old_scans', 'same_scan',
    'wrong_side', 'already_numbered', 'future'])
def test_does_not_repair_unless_all_conditions_hold(tmp_path, condition):
    store, old, current = setup_book(tmp_path)
    root = store.book_dir('book')
    if condition == 'single':
        current = current[:1]
    elif condition == 'unnumbered':
        current = (current[0], replace(current[1], page_number=None))
    elif condition == 'gap':
        current = (current[0], replace(current[1], page_number=9))
    elif condition == 'too_low':
        current = (replace(current[0], page_number=2), replace(current[1], page_number=3))
    elif condition.startswith('missing_'):
        (root / 'pages' / ('page_1.json' if condition.endswith('left') else 'page_2.json')).unlink()
    elif condition.startswith('occupied_'):
        n = 5 if condition.endswith('left') else 6
        store.save_page('book', replace(old[0], page_id=f'page_{n:04d}', page_number=n))
    else:
        values = {'different_old_scans': {'scan_id': 'other'}, 'same_scan': {'scan_id': 'new'},
                  'wrong_side': {'side': 'right'}, 'already_numbered': {'page_number': 99},
                  'future': {'created_at': '2026-10-01T00:00:00Z'}}[condition]
        _write_json(root / 'pages/page_1.json', replace(old[0], **values).to_dict())
    before = {p: p.read_bytes() for p in root.rglob('*.json')}
    assert repair_previous_spread(store, 'book', current) == ()
    assert before == {p: p.read_bytes() for p in root.rglob('*.json')}


def test_ingest_waits_for_full_spread_and_carries_previous_tail(tmp_path):
    store, old, current = setup_book(tmp_path)
    store.save_page('book', replace(old[1], tail_fragment='Er ging'))
    report = tmp_path / 'report.json'
    pages = [{'page_id': f'page_{i}', 'slot': side, 'page_number': n,
              'ocr_lines': [{'text': text}]} for i, side, n, text in
             [(1, 'left', 7, 'weiter.'), (2, 'right', 8, 'Ein Ende.')]]
    report.write_text(json.dumps({'pages': pages[:1]}))
    ingestor = PageIngestor(store)
    first = ingestor.ingest_report('book', report, scan_id='new', created_at=current[0].created_at)
    assert first.repaired_pages == ()
    report.write_text(json.dumps({'pages': pages}))
    result = ingestor.ingest_report('book', report, scan_id='new', created_at=current[0].created_at)
    assert [p.page_number for p in result.repaired_pages] == [5, 6]
    assert result.pages[0].speak_text == 'Er ging weiter.'
    assert store.load_page('book', 7).speak_text == 'Er ging weiter.'
    assert sorted(p.name for p in (store.book_dir('book') / 'pages').glob('*.json')) == [
        '0005.json', '0006.json', '0007.json', '0008.json']


def test_write_failure_restores_originals(tmp_path, monkeypatch):
    store, old, current = setup_book(tmp_path)
    root = store.book_dir('book')
    store.save_runtime_state('book', 'boundary.json', {'page_id': 'page_1', 'page_number': None})
    before = {p: p.read_bytes() for p in root.rglob('*.json')}
    def fail_on_reference(path, data):
        if path.name == 'boundary.json':
            raise OSError('simulated write failure')
        _write_json(path, data)
    monkeypatch.setattr('abr.book.page_number_repair._write_json', fail_on_reference)
    with pytest.raises(OSError):
        repair_previous_spread(store, 'book', current)
    assert before == {p: p.read_bytes() for p in root.rglob('*.json')}
