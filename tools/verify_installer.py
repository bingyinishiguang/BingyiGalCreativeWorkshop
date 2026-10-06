#!/usr/bin/env python3
"""在独立临时目录安装并验证桌面入口，结束后卸载与清理测试进程。"""
from __future__ import annotations

import sys as _sys_boot

#输出统一用 UTF-8，避免 Windows 控制台编码无法表示某些字符。
#print 就会抛 UnicodeEncodeError 直接崩，用户只看到一闪而过的报错。
for _stream in (_sys_boot.stdout, _sys_boot.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import argparse
import http.cookiejar
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INSTALL_DIR = Path(tempfile.gettempdir()) / "bgw-verify-install"
REQUIRED_DOCS = ("LICENSE", "THIRD_PARTY_NOTICES.md", "README.md", "NOTICE")
REQUIRED_EXES = ("BingyiGalCreativeWorkshop.exe", "IceWingCompanion.exe")
#许可文件只接受白名单名称；Windows 使用 LICENSE.txt 副本。
REQUIRED_DOCS_WINDOWS = ("LICENSE.txt",)

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    """记录一条检查结果并立刻打印，让用户能实时看到卡在哪一步。"""
    results.append((bool(ok), label))
    mark = "  [OK]  " if ok else "  [FAIL]"
    line = f"{mark} {label}"
    if detail:
        line += f"  —— {detail}"
    print(line, flush=True)
    return bool(ok)


def info(label: str, detail: str = "") -> None:
    """只输出信息，不计入通过项。"""
    line = f"  [INFO] {label}"
    if detail:
        line += f"  —— {detail}"
    print(line, flush=True)


def powershell(command: str, timeout: int = 30) -> str:
    """执行 PowerShell 并以 UTF-8 读取输出，无法解码的字符用占位符替代。"""
    done = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace")
    return (done.stdout or "").strip()


def kill_test_processes(install_dir: Path) -> None:
    """只结束从本次测试安装目录启动的进程。"""
    escaped = str(install_dir).replace("'", "''")
    #只清理测试安装目录的程序及其持有 DLL 的子进程。
    powershell(
        f"$ownedRoot='{escaped}'+'\\'; 1..3 | ForEach-Object {{ "
        "Get-Process -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Path -and $_.Path.StartsWith($ownedRoot, 'OrdinalIgnoreCase') } | "
        "Stop-Process -Force -ErrorAction SilentlyContinue; Start-Sleep -Milliseconds 250 }", timeout=60)
    #Inference Python is a separate child, not one of the three app EXEs.
    powershell(
        f"$testRoot='{escaped}'; Get-CimInstance Win32_Process | Where-Object {{ "
        "$_.Name -eq 'python.exe' -and $_.ExecutablePath -and "
        "$_.ExecutablePath.StartsWith($testRoot+'\\', 'OrdinalIgnoreCase') -and "
        "$_.CommandLine -match 'api_v2\\.py' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }",timeout=30)


def kill_uninstallers(install_dir: Path) -> None:
    """Only stop uninstallers whose executable or command line names this test path."""
    target=str(install_dir.resolve()).replace("'", "''")
    powershell(
        f"$testTarget='{target}'; Get-CimInstance Win32_Process | Where-Object {{ "
        "$_.Name -in @('unins000.exe','unins001.exe','unins002.exe') -and "
        "(($_.ExecutablePath -and $_.ExecutablePath.StartsWith($testTarget+'\\', 'OrdinalIgnoreCase')) "
        "-or ($_.CommandLine -and $_.CommandLine.IndexOf($testTarget, 'OrdinalIgnoreCase') -ge 0)) "
        "} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }", timeout=30)


def listening_port(pid: int) -> int | None:
    value = powershell(
        f"(Get-NetTCPConnection -State Listen -OwningProcess {pid} "
        f"-ErrorAction SilentlyContinue | Select-Object -First 1).LocalPort")
    return int(value) if value.isdigit() else None


def process_count(name: str) -> int:
    value = powershell(f"(Get-Process -Name {name} -ErrorAction SilentlyContinue).Count")
    return int(value) if value.isdigit() else 0


def wait_gone(path: Path, seconds: int = 90) -> bool:
    """卸载器异步退出；等待释放目录后再清理测试文件。"""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not path.exists():
            return True
        time.sleep(2)
    return not path.exists()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="打包产物端到端验收（静默安装 -> 启动 -> 点关键按钮 -> 判定）")
    parser.add_argument("--installer", default=None,
                        help="指定安装包；默认取 dist 下最新的 *Setup*.exe")
    parser.add_argument("--dir", default=str(DEFAULT_INSTALL_DIR),
                        help="测试安装目录（用完会卸载）")
    parser.add_argument("--keep", action="store_true",
                        help="不清理安装目录与沙箱数据目录，便于现场排查")
    parser.add_argument("--wait", type=int, default=45,
                        help="等待程序起来的最长秒数（默认 45）")
    args = parser.parse_args()

    if args.installer:
        installer = Path(args.installer)
    else:
        candidates = sorted(
            (p for p in (ROOT / "dist").glob("*Setup*.exe")),
            key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            print("找不到安装包：dist 下没有 *Setup*.exe，先跑安装包制作.bat")
            return 1
        installer = candidates[0]

    install_dir = Path(args.dir).resolve()
    test_root=(ROOT/'工作数据'/'临时').resolve()
    if install_dir!=DEFAULT_INSTALL_DIR.resolve() and not (
            install_dir.is_relative_to(test_root) and install_dir.name.startswith('bgw-verify-')):
        raise ValueError('测试安装目录须位于工作数据/临时下并以 bgw-verify- 开头，或使用默认测试目录')
    #沙箱数据目录：只删这个，绝不碰真实的 %APPDATA%\BingyiGalCreativeWorkshop。
    sandbox_appdata = install_dir.parent / "bgw-verify-appdata"
    sandbox_data = sandbox_appdata / "BingyiGalCreativeWorkshop"

    print("=" * 68)
    print("  冰翼Gal创作工坊 —— 打包产物端到端验收")
    print("=" * 68)
    print(f"  安装包    : {installer}")
    if installer.is_file():
        print(f"  体积      : {installer.stat().st_size / 1024 / 1024:.1f} MB")
    print(f"  测试安装到: {install_dir}")
    print(f"  沙箱数据  : {sandbox_appdata}")
    print("  你真实的 %APPDATA%\\BingyiGalCreativeWorkshop 不会被读写。")
    print()

    if not check(installer.is_file(), "安装包存在"):
        return 1

    #干净起点：清掉上次残留的测试目录与测试进程
    kill_test_processes(install_dir)
    kill_uninstallers(install_dir)
    time.sleep(1)
    for path in (install_dir, sandbox_appdata):
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    main_proc: subprocess.Popen | None = None
    try:
        #静默安装
        print("[1/6] 静默安装")
        install_log = install_dir.parent / "installation.log"
        install_log.parent.mkdir(parents=True, exist_ok=True)
        done = subprocess.run(
            [str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOICONS", "/TASKS=",
             f"/DIR={install_dir}", f"/LOG={install_log}"],
            capture_output=True, text=True, timeout=900,
            encoding="utf-8", errors="replace")
        time.sleep(2)
        check(done.returncode == 0, "安装器退出码为 0", f"实际 {done.returncode}")

        #关键文件是否落地
        print("[2/6] 安装目录内容")
        exe = install_dir / "BingyiGalCreativeWorkshop.exe"
        if not check(exe.is_file(), "主程序已安装", str(exe)):
            print("\n安装没有成功，后面的检查无法继续。")
            return 1
        for name in REQUIRED_EXES:
            check((install_dir / name).is_file(), f"{name} 已安装")
        for name in REQUIRED_DOCS:
            target = install_dir / name
            size = f"{target.stat().st_size / 1024:.1f} KB" if target.is_file() else ""
            check(target.is_file(),
                  f"{name} 随安装包分发（使用许可与第三方声明）", size)
        for name in REQUIRED_DOCS_WINDOWS:
            target = install_dir / name
            ok = target.is_file() and target.stat().st_size > 0
            check(ok, f"{name} 已生成（避免『选择应用』弹框）",
                  f"{target.stat().st_size / 1024:.1f} KB" if ok else "缺失")

        #启动冻结版（APPDATA 指向沙箱）
        print("[3/6] 启动冻结版（数据目录已沙箱隔离）")
        sandbox_appdata.mkdir(parents=True, exist_ok=True)
        child_env = dict(os.environ)
        child_env["APPDATA"] = str(sandbox_appdata)
        main_proc = subprocess.Popen(
            [str(exe)], cwd=str(install_dir), env=child_env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"      PID={main_proc.pid}")
        port = None
        deadline = time.time() + args.wait
        while time.time() < deadline:
            time.sleep(1)
            if main_proc.poll() is not None:
                break
            port = listening_port(main_proc.pid)
            if port:
                break
        if not check(port is not None, "程序启动并开始监听本地端口",
                     f"127.0.0.1:{port}" if port else "超时或已退出"):
            return 1

        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        with opener.open(f"http://127.0.0.1:{port}/", timeout=20) as response:
            check(response.status == 200 and bool(response.read()),
                  "界面首页可正常返回")

        #冻结版读到的品牌配置
        print("[4/6] 冻结版读到的配置")
        brand = json.loads(opener.open(
            f"http://127.0.0.1:{port}/api/brand", timeout=20).read().decode("utf-8"))
        label = str(brand.get("versionLabel") or "").strip()
        check(bool(brand.get("version")), "读到版本号",
              f"{brand.get('version')} {label}".strip())
        beta = brand.get("beta") or {}
        if beta.get("configured"):
            state = "已过期" if beta.get("expired") else f"剩余 {beta.get('daysLeft')} 天"
            info("内测期限", f"{beta.get('deadline')}（{state}）")
        else:
            info("内测期限", "未配置（允许）")
        info("内测期限语义", "软提醒，不锁功能（有专门测试断言这一点）")

        #打开 LICENSE（关于页文档入口）
        print("[5/6] 打开随附的 LICENSE 文件")
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/settings/open-folder",
            #走界面真正点的那个名字：`LICENSE.txt`（有扩展名，不会弹"选择应用"）
            data=json.dumps({"target": "app-file", "name": "LICENSE.txt"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with opener.open(request, timeout=25) as response:
                opened = json.loads(response.read().decode("utf-8")).get("path", "")
            #验证安装目录内的真实文件，不能回退到源码目录。
            same_dir = Path(opened).parent.resolve() == install_dir.resolve()
            check(same_dir and Path(opened).is_file(),
                  "打开的是安装目录里的 LICENSE.txt", str(opened))
        except Exception as error:
            check(False, "打开 LICENSE.txt 失败", f"{type(error).__name__}: {error}")

        #点「冰翼取用精灵」（历史崩溃点）
        print("[6/6] 点「冰翼取用精灵」（这一步曾经让打包版直接崩）")
        before = process_count("IceWingCompanion")
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/picker/open",
            data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        try:
            with opener.open(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            check(response.status == 200 and bool(payload.get("ok")),
                  "/api/picker/open 返回成功", json.dumps(payload, ensure_ascii=False))
        except Exception as error:
            check(False, "/api/picker/open 请求失败", f"{type(error).__name__}: {error}")

        #观察 12 秒：桌宠若崩会立刻消失
        samples = [process_count("IceWingCompanion")]
        for _ in range(6):
            time.sleep(2)
            samples.append(process_count("IceWingCompanion"))
        print(f"      桌宠进程数（每 2 秒）: {samples}")
        check(max(samples) > 0, "桌宠进程真的起来了",
              f"点击前 {before}，之后 {samples}")

        #日志里不能出现那个具体的崩溃（从沙箱读，不读用户的）
        topmost = sandbox_data / "topmost.log"
        text = topmost.read_text(encoding="utf-8", errors="replace") if topmost.is_file() else ""
        check("PET_READY hwnd=" in text and "visible=True" in text
              and "PET_INIT_FAILED" not in text,
              "桌宠窗口完成加载并显示", text[-800:])
        check("UnboundLocalError" not in text, "日志里没有 UnboundLocalError")
        tray_lines = [line for line in text.splitlines() if "TRAY 已启动" in line]
        if tray_lines:
            info("托盘进程", tray_lines[-1][:110])
        else:
            info("托盘进程", "日志无记录（不判失败）")

        #主程序本身在这整段时间里也要活着
        check(main_proc.poll() is None, "主程序全程存活")

        #汇总
        failed = [label for ok, label in results if not ok]
        print()
        print("=" * 68)
        if failed:
            print(f"  结果：{len(results) - len(failed)}/{len(results)} 通过，"
                  f"{len(failed)} 项失败")
            for label in failed:
                print(f"    [FAIL] {label}")
            print("=" * 68)
            return 1
        print(f"  结果：全部 {len(results)} 项通过，安装器检查通过；剪映播放与保存重开仍须另验。")
        print("=" * 68)
        return 0
    finally:
        print()
        print("清理……")
        uninstall_failed = False
        if main_proc is not None:
            main_proc.terminate()
            try:
                main_proc.wait(timeout=10)
            except Exception:
                main_proc.kill()
        kill_test_processes(install_dir)
        uninstaller = install_dir / "unins000.exe"
        if uninstaller.is_file():
            #静默卸载，避免消息框阻塞测试。
            #kill_uninstallers(install_dir) 收尾，保证不会在用户屏幕上留下窗口。
            subprocess.run(
                [str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                capture_output=True, text=True, timeout=300,
                encoding="utf-8", errors="replace")
            #卸载器异步退出；等待释放目录后再清理测试文件。
            #必须等它真做完，否则会误报"已清理"却留着整个目录。
            gone = wait_gone(install_dir)
            if not gone:
                print(f"  [FAIL] 卸载后目录仍在：{install_dir}")
                results.append((False, "卸载后测试安装目录已清除"))
                uninstall_failed = True
        #收尾：结束卸载器（含 %TEMP% 里的副本），否则它会在屏幕上弹窗
        kill_uninstallers(install_dir)
        if args.keep:
            print(f"  --keep：保留 {install_dir} 与 {sandbox_appdata}")
        else:
            shutil.rmtree(install_dir, ignore_errors=True)
            shutil.rmtree(sandbox_appdata, ignore_errors=True)
            remaining = [str(p) for p in (install_dir, sandbox_appdata) if p.exists()]
            if remaining:
                print("  [FAIL] 仍有残留：" + "、".join(remaining))
                results.append((False, "测试残留已清除"))
                raise RuntimeError("测试清理失败，请查看残留路径")
            else:
                print("  已清理测试安装与沙箱数据目录（未触碰你的 %APPDATA%）")
        if uninstall_failed:
            raise RuntimeError('安装验证的卸载清理失败，不能报告整体通过')


if __name__ == "__main__":
    sys.exit(main())
