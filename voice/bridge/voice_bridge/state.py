"""Keep user state outside the installed package and migrate legacy files."""
import os
from pathlib import Path
import sys
import tempfile
from .log import log

FILES = ("token", "host")


def directory():
    override = os.environ.get("PASSPORT_VOICE_STATE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/passport-voice"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "passport-voice"


def legacy_directory():
    bridge = Path(__file__).resolve().parents[1]
    return bridge.parent / ".local" if (bridge / "pyproject.toml").is_file() else None


def migrate(destination, source):
    """Copy known files without overwriting data. Keep the originals as backups."""
    if source is None or source.resolve() == destination.resolve():
        return
    pending = []
    for name in FILES:
        old, new = source / name, destination / name
        if not old.exists():
            continue
        data = old.read_bytes()
        if name == "token":
            token = data.decode().strip()
            if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
                raise ValueError(f"Invalid legacy token: {old}; state was not migrated")
        if new.exists():
            if name == "token" and new.read_bytes().strip() != data.strip():
                raise RuntimeError(f"State conflict: {old} and {new}; neither file was overwritten")
            # The current cache can change after DHCP or a successful connection.
            # It must not make a later setup fail or revert to an old address.
        else:
            pending.append((new, data))
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    for new, data in pending:
        # Publish a complete file without replacing a concurrent writer's file.
        with tempfile.NamedTemporaryFile(dir=destination, delete=False) as output:
            temporary = Path(output.name)
            try:
                output.write(data)
                output.flush()
                os.link(temporary, new)
            finally:
                temporary.unlink(missing_ok=True)
        log(f"Copied {source / new.name} to {new}; original retained")
