"""Published cipher vectors and malformed-input regression checks."""
import struct

import pytest

from pbd_codec import _chacha8, _empty_xxh32, _inflate, _Values, decode_records

@pytest.mark.parametrize('key,expected', [
    (bytes(32), '3e00ef2f895f40d67f5bb8e81f09a5a12c840ec3ce9a7f3b181be188ef711a1e984ce172b9216f419f445367456d5619314a42a3da86b001387bfdb80e0cfe42'),
    (b'\x01'+bytes(31), 'cf5ee9a0494aa9613e05d5ed725b804b12f4a465ee635acc3a311de8740489ea289d04f43c7518db56eb4433e498a1238cd8464d3763ddbb9222ee3bd8fae3c8'),
])
def test_published_chacha8_vectors(key, expected):
    #Crypto++ TestVectors/chacha.txt: original ChaCha8, counter/IV zero.
    assert _chacha8(key, 0, 0, 0).hex() == expected

def frame(block):
    return struct.pack('<H',len(block))+block

def test_xxh32_empty_known_digest():
    assert _empty_xxh32(0) == 0x02cc5d05

def test_lz4_overlap_and_history_across_frames():
    assert _inflate(frame(b'\x10a\x01\x00'), 5) == b'aaaaa'
    assert _inflate(frame(b'\x30abc')+frame(b'\x00\x03\x00'), 7) == b'abcabca'

@pytest.mark.parametrize('payload', [b'\x01',b'\x00\x00',frame(b'\xf0'),
    frame(b'\x20a'),frame(b'\x00\x00\x00'),frame(b'\x00\x01\x00')])
def test_invalid_lz4_is_rejected(payload):
    with pytest.raises(ValueError):
        _inflate(payload, 100)

def test_decompression_cap_is_applied_before_expansion():
    with pytest.raises(ValueError, match='过大'):
        _inflate(frame(b'\x10a\x01\x00'), 4)

@pytest.mark.parametrize('raw', [b'',bytes(16),b'TJS/4s0\0'+struct.pack('<IHH',0,2,0),
    b'TJS/4s0\0'+struct.pack('<IHH',0,1,8)])
def test_unknown_header_profile_rejected(raw):
    with pytest.raises(ValueError):
        decode_records(raw,100)

def test_object_check_and_unknown_tag_rejected():
    with pytest.raises(ValueError,match='校验'):
        _Values(b'\x04\x01'+bytes(8),0).value()
    with pytest.raises(ValueError,match='类型'):
        _Values(b'\xff\x00',0).value()

def test_untrusted_object_count_and_string_length():
    for data in (b'\x81\x00'+struct.pack('<I',0xffffffff),
                 b'\x02\x00'+struct.pack('<I',0xffffffff)):
        with pytest.raises(ValueError):
            _Values(data,0).value()

def test_nested_objects_stop_at_depth_limit():
    nested = (b'\x81\x00'+struct.pack('<I',1))*66 + b'\x04\x00'+bytes(8)
    with pytest.raises(ValueError,match='层数'):
        _Values(nested,0).value()

def test_current_pose_missing_image_filters_only_dependent_combinations(tmp_path):
    from types import SimpleNamespace
    from sprite_composer import _lime_combination_available

    layers = [SimpleNamespace(name=name, filename=filename) for name, filename in (
        ('uniform', 'body.png'), ('happy', 'happy.png'), ('sad', 'sad.png'))]
    pose = SimpleNamespace(pbd_path=tmp_path / 'character.pbd',
                           document=SimpleNamespace(layers=layers),
                           dresses={'uniform': ['clothes/uniform']},
                           faces={'happy': ['face/happy'], 'sad': ['face/sad']})
    (tmp_path / 'body.png').touch()
    (tmp_path / 'happy.png').touch()
    files, names = {}, {}
    assert _lime_combination_available(pose, 'uniform', 'happy', files, names)
    assert not _lime_combination_available(pose, 'uniform', 'sad', files, names)
