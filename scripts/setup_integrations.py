"""Generate (and optionally install) MCP host configurations.

The compiled server speaks the standard MCP stdio protocol, so the same
``mcpServers`` entry works in LM Studio, Jan, Claude Desktop, Cursor, Cline,
Continue, ollmcp and any other MCP-aware host.

Examples::

    uv run python scripts/setup_integrations.py
    uv run python scripts/setup_integrations.py --apply
    uv run python scripts/setup_integrations.py --mode python --apply

``--apply`` merges the entry into LM Studio, Jan and ollmcp user configs
(creating timestamped backups first) and leaves every other server untouched.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
DEFAULT_EXE = HERE / "dist" / "paper-analyzer-mcp.exe"
DEFAULT_PYTHON = HERE / ".venv" / "Scripts" / "python.exe"
DEFAULT_PAPERS = HERE / "papers"
DEFAULT_EXPORTS = HERE / "exports"


def _server_entry(
    mode: str,
    papers_dir: Path,
    exports_dir: Path,
    jan: bool = False,
) -> dict:
    if mode == "exe":
        command = str(DEFAULT_EXE)
        args: list[str] = []
    else:
        command = str(DEFAULT_PYTHON)
        args = [str(HERE / "paper_analyzer.py")]

    entry: dict = {
        "command": command,
        "args": args,
        "env": {
            "PAPERS_DIR": str(papers_dir),
            "EXPORTS_DIR": str(exports_dir),
            "PAPER_ANALYZER_LOG_LEVEL": "INFO",
            "PYTHONIOENCODING": "utf-8",
            # Belt and braces if a host launches the Python entry point:
            "FASTMCP_SHOW_SERVER_BANNER": "false",
            "FASTMCP_CHECK_FOR_UPDATES": "off",
        },
    }
    if jan:
        entry["active"] = True
    return entry


def _jan_config_path() -> Path | None:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        return Path(appdata) / "Jan" / "data" / "mcp_config.json" if appdata else None
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Jan" / "data" / "mcp_config.json"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "Jan" / "data" / "mcp_config.json"


def _lmstudio_config_path() -> Path:
    return Path.home() / ".lmstudio" / "mcp.json"


def _ollmcp_config_path() -> Path:
    """ollmcp stores user-scope servers in ~/.config/ollmcp/mcp.json."""
    return Path.home() / ".config" / "ollmcp" / "mcp.json"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _merge_server(path: Path, name: str, entry: dict) -> None:
    """Merge *entry* into the host config, preserving everything else."""
    if path.exists():
        raw = path.read_text(encoding="utf-8-sig")
        try:
            data = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Cannot parse {path}: {exc}. Fix or remove it first.") from exc

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_suffix(path.suffix + f".bak-{stamp}")
        shutil.copy2(path, backup)
        print(f"  backup: {backup}")
    else:
        data = {}

    servers = data.setdefault("mcpServers", {})
    servers[name] = entry
    _write_json(path, data)
    print(f"  wrote : {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["auto", "exe", "python"],
        default="auto",
        help="Use the compiled .exe (default when present) or the project venv.",
    )
    parser.add_argument("--papers-dir", type=Path, default=DEFAULT_PAPERS)
    parser.add_argument("--exports-dir", type=Path, default=DEFAULT_EXPORTS)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Merge the entry into LM Studio, Jan and ollmcp configs (with backups).",
    )
    parser.add_argument("--name", default="paper-analyzer")
    args = parser.parse_args()

    mode = args.mode
    if mode == "auto":
        mode = "exe" if DEFAULT_EXE.is_file() else "python"

    if mode == "exe" and not DEFAULT_EXE.is_file():
        print(f"Executable not found: {DEFAULT_EXE}\nRun scripts/build_exe.ps1 first.", file=sys.stderr)
        return 2
    if mode == "python" and not DEFAULT_PYTHON.is_file():
        print(f"Virtualenv not found: {DEFAULT_PYTHON}\nRun: uv sync", file=sys.stderr)
        return 2

    papers_dir = args.papers_dir.resolve()
    exports_dir = args.exports_dir.resolve()
    papers_dir.mkdir(parents=True, exist_ok=True)
    exports_dir.mkdir(parents=True, exist_ok=True)

    entry = _server_entry(mode, papers_dir, exports_dir)
    jan_entry = _server_entry(mode, papers_dir, exports_dir, jan=True)

    out_dir = HERE / "dist" / "configs"
    _write_json(out_dir / "lmstudio-mcp.json", {"mcpServers": {args.name: entry}})
    _write_json(out_dir / "claude-desktop-config.json", {"mcpServers": {args.name: entry}})
    _write_json(out_dir / "generic-mcp.json", {"mcpServers": {args.name: entry}})
    _write_json(out_dir / "ollmcp-servers.json", {"mcpServers": {args.name: entry}})
    _write_json(out_dir / "jan-mcp_config.json", {"mcpServers": {args.name: jan_entry}})

    print(f"Mode          : {mode}")
    print(f"Server command: {entry['command']} {' '.join(entry['args'])}".rstrip())
    print(f"Papers dir    : {papers_dir}")
    print(f"Exports dir   : {exports_dir}")
    print(f"Configs       : {out_dir}")

    if args.apply:
        print("\nInstalling host configurations:")
        lmstudio = _lmstudio_config_path()
        if lmstudio.parent.is_dir():
            _merge_server(lmstudio, args.name, entry)
        else:
            print(f"  skip  : LM Studio not found ({lmstudio.parent})")

        jan = _jan_config_path()
        if jan is not None and jan.parent.is_dir():
            _merge_server(jan, args.name, jan_entry)
        else:
            print(f"  skip  : Jan not found ({jan})")

        ollmcp = _ollmcp_config_path()
        if ollmcp.parent.is_dir():
            _merge_server(ollmcp, args.name, entry)
        else:
            print(f"  skip  : ollmcp not installed ({ollmcp.parent})")

    print("\nHost setup:")
    print("  LM Studio : Program tab > Install > Edit mcp.json (or restart the app)")
    print("  Jan       : Settings > MCP Servers > restart Jan")
    print("  Ollama    : run scripts\\run_ollama_mcp.ps1 (uses ollmcp as the MCP host)")
    print("  Others    : copy dist/configs/generic-mcp.json into the host's mcpServers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
