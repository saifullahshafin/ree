#!/bin/bash
# Run sound.py then sfx_events.py for each video, one at a time, each inside a hard memory cap so a runaway
# job is killed by its own cgroup instead of freezing a shared VM (the first pack froze a no-swap VM twice).
#   ./run_sound_safe.sh <job_dir> <venv_python> <id> [<id> ...]
# job_dir holds full/<id>.m4a, out/<id>/transcript.json, events/<id>.json, sound.py, sfx_events.py
set -u
JOB=$1; PY=$2; shift 2
cd "$JOB" || exit 1
CAP=${MEMORY_MAX:-6G}
run() { sudo -n systemd-run --quiet --scope -p MemoryMax="$CAP" -p MemorySwapMax=0 --uid="$(id -u)" --gid="$(id -g)" \
          --setenv=TORCH_HOME="$TORCH_HOME" --setenv=DEMUCS_THREADS="${DEMUCS_THREADS:-3}" nice -n 10 "$@"; }
for id in "$@"; do
  s=$(date +%s)
  if [ ! -s "sound/$id.json" ]; then
    run "$PY" sound.py --audio "full/$id.m4a" --words "out/$id/transcript.json" --work sep --out "sound/$id.json" >> sound_log.txt 2>&1
    echo "$id sound exit=$? secs=$(( $(date +%s)-s ))" >> sound_progress.txt
  fi
  if [ -s "sound/$id.json" ] && [ ! -s "sfx_ev/$id.json" ]; then
    run "$PY" sfx_events.py --events "events/$id.json" --stem "sep/htdemucs/$id/no_vocals.wav" --out "sfx_ev/$id.json" >> sound_log.txt 2>&1
    echo "$id sfx exit=$?" >> sound_progress.txt
  fi
done
echo ALLDONE >> sound_progress.txt
