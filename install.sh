#!/bin/sh
set -eu
CAF_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ ! -x "$CAF_ROOT/.venv/bin/python" ]; then
    if ! command -v uv >/dev/null 2>&1; then
        printf 'caf: install uv first: brew install uv\n' >&2
        exit 1
    fi
    uv sync --project "$CAF_ROOT" --locked --no-dev --quiet
fi
"$CAF_ROOT/.venv/bin/python" - "$CAF_ROOT" <<'PY'
from datetime import datetime
from pathlib import Path
import shlex
import shutil
import sys
import os
root=Path(sys.argv[1])
target=Path.home()/'.local/bin/caf'
script='#!/bin/sh\nexec '+shlex.quote(str(root/'caf'))+' "$@"\n'
if target.exists() and not target.is_symlink() and target.read_bytes()==script.encode():
    print('caf is already installed.')
    raise SystemExit
if target.exists() or target.is_symlink():
    backup=root/'.backups'/('caf-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(target,backup,follow_symlinks=True)
    print('Previous caf saved to',backup)
target.parent.mkdir(parents=True,exist_ok=True)
if target.is_symlink():target.unlink()
target.write_text(script)
target.chmod(0o755)
print('Installed. Run caf in Ghostty. Keep this checkout in place.')
if str(target.parent) not in os.environ.get('PATH', '').split(os.pathsep):
    print('Add this to your shell profile: export PATH="$HOME/.local/bin:$PATH"')
PY
