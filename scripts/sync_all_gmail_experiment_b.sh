#!/bin/bash
# Loop completo de sync-batch contra experiment-B hasta terminar inbox.
# Reutiliza cursor_token entre iteraciones; para cuando has_more=false.

set -u
BACKEND="http://localhost:8001"
BATCH=100
SLEEP=2
LOG="/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026/tutelas-app/logs/sync_all_gmail_b.jsonl"
SUMMARY="/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026/tutelas-app/logs/sync_all_gmail_b.md"

cursor=""
iter=0
start_ts=$(date +%s)

echo "# Sync-all experiment-B — inicio $(date -Iseconds)" > "$SUMMARY"
echo "" > "$LOG"

while true; do
    iter=$((iter+1))
    if [ -z "$cursor" ]; then
        body="{\"batch_size\":$BATCH,\"read_only\":true}"
    else
        body="{\"batch_size\":$BATCH,\"read_only\":true,\"resume_cursor\":\"$cursor\"}"
    fi

    resp=$(curl -s --max-time 900 -X POST "$BACKEND/api/emails/sync-batch" \
           -H "Content-Type: application/json" -d "$body")
    ec=$?
    if [ $ec -ne 0 ] || [ -z "$resp" ]; then
        echo "[iter $iter] ERROR curl ec=$ec resp=$resp" | tee -a "$SUMMARY"
        break
    fi

    echo "$resp" >> "$LOG"

    has_more=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('has_more',False))")
    cursor=$(echo "$resp"  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('cursor_token') or '')")
    line=$(echo "$resp" | python3 -c "
import sys, json
d = json.load(sys.stdin)
b = d['batch']
c = d['cumulative']
print(f\"iter={$iter} in={b['emails_in_batch']} AUTO={b['AUTO_MATCH']} DUP={b['DUPLICATE_GMAIL']} NEW={b['NEW_CASE']} Q={b['QUARANTINE']} IGN={b['IGNORED']} ERR={b['ERROR']} elapsed={b['elapsed_seconds']}s cum={c['total_processed']}\")
")
    echo "[$(date +%H:%M:%S)] $line"
    echo "- $line" >> "$SUMMARY"

    if [ "$has_more" != "True" ]; then
        echo "[$(date +%H:%M:%S)] has_more=false — FIN"
        echo "" >> "$SUMMARY"
        echo "FIN $(date -Iseconds) — iters=$iter elapsed=$(( $(date +%s) - start_ts ))s" >> "$SUMMARY"
        break
    fi

    sleep $SLEEP
done
