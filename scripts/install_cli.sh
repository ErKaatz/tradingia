#!/usr/bin/env bash
# install_cli.sh -- installs the `tia` command for the current user by
# symlinking ~/.local/bin/tia -> <repo>/scripts/tia. A symlink (not a copy)
# means `git pull` updates to scripts/tia take effect immediately, with no
# reinstall step.
set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
    DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd -P "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"
TIA_SCRIPT="$REPO_ROOT/scripts/tia"
BIN_DIR="$HOME/.local/bin"
TARGET="$BIN_DIR/tia"

if [ ! -f "$TIA_SCRIPT" ]; then
    echo "install_cli.sh: expected $TIA_SCRIPT to exist -- aborting." >&2
    exit 1
fi

if [ ! -x "$TIA_SCRIPT" ]; then
    echo "install_cli.sh: $TIA_SCRIPT is not executable; fixing (chmod +x)." >&2
    chmod +x "$TIA_SCRIPT"
fi

mkdir -p "$BIN_DIR"

if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
    if [ -L "$TARGET" ] && [ "$(readlink "$TARGET")" = "$TIA_SCRIPT" ]; then
        echo "install_cli.sh: $TARGET already points to $TIA_SCRIPT -- nothing to do."
    else
        echo "install_cli.sh: $TARGET already exists and is not the expected symlink." >&2
        echo "  Current target: $(readlink "$TARGET" 2>/dev/null || echo '(not a symlink -- a real file)')" >&2
        read -r -p "Overwrite it with a symlink to $TIA_SCRIPT? [y/N] " reply
        case "$reply" in
            [yY]|[yY][eE][sS])
                rm -f "$TARGET"
                ln -s "$TIA_SCRIPT" "$TARGET"
                echo "install_cli.sh: replaced $TARGET with a symlink to $TIA_SCRIPT."
                ;;
            *)
                echo "install_cli.sh: aborted -- left $TARGET untouched." >&2
                exit 1
                ;;
        esac
    fi
else
    ln -s "$TIA_SCRIPT" "$TARGET"
    echo "install_cli.sh: created $TARGET -> $TIA_SCRIPT."
fi

case ":$PATH:" in
    *":$BIN_DIR:"*)
        echo "install_cli.sh: $BIN_DIR is already in your PATH."
        ;;
    *)
        echo
        echo "WARNING: $BIN_DIR is not in your PATH."
        echo "Add it yourself (this script will not modify your shell config), e.g.:"
        echo
        echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc"
        echo "  source ~/.bashrc"
        echo
        echo "(or the equivalent for your shell's rc file, e.g. ~/.zshrc)."
        ;;
esac

echo
echo "Installed. Next: ./scripts/setup_mt5_remote.sh to configure MT5 connection, then try: tia mt5 status"
