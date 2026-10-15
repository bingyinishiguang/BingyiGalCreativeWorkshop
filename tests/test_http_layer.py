"""本机 HTTP 接口、静态资源与输入边界回归。"""
from __future__ import annotations

import http.cookiejar
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import app_paths
import sprite_composer


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    root = tmp_path_factory.mktemp("http-server")
    original_resolve = sprite_composer.app_paths.resolve_data_dir
    original_packs = sprite_composer.app_paths.packs_dir
    original_log = sprite_composer._startup_log
    original_summary = sprite_composer._write_scan_summary
    original_url = getattr(sprite_composer, "LAST_URL", None)


    packs = root / "sprite-packs"
    packs.mkdir(parents=True, exist_ok=True)

    sprite_composer.app_paths.resolve_data_dir = lambda: root
    sprite_composer.app_paths.packs_dir = lambda: packs
    sprite_composer._startup_log = lambda message: None
    sprite_composer._write_scan_summary = lambda payload: None
    sprite_composer.LAST_URL = None

    policy = sprite_composer.IsolationPolicy.load(root / "isolation-decisions.json")
    state = sprite_composer.BootState(root, root / "exports")
    state.publish({}, {}, {}, policy)
    _SERVER_STATE.clear()
    _SERVER_STATE.append(state)
    thread = threading.Thread(
        target=sprite_composer.run_web_app,
        args=(root, state),
        kwargs={"open_browser": False, "scan_in_background": False},
        daemon=True,
    )
    thread.start()

    url = None
    for _ in range(100):
        url = getattr(sprite_composer, "LAST_URL", None)
        if url:
            break
        time.sleep(0.1)
    if not url:
        pytest.skip("本地服务未能在 10 秒内启动")


    ready = False
    probe = urllib.request.build_opener()
    for _ in range(100):
        try:
            with probe.open(url.rstrip("/") + "/", timeout=2) as response:
                response.read(1)
            ready = True
            break
        except Exception:
            time.sleep(0.05)
    if not ready:
        pytest.skip("本地服务已启动但未能接受连接")

    yield url.rstrip("/")

    sprite_composer.app_paths.resolve_data_dir = original_resolve
    sprite_composer.app_paths.packs_dir = original_packs
    sprite_composer._startup_log = original_log
    sprite_composer._write_scan_summary = original_summary
    sprite_composer.LAST_URL = original_url


@pytest.fixture(scope="module")
def server_state(server):
    """`server` 那份 BootState 的 output_root —— 服务真正使用的立绘库位置。"""
    return _SERVER_STATE[0]


_SERVER_STATE: list = []


def test_background_and_roughcut_endpoints(server, server_state, tmp_path):
    from PIL import Image
    source = tmp_path / '背景.png'
    Image.new('RGB', (640, 360), '#234567').save(source)
    unauthenticated = _opener()
    status, _ = _post(unauthenticated, server + '/api/backgrounds/import', {'paths': [str(source)]})
    assert status == 403
    opener = _opener()
    _get(opener, server + '/')
    status, body = _post(opener, server + '/api/backgrounds/import', {'paths': [str(source)]})
    assert status == 200, body
    item = json.loads(body)['results'][0]['item']
    status, body = _get(opener, server + '/api/backgrounds')
    assert status == 200 and json.loads(body)['total'] == 1
    media_url = server + '/api/backgrounds/media?id=' + item['id']
    request = urllib.request.Request(media_url, headers={'Range':'bytes=0-7'})
    with opener.open(request) as response:
        assert response.status == 206
        assert response.read() == b'\x89PNG\r\n\x1a\n'
        assert response.headers['Content-Range'].startswith('bytes 0-7/')
    request = urllib.request.Request(media_url, headers={'Range':'bytes=999999999-'})
    with pytest.raises(urllib.error.HTTPError) as error:
        opener.open(request)
    assert error.value.code == 416
    status, body = _post(opener, server + '/api/roughcut/export', {
        'name':'HTTP 粗剪测试','scenes':[{'background':item['id'],'duration':2,'actors':[]}]})
    assert status == 200, body
    result = json.loads(body)
    assert result['duration'] == 2
    assert Path(result['path']).is_relative_to(server_state.data_dir)
    status, body = _get(opener, server + '/api/roughcut/project?id=' + result['project']['id'])
    assert status == 200 and json.loads(body)['name'] == 'HTTP 粗剪测试'
    status, _ = _get(opener, server + '/api/roughcut/project?id=../../escape')
    assert status == 400


def _opener():
    """带 cookie 的 opener —— 等价于浏览器同源请求（前端就是这样拿到令牌的）。"""
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def test_assistant_http_routes_and_secret_redaction(server):
    url = server
    opener = _opener()
    _get(opener, url + '/')
    status, body = _get(opener, url + '/api/assistant/settings')
    assert status == 200
    assert json.loads(body)['models'] == []
    status, body = _post(opener, url + '/api/assistant/settings', {
        'models': [{'id': 'http-assistant-test', 'name': '连接验收',
                    'baseUrl': 'https://example.invalid/v1', 'model': 'test-model',
                    'apiKey': 'test-private-model-key'}],
        'activeModelId': 'http-assistant-test',
        'translation': {'appId': 'test-app', 'secret': 'test-private-baidu-key'}})
    assert status == 200
    assert 'test-private' not in body
    status, body = _get(opener, url + '/api/assistant/settings')
    assert status == 200 and b'test-private' not in body
    settings = json.loads(body)
    assert settings['models'][0]['hasApiKey'] is True
    assert settings['translation']['hasSecret'] is True
    status, body = _get(opener, url + '/api/assistant/job?id=does-not-exist')
    assert status == 400 and 'error' in json.loads(body)


def test_manuscript_and_existing_draft_routes_are_live_and_authenticated(server):
    for route in ('/api/assistant/manuscript-preview','/api/assistant/manuscript-apply',
                  '/api/assistant/normalize-subtitles','/api/existing-draft/load',
                  '/api/existing-draft/preview','/api/existing-draft/normalize','/api/existing-draft/save',
                  '/api/existing-draft/chat','/api/existing-draft/progress-save',
                  '/api/existing-draft/style-info','/api/existing-draft/style-preview','/api/existing-draft/preset-save',
                  '/api/existing-draft/progress-backup','/api/existing-draft/recovery-list',
                  '/api/existing-draft/recovery-preview'):
        status,_=_post(_opener(),server+route,{})
        assert status==403
        opener=_opener();_get(opener,server+'/')
        status,body=_post(opener,server+route,{})
        if route.endswith('normalize-subtitles'):
            assert status==200 and 'project' in json.loads(body)
        else:
            assert status==400 and 'error' in json.loads(body)
    for script in ('manuscript_review.js','existing_draft.js'):
        status,body=_get(_opener(),server+'/ui/'+script)
        assert status==200 and len(body)>100


def _post(opener, url, payload):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with opener.open(request, timeout=20) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


def _get(opener, url):
    request = urllib.request.Request(url, method="GET")
    try:
        with opener.open(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def test_home_page_sets_session_cookie(server):
    opener = _opener()
    status, _ = _get(opener, server + "/")
    assert status == 200


def test_gal_story_routes_save_large_project_and_return_measured_preview(server):
    opener=_opener();assert _get(opener,server+'/')[0]==200
    for route in ('status','catalog','projects','last'):
        status,body=_get(opener,server+'/api/gal-story/'+route)
        assert status==200,body
    status,body=_post(opener,server+'/api/gal-story/demo',{})
    assert status==200,body
    project=json.loads(body)
    # Raw UTF-8 is modest; default JSON encoding expands CJK text sixfold.
    project['originalText']='原稿保留，不因请求过长而丢失。'*6000
    assert len(project['originalText'])<100000
    status,body=_post(opener,server+'/api/gal-story/save',{'project':project})
    assert status==200,body
    status,body=_get(opener,server+'/api/gal-story/project?id='+project['id'])
    assert status==200 and json.loads(body)['originalText']==project['originalText']
    status,body=_post(opener,server+'/api/gal-story/plan',{'project':project})
    assert status==200 and len(json.loads(body)['segments'])==13
    request=urllib.request.Request(server+'/api/gal-story/preview',data=json.dumps({'project':project,'time':2}).encode(),headers={'Content-Type':'application/json'},method='POST')
    with opener.open(request,timeout=20) as response:
        assert response.headers['Content-Type']=='image/jpeg'
        assert response.read(2)==b'\xff\xd8'
    assert _post(_opener(),server+'/api/gal-story/save',{'project':project})[0]==403
    assert _get(opener,server+'/api/gal-story/project?id=../outside')[0]==400


def test_post_without_token_is_rejected(server):
    status, body = _post(_opener(), server + "/api/settings",
                         {"singleMode": "browser", "singlePath": "", "batchPath": ""})
    assert status == 403, body


def test_post_with_same_origin_cookie_works(server):
    opener = _opener()
    assert _get(opener, server + "/")[0] == 200
    status, body = _post(opener, server + "/api/settings",
                         {"singleMode": "browser", "singlePath": "", "batchPath": ""})
    assert status == 200, body


def test_bad_query_parameter_returns_400_not_500(server):
    status, _ = _get(_opener(), server + "/api/library?offset=abc")
    assert status == 400


def test_missing_preview_parameter_returns_400(server):
    status, _ = _get(_opener(), server + "/api/preview")
    assert status == 400


def test_catalog_is_served(server):
    status, body = _get(_opener(), server + "/api/catalog")
    assert status == 200
    assert json.loads(body.decode("utf-8")) == {}


def test_removed_unpack_endpoints_return_404(server):
    opener = _opener()
    _get(opener, server + "/")
    for path in ("/api/unpack/open", "/api/unpack/extract", "/api/unpack/open-dir",
                 "/api/unpack/choose-file", "/api/unpack/choose-dir"):
        status, _ = _post(opener, server + path, {})
        assert status == 404, path


def test_import_endpoints_exist(server):
    opener = _opener()
    _get(opener, server + "/")
    status, _ = _post(opener, server + "/api/library/import-commit", {"paths": []})
    assert status == 400, "空路径应回 400 说明，而不是 404 或 500"




@pytest.fixture(scope="module")
def booting_server(tmp_path_factory):
    """数据故意不就绪的服务：用来验证 /api/boot 与闸门行为。"""
    root = tmp_path_factory.mktemp("http-booting")
    original_resolve = sprite_composer.app_paths.resolve_data_dir
    original_log = sprite_composer._startup_log
    original_url = getattr(sprite_composer, "LAST_URL", None)
    sprite_composer.app_paths.resolve_data_dir = lambda: root
    sprite_composer._startup_log = lambda message: None
    sprite_composer.LAST_URL = None

    state = sprite_composer.BootState(root, root / "exports")
    state.set_phase(1, "正在把立绘一张张理出来")
    state.set_progress(3, 7)
    thread = threading.Thread(
        target=sprite_composer.run_web_app,
        args=(root, state),
        kwargs={"open_browser": False, "scan_in_background": True, "gate_on_ready": True,
                "auto_scan": False},
        daemon=True,
    )
    thread.start()
    url = None
    for _ in range(100):
        url = getattr(sprite_composer, "LAST_URL", None)
        if url:
            break
        time.sleep(0.1)
    if not url:
        pytest.skip("本地服务未能在 10 秒内启动")
    probe = urllib.request.build_opener()
    for _ in range(100):
        try:
            with probe.open(url.rstrip("/") + "/", timeout=2) as response:
                response.read(1)
            break
        except Exception:
            time.sleep(0.05)


    state.gate_timeout[0] = 0.3


    previous_url = getattr(sprite_composer, "LAST_URL", None)
    sprite_composer.LAST_URL = url
    yield url.rstrip("/"), state
    sprite_composer.LAST_URL = previous_url
    sprite_composer.app_paths.resolve_data_dir = original_resolve
    sprite_composer._startup_log = original_log
    sprite_composer.LAST_URL = original_url


def test_boot_endpoint_reports_real_progress(booting_server):
    url, _state = booting_server
    opener = _opener()
    _get(opener, url + "/")
    status, body = _get(opener, url + "/api/boot")
    assert status == 200
    payload = json.loads(body.decode("utf-8"))
    assert payload["ready"] is False
    assert payload["phase"] == 1
    assert payload["done"] == 3 and payload["total"] == 7
    assert payload["catalogReady"] is False


def test_data_endpoints_wait_for_scan_then_503(booting_server):
    url, _state = booting_server
    opener = _opener()
    _get(opener, url + "/")

    status, body = _get(opener, url + "/api/catalog")
    assert status == 503, body[:200]
    assert json.loads(body.decode("utf-8"))["booting"] is True


def test_draft_workflow_script_is_served(server):
    url = server
    opener = _opener()
    status, body = _get(opener, url + '/ui/draft_workflow.js')
    assert status == 200
    assert b'draft-legacy-tools' in body


def test_boot_page_assets_are_served(booting_server):
    from html.parser import HTMLParser

    class PageAssets(HTMLParser):
        def __init__(self):
            super().__init__()
            self.resources = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "link" and attrs.get("rel") == "stylesheet":
                self.resources.append((attrs["href"], "text/css"))
            elif tag == "script" and attrs.get("src"):
                self.resources.append((attrs["src"], "text/javascript"))

    url, _state = booting_server
    opener = _opener()
    status, body = _get(opener, url + "/")
    assert status == 200
    page = PageAssets()
    page.feed(body.decode("utf-8"))
    assert page.resources
    for resource, content_type in page.resources:
        with opener.open(url + resource, timeout=10) as response:
            assert response.status == 200, resource
            assert response.headers.get_content_type() == content_type, resource
            assert response.read(), resource
    for name in ("boot-01-default.png", "boot-02-searching.png",
                 "boot-03-ready.png", "boot-04-done.png"):
        status, body = _get(opener, f"{url}/ui/loading/{name}")
        assert status == 200, name
        assert body[:8] == b"\x89PNG\r\n\x1a\n", f"{name} 不是 PNG"


def test_zip_pack_copy_import_extracts(server, tmp_path):
    import uuid
    import zipfile

    import pack_import

    url = server

    pack_name = f"素材包-精简-{uuid.uuid4().hex[:8]}"
    build = tmp_path / pack_name
    (build / "games" / "角色A").mkdir(parents=True)
    (build / "games" / "角色A" / "body.pbd").write_bytes(b"PBD" + b"\x00" * 64)
    (build / "games" / "角色A" / "body.txt").write_text("body.pbd\t0\t0\n", encoding="utf-8")
    archive = tmp_path / f"{pack_name}.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        for item in build.rglob("*"):
            if item.is_file():
                handle.write(item, item.relative_to(build))

    opener = _opener()
    _get(opener, url + "/")
    status, body = _post(opener, url + "/api/packs",
                         {"action": "copy", "path": str(archive)})
    assert status == 201, body[:300]
    extracted = sprite_composer.app_paths.packs_dir() / pack_name
    assert extracted.is_dir(), f"zip 应该被解压成目录，实际: {extracted}"
    assert any(extracted.rglob("*.pbd")), "解压后应能看到素材文件"


    status, body = _post(opener, url + "/api/packs",
                         {"action": "copy", "path": str(archive)})
    assert status == 400, body[:200]


    link_archive = tmp_path / f"{pack_name}-link.zip"
    link_archive.write_bytes(archive.read_bytes())
    status, body = _post(opener, url + "/api/packs",
                         {"action": "link", "path": str(link_archive)})
    assert status == 400, body[:200]
    payload = json.loads(body)
    assert "复制导入" in (payload.get("error") or ""), f"链接导入 zip 应给人话提示，实际: {payload}"


def test_zip_pack_helpers_are_wired(server):
    import inspect

    source = inspect.getsource(sprite_composer)
    assert "pack_import.extract_zip(" in source, "extract_zip 必须被路由真正调用"


def test_preview_missing_combination_returns_404(server):
    url = server
    opener = _opener()
    _get(opener, url + "/")
    for path in ("/api/preview", "/api/export"):
        status, body = _get(
            opener, f"{url}{path}?game=NOPE&character=x&body=y&face=z")
        assert status == 404, f"{path} 应回 404，实际 {status}: {body[:120]}"
        assert "没有这个组合" in json.loads(body)["error"]

    status, _body = _get(opener, f"{url}/api/preview?game=NOPE")
    assert status == 400


def test_log_writes_are_not_torn_by_concurrency(tmp_path):
    import re
    import threading
    from unittest.mock import patch

    import app_paths

    line_pattern = re.compile(
        r"^\[(startup|request) \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] T\d+-\d+$")

    with patch.object(sprite_composer.app_paths, "resolve_data_dir", return_value=tmp_path):
        def worker(index: int) -> None:
            for step in range(40):
                tag = "startup" if step % 2 else "request"
                sprite_composer._append_log_line(tag, f"T{index}-{step}")

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    log_path = tmp_path / app_paths.STARTUP_LOG_NAME
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 12 * 40, f"行数不对：{len(lines)}"
    torn = [line for line in lines if not line_pattern.match(line)]
    assert torn == [], f"出现被并发写坏的行：{torn[:3]}"


def test_library_orphans_scan_is_readonly_and_clean_only_touches_library(server, server_state):
    import os
    import time

    from PIL import Image, ImageDraw

    url = server
    library = sprite_composer.SpriteLibrary(
        server_state.output_root / sprite_composer.app_paths.LIBRARY_DIR_NAME)

    def _sprite(path):
        image = Image.new("RGBA", (400, 800), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((140, 150, 260, 600), fill=(200, 30, 30, 255))
        image.save(path)


    staging = sprite_composer.app_paths.resolve_data_dir() / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    good = staging / "正常.png"
    _sprite(good)
    library.import_image(good, "角色", "标签", game="作品")


    orphan_dir = library.images / "zz"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    orphan = orphan_dir / ("a" * 32 + ".png")
    _sprite(orphan)
    old = time.time() - 7200
    os.utime(orphan, (old, old))

    opener = _opener()
    _get(opener, url + "/")

    status, body = _post(opener, url + "/api/library/orphans", {"action": "scan"})
    assert status == 200, body[:200]
    payload = json.loads(body)
    assert payload["total"] >= 1, (
        f"payload={payload}  orphan.exists={orphan.exists()}  "
        f"lib_root={library.root}  images={library.images}  "
        f"direct={ {k: len(v) for k, v in library._collect_orphans().items()} }")
    assert orphan.exists(), "扫描阶段绝不能删文件"

    status, body = _post(opener, url + "/api/library/orphans", {"action": "clean"})
    assert status == 200, body[:200]
    assert json.loads(body)["removed"] >= 1
    assert not orphan.exists(), "确认后应被删除"
    assert library.list(False, limit=10)["total"] >= 1, "正常立绘不能被误删"


    status, _body = _post(opener, url + "/api/library/orphans", {"action": "nuke"})
    assert status == 400


def test_project_document_open_is_whitelisted(server, tmp_path, monkeypatch):
    url = server
    opener = _opener()
    _get(opener, url + "/")

    documents = tmp_path / 'application'
    documents.mkdir()
    for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md', 'README.md', 'NOTICE'):
        (documents / name).write_bytes((app_paths.project_root() / name).read_bytes())
    monkeypatch.setattr(app_paths, 'project_root', lambda: documents)


    opened: list[str] = []
    original_startfile = sprite_composer.os.startfile
    sprite_composer.os.startfile = lambda path: opened.append(str(path))
    try:
        #Windows 打开 LICENSE.txt 副本，避免无扩展名文件的关联提示。
        license_txt = app_paths.project_root() / "LICENSE.txt"
        created = False
        if not license_txt.exists():
            license_txt.write_bytes((app_paths.project_root() / "LICENSE").read_bytes())
            created = True
        try:
            for name in ("LICENSE", "LICENSE.txt", "THIRD_PARTY_NOTICES.md",
                         "README.md", "NOTICE"):
                before = len(opened)
                status, body = _post(opener, url + "/api/settings/open-folder",
                                     {"target": "app-file", "name": name})
                assert status == 200, f"{name} 应能打开：{status} {body[:200]}"
                assert len(opened) == before + 1, f"{name} 应触发一次打开动作"

                target = Path(opened[-1]).resolve()
                assert target == (app_paths.project_root() / name).resolve(), \
                    f"{name} 打开了错误的路径：{target}"


            for bad in ("../../sprite_composer.py", "..\\..\\sprite_composer.py",
                        "C:\\Windows\\win.ini", "sprite_composer.py", "",
                        "LICENSE/../ui/brand.json", "/etc/passwd", "ui/brand.json"):
                before = len(opened)
                status, body = _post(opener, url + "/api/settings/open-folder",
                                     {"target": "app-file", "name": bad})
                assert status == 400, \
                    f"{bad!r} 必须被白名单拒绝，实际 {status} {body[:120]}"
                assert len(opened) == before, f"{bad!r} 不该触发任何打开动作"
        finally:
            if created:
                license_txt.unlink(missing_ok=True)
    finally:
        sprite_composer.os.startfile = original_startfile


def test_removed_special_mode_is_rejected(server):
    opener = _opener()
    _get(opener, server + "/")
    for path in ("/api/library", "/api/preview", "/api/export"):
        status, body = _get(opener, f"{server}{path}?special=1")
        assert status == 403


@pytest.mark.parametrize("target", ["draft", "episode", None])
def test_project_folder_picker_accepts_independent_targets(server, tmp_path, monkeypatch, target):
    import app_settings
    calls = []
    picked = tmp_path / "selected-project-folder"
    picked.mkdir()
    def choose(title, initial):
        calls.append((title, initial))
        return str(picked)
    monkeypatch.setattr(app_settings, "browse_for_directory", choose)
    opener = _opener()
    _get(opener, server + "/")
    _, before = _get(opener, server + "/api/settings")
    status, body = _post(opener, server + "/api/settings/choose-folder", {"target": target, "initial": str(tmp_path)})
    assert status == 200 and json.loads(body)["path"] == str(picked)
    assert calls == [("选择剪映草稿目录" if target == "draft" else "选择文件夹", str(tmp_path))]
    _, after = _get(opener, server + "/api/settings")
    assert json.loads(before) == json.loads(after)


def test_draft_folder_picker_cancel_returns_empty_path(server, monkeypatch):
    import app_settings
    monkeypatch.setattr(app_settings, "browse_for_directory", lambda title, initial: "")
    opener = _opener()
    _get(opener, server + "/")
    status, body = _post(opener, server + "/api/settings/choose-folder", {"target": "draft"})
    assert status == 200 and json.loads(body)["path"] == ""


def test_native_file_picker_failure_is_reported(server, monkeypatch):
    import file_dialog
    def fail(*args, **kwargs):
        raise ValueError('选择的文件过多，请分批导入。')
    monkeypatch.setattr(file_dialog, 'browse_for_images', fail)
    opener=_opener();_get(opener,server+'/')
    status,body=_post(opener,server+'/api/audio/pick',{})
    assert status==400 and '文件过多' in json.loads(body)['error']


def test_native_folder_picker_failure_is_reported(server, monkeypatch):
    import app_settings
    def fail(*args, **kwargs):
        raise RuntimeError('系统文件夹选择框初始化失败。')
    monkeypatch.setattr(app_settings,'browse_for_directory',fail)
    opener=_opener();_get(opener,server+'/')
    status,body=_post(opener,server+'/api/settings/choose-folder',{'target':'draft'})
    assert status==500 and '初始化失败' in json.loads(body)['error']
