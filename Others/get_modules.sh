#!/bin/bash

CSV="CT1-server-IP-details.csv"
UNREACHABLE="unreachable_ips.txt"

USER="patcher"

# Prompt for passwords at runtime (not hardcoded). Enter one per line,
# leave empty and press Enter to finish.
PASSWORDS=()
echo "Enter password(s) to try for SSH login (press Enter on empty line to stop):"
while true; do
    read -r -s -p "Password $(( ${#PASSWORDS[@]} + 1 )): " pw
    echo
    [[ -z "$pw" ]] && break
    PASSWORDS+=("$pw")
done

if [[ ${#PASSWORDS[@]} -eq 0 ]]; then
    echo "No passwords provided. Exiting."
    exit 1
fi

OUTPUT="all_modules.txt"
TIMEOUT_FILE="timeout_ip.txt"
EXPIRED_PASSWORD_FILE="password_expired_ips.txt"
PROXY_ERROR_FILE="proxy_error_ips.txt"

# Clear output
> "$OUTPUT"
> "$TIMEOUT_FILE"
> "$EXPIRED_PASSWORD_FILE"
> "$PROXY_ERROR_FILE"

finalize() {
    sort -u "$OUTPUT" -o "$OUTPUT"
    sort -u "$TIMEOUT_FILE" -o "$TIMEOUT_FILE"
    sort -u "$EXPIRED_PASSWORD_FILE" -o "$EXPIRED_PASSWORD_FILE"
    sort -u "$PROXY_ERROR_FILE" -o "$PROXY_ERROR_FILE"
}
trap finalize EXIT INT TERM

while IFS=',' read -r IP TYPE OS
do
    IP=$(echo "$IP" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    OS=$(echo "$OS" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

    # Skip empty lines
    [[ -z "$IP" ]] && continue

    # Process ONLY Debian machines
    [[ "$OS" != Debian* ]] && continue

    # Skip IPs already known to be unreachable
    if [[ -f "$UNREACHABLE" ]] && grep -qxF "$IP" "$UNREACHABLE"; then
        echo "Skipping $IP (in $UNREACHABLE)"
        continue
    fi

    echo "Checking $IP..."

    # Check whether SSH port is reachable
    if ! timeout 2 bash -c "</dev/tcp/$IP/22" 2>/dev/null; then
        echo "  SSH port 22 is DOWN/UNREACHABLE"
        continue
    fi

    echo "  SSH port is reachable"

    # Try both passwords within a single combined 3s budget
    try_ssh() {
        local pass="$1"
        sshpass -p "$pass" ssh -n \
            -o StrictHostKeyChecking=no \
            -o ConnectTimeout=3 \
            -o ConnectionAttempts=1 \
            "$USER@$IP" \
            'lsmod | awk "NR > 1 {print \$1}"' 2>/dev/null
    }
    export -f try_ssh
    export USER IP

    SSH_ERR=$(mktemp)
    MODULES=$(timeout 3 bash -c '
        for pw in "$@"; do
            try_ssh "$pw" && exit 0
        done
        exit 1
    ' _ "${PASSWORDS[@]}" 2>"$SSH_ERR")

    STATUS=$?
    ERR_OUTPUT=$(<"$SSH_ERR")
    rm -f "$SSH_ERR"

    if echo "$ERR_OUTPUT" | grep -qi "password has expired\|password is expired\|Current password:\|change your password"; then
        echo "  Password expired, skipping"
        echo "$IP" >> "$EXPIRED_PASSWORD_FILE"
        continue
    fi

    if echo "$ERR_OUTPUT" | grep -qi "Proxy error\|nc: "; then
        echo "  Proxy error, skipping"
        echo "$IP" >> "$PROXY_ERROR_FILE"
        continue
    fi

    if [[ $STATUS -eq 124 ]]; then
        echo "  SSH timed out (>3s), skipping"
        echo "$IP" >> "$TIMEOUT_FILE"
        continue
    fi

    if [[ $STATUS -ne 0 ]]; then
        echo "  LOGIN FAILED"
        continue
    fi

    if [[ -z "$MODULES" ]]; then
        echo "  No modules returned"
        continue
    fi

    echo "  SUCCESS"

    # Merge new modules into the output, keeping it deduplicated (not a raw append)
    { cat "$OUTPUT" 2>/dev/null; echo "$MODULES"; } | sort -u > "$OUTPUT.tmp" && mv "$OUTPUT.tmp" "$OUTPUT"

done < "$CSV"

# Create unique union (also runs via trap on exit/interrupt)
finalize

echo
echo "========================================"
echo "UNIQUE MODULES - DEBIAN SERVERS"
echo "========================================"

cat "$OUTPUT"

echo
echo "Total unique modules: $(wc -l < "$OUTPUT")"
echo "Output saved to: $OUTPUT"
