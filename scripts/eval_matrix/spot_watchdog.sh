#!/usr/bin/env bash
# Local watchdog for a Spot matrix VM: on preemption, restart it (retrying on
# capacity errors), bring the vLLM replicas back, and resume the matrix.
# Prints one line per event; exits when the matrix reports MATRIX_DONE.
#   spot_watchdog.sh VM ZONE [PROJECT] [POLL_SECONDS]
set -u
V=$1; Z=$2; P=${3:-ai-coe-454404}; POLL=${4:-120}
log() { echo "$(date -u +%FT%TZ) $*"; }
status() { gcloud compute instances describe "$V" --project "$P" --zone "$Z" --format='value(status)' 2>/dev/null; }
rssh() { gcloud compute ssh "$V" --project "$P" --zone "$Z" --quiet --command "$1" 2>/dev/null; }

recover() {
  log "PREEMPTED status=$(status); waiting for TERMINATED"
  until [ "$(status)" = "TERMINATED" ]; do sleep 15; done
  local a=0
  while :; do
    a=$((a+1))
    if gcloud compute instances start "$V" --project "$P" --zone "$Z" >/dev/null 2>&1; then
      log "RESTARTED after $a attempt(s)"; break
    fi
    [ $a -ge 60 ] && { log "RESTART_FAILED after $a attempts"; return 1; }
    sleep 60
  done
  until rssh true; do sleep 15; done
  log "SSH_READY; starting replicas"
  rssh 'timeout 1200 bash ~/matrix/remote_bootstrap.sh serve >/dev/null 2>&1 && bash ~/matrix/remote_bootstrap.sh resume' \
    && log "RESUMED" || log "RESUME_FAILED"
}

while :; do
  st=$(status)
  case "$st" in
    RUNNING)
      if rssh 'grep -q MATRIX_DONE ~/matrix/matrix_s1.log 2>/dev/null'; then
        log "MATRIX_DONE $(rssh 'tail -1 ~/matrix/out/progress.log' | cut -c1-200)"; exit 0
      fi
      ;;
    STOPPING|TERMINATED|STAGING|PROVISIONING)
      recover || exit 1 ;;
    "") log "STATUS_UNKNOWN (describe failed)";;
    *) log "STATUS_$st";;
  esac
  sleep "$POLL"
done
