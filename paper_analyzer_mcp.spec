# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for paper-analyzer-mcp.

Build with::

    uv run pyinstaller --noconfirm --clean paper_analyzer_mcp.spec

Produces ``dist/paper-analyzer-mcp.exe`` (Windows) or the equivalent
binary for the current platform. The result is a self-contained MCP
server: no Python/uv installation is required on the target machine.
"""

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

# Quality-assessment frameworks are read from disk at runtime
# (services/quality_assessor.py resolves them relative to the package).
datas = [("checklists", "checklists")]

# python-docx ships its default template and XML parts that are loaded at
# runtime; pdfminer.six ships the CMap tables needed for non-Latin PDFs.
datas += collect_data_files("docx")
datas += collect_data_files("pdfminer")

# FastMCP/MCP read their own package metadata at import time.
datas += copy_metadata("fastmcp")
datas += copy_metadata("mcp")

hiddenimports = [
    "config",
    "models",
    "models.domain_patterns",
    "models.schemas",
    "services",
    "services.bibliometric_engine",
    "services.cross_paper_analyzer",
    "services.document_exporter",
    "services.keyword_searcher",
    "services.metadata_extractor",
    "services.paper_scanner",
    "services.path_utils",
    "services.pdf_extractor",
    "services.quality_assessor",
    "services.reference_parser",
    "services.section_detector",
    "services.study_data_extractor",
    "docx",
    "pdfplumber",
    "pdfminer",
    "pdfminer.high_level",
]

a = Analysis(
    ["paper_analyzer.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "pandas",
        "numpy",
        "IPython",
        "pytest",
        "reportlab",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="paper-analyzer-mcp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
