import pytest
from pause_cleanup import pause_candidates


def test_natural_pauses_keep_short_gaps_and_protect_head_tail_and_long_emphasis():
    log='silence_start: 0\nsilence_end: 1\nsilence_start: 2\nsilence_end: 2.2\nsilence_start: 3\nsilence_end: 4.3\nsilence_start: 6\nsilence_end: 8.5\nsilence_start: 9\nsilence_end: 10'
    rows=pause_candidates(log,10)
    assert len(rows)==2 and rows[0]['selected'] and not rows[1]['selected']
    assert rows[0]['cutStart']==pytest.approx(3.225) and rows[0]['cutEnd']==pytest.approx(4.075)
    assert (rows[0]['end']-rows[0]['start'])-(rows[0]['cutEnd']-rows[0]['cutStart'])==pytest.approx(.45)


@pytest.mark.parametrize('minimum,keep',[(.9,0),(.9,.9),(.4,.3),(float('nan'),.45)])
def test_aggressive_or_invalid_pause_settings_rejected(minimum,keep):
    with pytest.raises(ValueError):pause_candidates('',10,minimum,keep)
