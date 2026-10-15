import copy
import json
from pathlib import Path

import pytest

from manuscript_review import compare, apply_review, review_record
from subtitle_tools import format_subtitle, validate_cues
from test_ai_assistant import studio
from ai_subtitle_assistant import SubtitleAssistant


@pytest.mark.parametrize('raw,expected', [
    ('除了课程，他也想学习很多东西。', '除了课程，他也想学习很多东西'),
    ('如果实在理解不了，有时只能放一放，', '如果实在理解不了，有时只能放一放'),
    ('第一句。第二句！', '第一句，第二句'),
    ('他说：“你好。”', '他说：“你好”'),
    ('价格是3.14元。', '价格是3.14元'),
    ('hello, world.', 'hello， world'),
    ('真的？！……', '真的'),
    ('保持原文', '保持原文'),
])
def test_subtitle_rule_preserves_clauses_quotes_and_decimals(raw, expected):
    assert format_subtitle(raw) == expected
    assert format_subtitle(expected) == expected


def test_punctuation_only_subtitle_rejected():
    with pytest.raises(ValueError):
        validate_cues([{'start': 0, 'end': 1, 'text': '……'}], 2)


def cues(texts):
    return [{'start': i, 'end': i+.8, 'text': text} for i, text in enumerate(texts)]


def test_local_typo_matching_keeps_unread_script_and_does_not_shift_later_cues():
    original = cues(['今天我想说几句话', '我也想学很多东酉', '最后谢谢大家'])
    raw = '今天我想说几句话。\n这里是没有读出来的内容。\n我也想学很多东西。\n最后谢谢大家。'
    result = compare(original, raw)
    assert result['rows'][1]['suggested'] == '我也想学很多东西'
    assert result['rows'][2]['suggested'] == '最后谢谢大家'
    assert result['unmatched'] == ['这里是没有读出来的内容']
    assert result['manuscript'] == raw
    assert original[1]['text'] == '我也想学很多东酉'


def test_repeated_and_cross_language_lines_are_not_silently_selected():
    assert not any(r['selected'] for r in compare(cues(['再见', '再见']), '再见。再见。')['rows'])
    result = compare(cues(['こんにちは', 'さようなら']), '今天想说几句话。最后谢谢大家。')
    assert result['matchedCount'] == 0
    assert result['reviewCount'] == 2


def test_explicit_per_line_mapping_requires_exact_count():
    with pytest.raises(ValueError, match='2 行'):
        compare(cues(['a', 'b']), '只有一行', 'lines')
    result = compare(cues(['こんにちは', 'さようなら']), '你好。\n再见。', 'lines')
    assert [r['suggested'] for r in result['rows']] == ['你好', '再见']


def test_review_only_changes_selected_text_and_preserves_original_manuscript():
    project = {'audioClips': [{'id': 'voice', 'cues': cues(['第一条', '第二条']), 'volume': .7}],
               'scenes': [{'id': 'background', 'duration': 5}], 'textClips': [{'text': '标题。'}]}
    original = copy.deepcopy(project)
    changed = apply_review(project, 'voice', [{'cueIndex': 0, 'text': '修改第一条，保留逗号。'}], '作者原稿。', '原稿.txt')
    assert changed['audioClips'][0]['cues'][0] == {**original['audioClips'][0]['cues'][0], 'text': '修改第一条，保留逗号'}
    assert changed['audioClips'][0]['cues'][1] == original['audioClips'][0]['cues'][1]
    assert changed['scenes'] == original['scenes']
    assert changed['textClips'] == original['textClips']
    assert changed['audioClips'][0]['manuscript']['text'] == '作者原稿。'
    assert project == original


@pytest.mark.parametrize('rows', [
    [{'cueIndex': True, 'text': 'x'}], [{'cueIndex': 0, 'text': ''}],
    [{'cueIndex': 5, 'text': 'x'}], [{'cueIndex': 0, 'text': 'x'}, {'cueIndex': 0, 'text': 'y'}],
])
def test_invalid_review_rows_are_rejected(rows):
    with pytest.raises(ValueError):
        apply_review({'audioClips': [{'id': 'voice', 'cues': cues(['a'])}]}, 'voice', rows, '原文')


def test_record_hash_is_derived_and_limits_enforced():
    assert review_record({'text': '原文。', 'hash': 'fake'})['hash'] != 'fake'
    with pytest.raises(ValueError):
        review_record({'text': 'a'*100001})


def test_manuscript_persists_and_export_enforces_subtitle_rule_without_changing_title(tmp_path, studio):
    cut, audio, item, project = studio
    project['audioClips'][0]['cues'] = [{'start': 1, 'end': 2, 'text': '原始字幕。'}]
    project['textClips'][0]['text'] = '独立标题。'
    assistant = SubtitleAssistant(tmp_path/'assistant', cut, audio)
    reviewed = assistant.manuscript_apply({'project': project, 'clipId': project['audioClips'][0]['id'],
        'rows': [{'cueIndex': 0, 'text': '保留逗号，去掉句末。'}], 'manuscript': '保留逗号，去掉句末。', 'name': '稿.txt'})['project']
    saved = cut.save(reviewed)
    loaded = cut.load(saved['id'])
    assert loaded['audioClips'][0]['manuscript']['text'] == '保留逗号，去掉句末。'
    exported = cut.export(loaded)
    content = json.loads((Path(exported['path'])/'draft_content.json').read_text('utf-8'))
    texts = [json.loads(m['content'])['text'] for m in content['materials']['texts']]
    assert '保留逗号，去掉句末' in texts
    assert '独立标题。' in texts
