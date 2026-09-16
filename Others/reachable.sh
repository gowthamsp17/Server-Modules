#!/bin/bash

CSV="CT1-server-IP-details.csv"
OUTPUT="unreachable_ips.txt"
PARALLEL_JOBS=50

> "$OUTPUT"

check_ip() {
    local IP="$1"
    [[ -z "$IP" ]] && return

    if ping -c 1 -W 1 "$IP" &>/dev/null; then
        echo "  [OK]          $IP is reachable" >&2
        return
    fi

    echo "  [UNREACHABLE] $IP is NOT reachable" >&2
    echo "$IP"
}

export -f check_ip

echo "Checking $(cut -d',' -f1 "$CSV" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | grep -v '^$' | sort -u | wc -l) unique IPs with $PARALLEL_JOBS parallel jobs..."
echo

# Extract IPs (first CSV field), trim whitespace, drop blanks/duplicates
cut -d',' -f1 "$CSV" \
    | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' \
    | grep -v '^$' \
    | sort -u \
    | xargs -P "$PARALLEL_JOBS" -I{} bash -c 'check_ip "$@"' _ {} \
    >> "$OUTPUT"

sort -u "$OUTPUT" -o "$OUTPUT"

echo
echo "========================================"
echo "UNREACHABLE IPs"
echo "========================================"
cat "$OUTPUT"

echo
echo "Total unreachable: $(wc -l < "$OUTPUT")"
echo "Output saved to: $OUTPUT"
