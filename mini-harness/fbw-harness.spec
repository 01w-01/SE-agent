# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller configuration for the Windows x64 single-file CLI."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


hiddenimports = collect_submodules("keyring.backends.Windows") + collect_submodules("pytest")
entrypoint = Path(workpath) / "fbw_harness_entry.py"
entrypoint.parent.mkdir(parents=True, exist_ok=True)
entrypoint.write_text(
    "import sys\n"
    "if sys.argv[1:3] == ['-m', 'pytest']:\n"
    "    import pytest\n"
    "    raise SystemExit(pytest.main(sys.argv[3:]))\n"
    "from fbw_harness.cli import main\n"
    "raise SystemExit(main())\n",
    encoding="utf-8",
)
runtime_hook = Path(workpath) / "fbw_harness_demo_data.py"
runtime_hook.write_text(
    "from pathlib import Path\nimport sys\nfrom fbw_harness import demos\n"
    "demos._FIXTURE_ROOT = Path(sys._MEIPASS) / 'fixtures'\n",
    encoding="utf-8",
)
fixture_root = Path(SPECPATH) / "tests" / "fixtures" / "clamp_project"

a = Analysis(
    [str(entrypoint)],
    pathex=[str(Path(SPECPATH) / "src")],
    binaries=[],
    datas=[
        (str(fixture_root / "clamp.py"), "fixtures"),
        (str(fixture_root / "test_clamp.py"), "fixtures"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(runtime_hook)],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="fbw-harness",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
