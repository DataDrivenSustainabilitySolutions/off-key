#!/bin/sh
# Prepare the PostgreSQL data volume for a point-in-time restore.
# Runs inside the postgres image with the data volume at /var/lib/postgresql/data
# and the archive at /var/lib/postgresql/wal-archive; see docs/operations/recovery.md.
#
#   BASE=<base backup name>  TARGET='<UTC time>'  CONFIRM=erase-data  sh postgres_pitr_prepare.sh
set -eu
: "${BASE:?name the base backup under wal-archive/base}"
: "${TARGET:?give the recovery target time, e.g. 2026-11-16 12:53:56+00}"
archive=/var/lib/postgresql/wal-archive
data=/var/lib/postgresql/data
test -f "$archive/base/$BASE/base.tar.zst" || { echo "No base backup $BASE" >&2; exit 1; }
cd "$data"
if [ -n "$(ls -A .)" ]; then
  [ "${CONFIRM:-}" = erase-data ] || {
    echo "The data volume is not empty. Copy it aside, then set CONFIRM=erase-data." >&2
    exit 1
  }
  find . -mindepth 1 -delete
fi
zstd -dcq "$archive/base/$BASE/base.tar.zst" | tar -x
touch recovery.signal
cat >> postgresql.auto.conf <<EOF
restore_command = 'zstd -dcq $archive/wal/%f.zst > %p'
recovery_target_time = '$TARGET'
recovery_target_action = 'promote'
EOF
chown -R postgres:postgres .
chmod 700 .
echo "Prepared $data from $BASE, recovering to $TARGET"
