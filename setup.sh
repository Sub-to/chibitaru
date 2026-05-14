#!/bin/bash
# Chibitaru one-shot bash setup
# Run once: bash setup.sh
USB_DIR="$(cd "$(dirname "$0")" && pwd)"

cat >> ~/.bashrc << FUNC

function chibitaru() {
    local USB=""
    for P in "/media/\$USER/USB MEMORI/チビタル" "/run/media/\$USER/USB MEMORI/チビタル"; do
        [ -d "\$P" ] && USB="\$P" && break
    done
    [ -z "\$USB" ] && echo "USB not found" && return 1
    rm -rf /tmp/chibitaru_run
    cp -r "\$USB" /tmp/chibitaru_run
    bash /tmp/chibitaru_run/start.sh
}
FUNC

source ~/.bashrc
echo "[OK] Done! Run: chibitaru"
