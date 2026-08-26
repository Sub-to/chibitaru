#!/bin/bash
# Chibitaru Installer - macOS / Linux

set -u

USB_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OS="$(uname -s)"
DEST="$HOME/chibitaru-agents"

echo ""
echo "========================================"
echo "  Chibitaru Installer ($OS)"
echo "========================================"
echo ""
echo "  1: Install Blue Triple Star (security monitor)"
echo "  2: Install 'chibitaru' shell command"
echo "  3: Install lightweight autostart (Linux / no LLM)"
echo "  0: Exit"
echo ""
read -p "Select > " CHOICE

case $CHOICE in
  1)
    mkdir -p "$DEST"
    echo "[*] Installing Blue Triple Star to $DEST/aoko ..."
    cp -r "$USB_DIR/aoko" "$DEST/"
    echo "[OK] Done!"
    echo "     Lightweight (no model needed): CHIBITARU_ENGINE=auto python3 $DEST/aoko/monitor.py"
    echo "     LLM version                  : bash $DEST/aoko/launch.sh"
    ;;

  2)
    # ログインシェルを見て bash / fish を選ぶ
    if [ -n "${SHELL:-}" ] && [ "$(basename "$SHELL")" = "fish" ]; then
        FISH_DIR="$HOME/.config/fish/functions"
        mkdir -p "$FISH_DIR"
        cat > "$FISH_DIR/chibitaru.fish" << FISHEOF
function chibitaru
    set -l RUN (test -n "\$TMPDIR"; and echo \$TMPDIR; or echo /tmp)/chibitaru_run
    rm -rf \$RUN
    cp -r "$USB_DIR" \$RUN
    bash \$RUN/start.sh
end
FISHEOF
        echo "[OK] fish function installed: $FISH_DIR/chibitaru.fish"
        echo "     Run: chibitaru"
    else
        bash "$USB_DIR/setup.sh"
    fi
    ;;

  3)
    if [ "$OS" != "Linux" ]; then
        echo "[!] Lightweight autostart is Linux only."
        exit 1
    fi
    UNIT_DIR="$HOME/.config/systemd/user"
    if command -v systemctl >/dev/null 2>&1; then
        mkdir -p "$UNIT_DIR"
        cat > "$UNIT_DIR/chibitaru-lite.service" << UNITEOF
[Unit]
Description=Chibitaru lightweight security monitor (MYLN-FRAME, no LLM)
After=default.target

[Service]
Type=simple
Environment=CHIBITARU_ENGINE=auto
ExecStart=/usr/bin/env python3 $USB_DIR/aoko/monitor.py
Restart=on-failure
RestartSec=30

[Install]
WantedBy=default.target
UNITEOF
        echo "[OK] Unit written: $UNIT_DIR/chibitaru-lite.service"
        echo "     Enable: systemctl --user daemon-reload && systemctl --user enable --now chibitaru-lite"
        echo "     Logs  : journalctl --user -u chibitaru-lite -f"
    else
        echo "[!] systemd not found. Use cron instead — add this line to 'crontab -e':"
        echo ""
        echo "    */5 * * * * CHIBITARU_ENGINE=auto python3 $USB_DIR/aoko/monitor.py --once >> /tmp/chibitaru.log 2>&1"
        echo ""
    fi
    ;;

  0)
    echo "Bye!"
    ;;
  *)
    echo "Unknown option."
    ;;
esac
