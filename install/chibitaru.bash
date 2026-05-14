# chibitaru - bash function for Linux
# Usage: Add to ~/.bashrc automatically via:
#   bash /path/to/chibitaru/setup.sh

function chibitaru() {
    local USB=""
    for P in "/media/$USER/USB MEMORI/チビタル" "/run/media/$USER/USB MEMORI/チビタル"; do
        [ -d "$P" ] && USB="$P" && break
    done
    [ -z "$USB" ] && echo "USB not found (is it plugged in?)" && return 1
    rm -rf /tmp/chibitaru_run
    cp -r "$USB" /tmp/chibitaru_run
    bash /tmp/chibitaru_run/start.sh
}
