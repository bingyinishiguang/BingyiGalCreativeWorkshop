"""Imported files must enter scanning after restart, not only be copied."""
from pathlib import Path
import zipfile
import pack_import
import sprite_composer as composer


def configure(tmp_path, monkeypatch):
    packs=tmp_path/'packs';packs.mkdir()
    monkeypatch.setattr(composer.app_paths,'packs_dir',lambda:packs)
    monkeypatch.setattr(composer.app_paths,'resolve_data_dir',lambda:tmp_path)
    return packs


def test_copying_games_folder_is_discovered_after_restart(tmp_path,monkeypatch):
    packs=configure(tmp_path,monkeypatch)
    source=tmp_path/'source/games/新作品/角色'
    source.mkdir(parents=True);(source/'pose.txt').write_text('fixture')
    target=pack_import.copy_pack(source.parents[1],packs)
    roots=composer.discover_pack_game_roots(tmp_path)
    assert roots==[target]
    assert composer.game_directories(roots)['新作品']==target/'新作品'


def test_zip_preserves_games_and_single_work_name(tmp_path,monkeypatch):
    packs=configure(tmp_path,monkeypatch)
    for label,prefix in [('direct',''),('wrapped','素材包/')]:
        archive=tmp_path/(label+'.zip')
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr(prefix+'games/新作品/角色/pose.txt','fixture')
        target=pack_import.extract_zip(archive,packs)
        assert (target/'games/新作品/角色/pose.txt').is_file()
        assert target/'games' in composer.discover_pack_game_roots(tmp_path)


def test_legacy_flattened_pack_and_games_link(tmp_path,monkeypatch):
    packs=configure(tmp_path,monkeypatch)
    legacy=packs/'旧解压包/旧作品/角色'
    legacy.mkdir(parents=True);(legacy/'pose.txt').write_text('fixture')
    external=tmp_path/'outside/games/外部作品/角色'
    external.mkdir(parents=True);(external/'pose.txt').write_text('fixture')
    pack_import.add_link(composer.app_paths.links_file(tmp_path),external.parents[1])
    roots=composer.discover_pack_game_roots(tmp_path)
    assert packs/'旧解压包' in roots
    assert external.parents[1] in roots
    assert {'旧作品','外部作品'} <= composer.game_directories(roots).keys()
