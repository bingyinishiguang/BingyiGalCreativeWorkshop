import re
from gal_story_render import lines_for,face

def test_ordinary_english_words_are_kept_whole_without_discarding_spaces():
    text='The midnight workshop is quiet. 明天见。'
    lines=lines_for(text,34,240)
    assert ''.join(lines)==text
    assert re.findall(r'[A-Za-z]+','\n'.join(lines))==re.findall(r'[A-Za-z]+',text)
    assert all(face(34).getlength(line)<=240 for line in lines)

def test_oversized_word_is_split_without_losing_source_characters():
    text='BingyiGalCreativeWorkshopVeryLongIdentifier'
    lines=lines_for(text,34,100)
    assert len(lines)>1 and ''.join(lines)==text
    assert all(face(34).getlength(line)<=100 for line in lines)
