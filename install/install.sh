#!/bin/bash
# Chibitaru Installer - macOS / Linux

USB_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OS="$(uname -s)"
DEST="$HOME/chibitaru-agents"

echo ""
echo "========================================"
echo "  Chibitaru Installer ($OS)"
echo "========================================"
echo ""
echo "  1: Install Blue Triple Star (security monitor)"
echo "  2: Install chibitaru command (Linux Fish shell)"
echo "  0: Exit"
echo ""
read -p "Select > " CHOICE

mkdir -p "$DEST"

case $CHOICE in
  1)
    echo "[*] Installing Blue Triple Star to $DEST/aoko ..."
    cp -r "$USB_DIR/aoko" "$DEST/"
    echo "[OK] Done! Start with: bash $DEST/aoko/launch.sh"
    ;;
  2)
    FISH_DIR="$HOME/.config/fish/functions"
    mkdir -p "$FISH_DIR"
    cp "$USB_DIR/install/chibitaru.fish" "$FISH_DIR/chibitaru.fish"
    echo "[OK] chibitaru command installed!"
    echo "     Run: chibitaru"
    ;;
  0)
    echo "Bye!"
    ;;
  *)
    echo "Unknown option."
    ;;
esac

echo ""
echo "[OK] Done!"
