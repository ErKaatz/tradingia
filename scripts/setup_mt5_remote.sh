#!/usr/bin/env bash
# setup_mt5_remote.sh -- interactively creates ~/.config/tradingia/mt5.env
# with 0600 permissions. Never echoes the token, never leaves it in shell
# history (this script is invoked by path, not typed with the token inline).
set -euo pipefail

CONFIG_DIR="$HOME/.config/tradingia"
CONFIG_FILE="$CONFIG_DIR/mt5.env"

mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"

if [ -f "$CONFIG_FILE" ]; then
    echo "A config file already exists at: $CONFIG_FILE"
    read -r -p "Overwrite it? [y/N] " reply
    case "$reply" in
        [yY]|[yY][eE][sS]) ;;
        *)
            echo "Aborted -- left existing file untouched."
            exit 0
            ;;
    esac
fi

echo "MT5 bridge connection setup"
echo "----------------------------"
read -r -p "MT5_REMOTE_URL (e.g. http://192.168.1.50:8765): " remote_url
# Defensive cleanup: a pasted value from some terminals/clipboards can carry
# a trailing \r (CRLF) or surrounding whitespace; strip it rather than
# writing a subtly-broken URL/token to the config file.
remote_url="${remote_url%$'\r'}"
remote_url="$(echo -n "$remote_url" | tr -d '[:space:]')"
if [ -z "$remote_url" ]; then
    echo "setup_mt5_remote.sh: MT5_REMOTE_URL cannot be empty -- aborting." >&2
    exit 1
fi
if [[ ! "$remote_url" =~ ^https?:// ]]; then
    echo "setup_mt5_remote.sh: no http:// or https:// scheme given; assuming http://" >&2
    remote_url="http://$remote_url"
fi
if [[ ! "$remote_url" =~ ^https?://[^/[:space:]]+ ]]; then
    echo "setup_mt5_remote.sh: '$remote_url' does not look like a valid URL (scheme://host[:port]) -- aborting." >&2
    exit 1
fi

# Read the token one character at a time so we can echo '*' per character
# (never the character itself) -- plain `read -s` gives zero visual
# feedback, which makes it impossible to tell a paste actually went through
# or whether it got duplicated/mangled. The token itself is still never
# displayed or logged.
echo -n "MT5_REMOTE_TOKEN (must match the VM's MT5_BRIDGE_TOKEN; typing/paste shown as *): "
remote_token=""
while IFS= read -r -s -n 1 char; do
    # Enter ends input (read -n 1 returns an empty $char on Enter).
    if [ -z "$char" ]; then
        break
    fi
    # Backspace/DEL support so a mis-paste can be corrected without
    # aborting the whole script.
    if [[ "$char" == $'\x7f' || "$char" == $'\x08' ]]; then
        if [ -n "$remote_token" ]; then
            remote_token="${remote_token%?}"
            printf '\b \b'
        fi
        continue
    fi
    remote_token+="$char"
    printf '*'
done
echo
remote_token="${remote_token%$'\r'}"
remote_token="$(printf '%s' "$remote_token" | tr -d '[:space:]')"
if [ -z "$remote_token" ]; then
    echo "setup_mt5_remote.sh: MT5_REMOTE_TOKEN cannot be empty -- aborting." >&2
    exit 1
fi
echo "  (${#remote_token} characters read)"

umask 077
{
    echo "MT5_REMOTE_URL=$remote_url"
    echo "MT5_REMOTE_TOKEN=$remote_token"
} > "$CONFIG_FILE"
chmod 600 "$CONFIG_FILE"

unset remote_token

echo
echo "Wrote $CONFIG_FILE (permissions 600)."
echo "Token not shown. Test with: tia mt5 status"
