#!/opt/local/bin/bash
# Print usage
usage() {
    cat << EOF

NAME
    pg - Dump, convert, restore, or verify Speak Up Cambridge database

SYNOPSIS
    pg [OPTIONS]

DESCRIPTION
    Dump or restore the Railway PostgreSQL database for Speak Up
    Cambridge with a datetime stamp, or convert it to SQLite. The
    host, port, database, user, and password must be set in the
    environment. Prune old backups using GFS rotation, with
    confirmation. Verify the most recent dump by restoring it into
    an ephemeral local Postgres container and running sanity checks.

OPTIONS
    -d    Dump to an archive

    -c    Convert to SQLite

    -r    Restore from an archive

    -u    Restore Railway from a SQLite database (push local data up)

    -p    Prune old backups (GFS rotation)

    -t    Test-restore the latest dump (requires Docker Desktop)

    -h    Help

    -e    Exit immediately if a command returns a non-zero status

    -x    Print a trace of simple commands

SEE
    https://www.postgresql.org/docs/17/app-pgdump.html

EOF
}

# Parse command line options
dump=0
convert=0
restore=""
upload=""
prune=0
test_restore=0
while getopts ":dcr:u:pthex" opt; do
    case $opt in
        d)
            dump=1
            ;;
        c)
            convert=1
            ;;
        r)
	    restore="${OPTARG}"
            ;;
        u)
            upload="${OPTARG}"
            ;;
        p)
            prune=1
            ;;
        t)
            test_restore=1
            ;;
	h)
	    usage
	    exit 0
	    ;;
        e)
            set -e
            ;;
        x)
            set -x
            ;;
	\?)
	    echo "Invalid option: -${OPTARG}" >&2
	    usage
	    exit 1
	    ;;
	\:)
	    echo "Option -${OPTARG} requires an argument" >&2
	    usage
	    exit 1
	    ;;
    esac
done

if [[ $dump -eq 0 && $convert -eq 0 && $restore == "" && $upload == "" && $prune -eq 0 && $test_restore -eq 0 ]]; then
    echo "Must select dump, convert, restore, upload, prune, or test"
    exit 1
elif [[ $(( $dump + $convert + $prune + $test_restore + $([[ $restore != "" ]] && echo 1 || echo 0) + $([[ $upload != "" ]] && echo 1 || echo 0) )) -gt 1 ]]; then
    echo "Can only select one of dump, convert, restore, upload, prune, or test"
    exit 1
fi

# Parse command line arguments
shift `expr ${OPTIND} - 1`
if [[ "$#" -ne 0 ]]; then
    echo "No arguments required"
    exit 1
fi

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Prune old backups using GFS (Grandfather-Father-Son) rotation
prune_backups() {
    local now_epoch
    now_epoch=$(date +%s)

    # Collect dump files
    local files=()
    for f in "$SCRIPT_DIR"/dump-*.tar; do
        [[ -e "$f" ]] || continue
        files+=("$f")
    done

    if [[ ${#files[@]} -eq 0 ]]; then
        echo "No dump files found in $SCRIPT_DIR"
        return 0
    fi

    # For each file, decide keep or delete
    declare -A weekly_keep   # key: YYYY-WNN
    declare -A monthly_keep  # key: YYYY-MM
    declare -A yearly_keep   # key: YYYY
    local keep_files=()
    local delete_files=()

    # First pass: assign best candidate per bucket (latest file wins)
    # Process files sorted newest-first so the first seen per bucket is the latest
    local sorted_files
    sorted_files=($(printf '%s\n' "${files[@]}" | sort -r))

    for f in "${sorted_files[@]}"; do
        local basename
        basename=$(basename "$f")
        # Extract date from dump-YYYY-MM-DDTHH:MM:SS.tar
        local date_str="${basename#dump-}"
        date_str="${date_str%.tar}"
        # Parse into epoch (macOS BSD date)
        local file_epoch
        file_epoch=$(date -j -f "%Y-%m-%dT%H:%M:%S" "$date_str" +%s 2>/dev/null) || continue

        local age_days=$(( (now_epoch - file_epoch) / 86400 ))

        local dominated=0

        if [[ $age_days -le 7 ]]; then
            # Daily: keep all from last 7 days
            dominated=0
        elif [[ $age_days -le 30 ]]; then
            # Weekly: keep latest per ISO week
            local iso_week
            iso_week=$(date -j -f "%Y-%m-%dT%H:%M:%S" "$date_str" "+%G-W%V" 2>/dev/null)
            if [[ -z "${weekly_keep[$iso_week]+x}" ]]; then
                weekly_keep[$iso_week]="$f"
            else
                dominated=1
            fi
        elif [[ $age_days -le 365 ]]; then
            # Monthly: keep latest per month
            local month
            month=$(date -j -f "%Y-%m-%dT%H:%M:%S" "$date_str" "+%Y-%m" 2>/dev/null)
            if [[ -z "${monthly_keep[$month]+x}" ]]; then
                monthly_keep[$month]="$f"
            else
                dominated=1
            fi
        else
            # Yearly: keep latest per year
            local year
            year=$(date -j -f "%Y-%m-%dT%H:%M:%S" "$date_str" "+%Y" 2>/dev/null)
            if [[ -z "${yearly_keep[$year]+x}" ]]; then
                yearly_keep[$year]="$f"
            else
                dominated=1
            fi
        fi

        if [[ $dominated -eq 1 ]]; then
            delete_files+=("$f")
        else
            keep_files+=("$f")
        fi
    done

    if [[ ${#delete_files[@]} -eq 0 ]]; then
        echo "Nothing to prune. All ${#keep_files[@]} backup(s) are within retention policy."
        return 0
    fi

    echo "=== GFS Retention Summary ==="
    echo "Keeping ${#keep_files[@]} backup(s):"
    for f in "${keep_files[@]}"; do
        echo "  KEEP  $(basename "$f")"
    done
    echo ""
    echo "Deleting ${#delete_files[@]} backup(s):"
    for f in "${delete_files[@]}"; do
        echo "  DEL   $(basename "$f")"
    done
    echo ""

    read -rp "Proceed with deletion? [y/N] " answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
        for f in "${delete_files[@]}"; do
            rm "$f"
            echo "Deleted $(basename "$f")"
        done
        echo "Pruning complete."
    else
        echo "Aborted."
    fi
}

# Test-restore the latest dump in an ephemeral Docker Postgres
test_latest_dump() {
    if ! command -v docker >/dev/null 2>&1; then
        echo "pg.sh: docker not found in PATH; install Docker Desktop." >&2
        return 1
    fi
    if ! docker info >/dev/null 2>&1; then
        echo "pg.sh: docker daemon not running; start Docker Desktop." >&2
        return 1
    fi

    local latest
    latest=$(ls -t "$SCRIPT_DIR"/dump-*.tar 2>/dev/null | head -1)
    if [[ -z "$latest" ]]; then
        echo "pg.sh: no dump-*.tar files in $SCRIPT_DIR to test." >&2
        return 1
    fi

    # Pinned to the same major version used in production. Port 55432 is
    # unlikely to clash with a developer's local Postgres on 5432.
    local container="speakup-pg-restore-test"
    local image="postgres:17"
    local port=55432
    local password="restoretest"

    # Defensive: an interrupted prior run may have left the container
    # behind. --rm removes on stop, but it doesn't fire if the previous
    # invocation was kill -9'd.
    docker rm -f "$container" >/dev/null 2>&1 || true

    echo "pg.sh: starting $image on 127.0.0.1:$port..."
    if ! docker run -d --rm --name "$container" \
            -e POSTGRES_PASSWORD="$password" \
            -p "$port:5432" "$image" >/dev/null; then
        echo "pg.sh: failed to start container." >&2
        return 1
    fi

    # Tear the container down on any exit path from here on.
    trap 'docker stop "'"$container"'" >/dev/null 2>&1 || true' RETURN

    # Wait for the server to accept connections — pg_isready exits 0 when
    # the server is ready, non-zero otherwise. Cap at ~30s.
    local i
    for ((i=0; i<30; i++)); do
        if docker exec "$container" pg_isready -U postgres -q; then
            break
        fi
        sleep 1
    done
    if ! docker exec "$container" pg_isready -U postgres -q; then
        echo "pg.sh: container never became ready." >&2
        return 1
    fi

    echo "pg.sh: restoring $(basename "$latest")..."
    if ! PGPASSWORD="$password" pg_restore \
            -h 127.0.0.1 -p "$port" -U postgres -d postgres \
            -F t --no-owner --no-privileges "$latest" >/dev/null; then
        echo "pg.sh: pg_restore exited non-zero." >&2
        return 1
    fi

    # Sanity checks. A successful restore should leave a non-empty users
    # table and at least one meeting; the max meeting date should be
    # parseable. Failures here (with ON_ERROR_STOP=1, any missing table
    # aborts) indicate the dump is incomplete or the schema has drifted
    # unexpectedly. Heredoc rather than -c so each statement parses as
    # its own line.
    if ! PGPASSWORD="$password" psql \
            -h 127.0.0.1 -p "$port" -U postgres -d postgres \
            -v ON_ERROR_STOP=1 <<'SQL'
SELECT COUNT(*) AS user_rows FROM members_user;
SELECT COUNT(*) AS meeting_rows FROM meetings_meeting;
SELECT COUNT(*) AS attendance_rows FROM meetings_attendance;
SELECT COUNT(*) AS meeting_role_rows FROM meetings_meetingrole;
SELECT MAX(date) AS latest_meeting_date FROM meetings_meeting;
SQL
    then
        echo "pg.sh: sanity checks failed." >&2
        return 1
    fi

    echo "pg.sh: restore-test PASSED for $(basename "$latest")."
}

# Source environment variables (not needed for prune or test-restore —
# both run entirely against local artifacts and don't need Railway creds).
if [[ $prune -eq 0 && $test_restore -eq 0 ]]; then
    if [ -f "$SCRIPT_DIR/.env" ]; then
        source "$SCRIPT_DIR/.env"
    else
        echo ".env file not found at $SCRIPT_DIR/.env"
        exit 1
    fi
fi

# Dump, convert, restore, or prune
if [[ $dump -eq 1 ]]; then
    dump_file="$SCRIPT_DIR/dump-$(date "+%Y-%m-%dT%H:%M:%S").tar"
    pg_dump -h $PGHOST -p $PGPORT -d $PGDATABASE -U $PGUSER -w -F t > "$dump_file"
    # Off-site copy: email the new dump to the club's backup mailbox.
    # send_dump.py is a no-op when BACKUP_EMAIL_ADDRESS is unset, so this is
    # safe before the mailbox is provisioned. Failures here log to stderr
    # but do not fail the dump — the local tar is the primary artifact.
    py_path="$SCRIPT_DIR/../.venv/bin/python3"
    [[ -x "$py_path" ]] || py_path="python3"
    "$py_path" "$SCRIPT_DIR/send_dump.py" "$dump_file" || \
        echo "pg.sh: send_dump.py exited non-zero; dump itself succeeded." >&2
elif [[ $convert -eq 1 ]]; then
    # Build the SQLite schema with Django (correct PK/UNIQUE/FK), then copy
    # only data from Railway
    db_name=db-$(date "+%Y-%m-%dT%H:%M:%S").sqlite3
    db_path="$SCRIPT_DIR/$db_name"
    py_path="$SCRIPT_DIR/../.venv/bin/python"
    mang_path="$SCRIPT_DIR/../manage.py"
    data_path="$SCRIPT_DIR/_convert_data.json"

    # Canonical schema (also auto-seeds contenttypes + permissions)
    DATABASE_URL="sqlite:///$db_path" "$py_path" "$mang_path" migrate --noinput

    # Dump Railway rows. Exclude what migrate already seeded; serialize FKs to
    # those by natural key so they re-resolve against the fresh rows.
    DATABASE_URL="postgresql://$PGUSER:$PGPASSWORD@$PGHOST:$PGPORT/$PGDATABASE" \
        "$py_path" "$mang_path" dumpdata --natural-foreign \
        --exclude contenttypes --exclude auth.permission \
        --exclude sessions.session --exclude admin.logentry \
        -o "$data_path"

    # Load the rows into the Django-built schema
    DATABASE_URL="sqlite:///$db_path" "$py_path" "$mang_path" loaddata "$data_path"
    rm -f "$data_path"

    # Link to the database for local development
    pushd ..
    ln -fs postgres/$db_name db.sqlite3
    popd
elif [[ $upload != "" ]]; then
    # Push a local SQLite database up to Railway — the inverse of -c. Mirrors
    # the same dumpdata exclusions/natural keys so the round trip is symmetric.
    #
    # Safety: everything that can fail without touching Railway runs FIRST
    # (serialize, schema check). Immediately before the destructive flush we
    # take a full safety dump, so any failure is one `-r` away from recovery.
    # set -e aborts on the first unexpected error; steps that need a custom
    # message are guarded explicitly.
    set -e
    if [[ ! -f "$upload" ]]; then
        echo "SQLite database not found: $upload"
        exit 1
    fi
    sqlite_abs="$(cd "$(dirname "$upload")" && pwd)/$(basename "$upload")"
    py_path="$SCRIPT_DIR/../.venv/bin/python"
    mang_path="$SCRIPT_DIR/../manage.py"
    data_path="$SCRIPT_DIR/_upload_data.json"
    pg_url="postgresql://$PGUSER:$PGPASSWORD@$PGHOST:$PGPORT/$PGDATABASE"

    # 1. Serialize local rows (non-destructive; fail fast if the DB is bad).
    #    Exclude what migrate/flush re-seed; natural FKs so references to
    #    contenttypes/permissions re-resolve on the target.
    DATABASE_URL="sqlite:///$sqlite_abs" "$py_path" "$mang_path" dumpdata \
        --natural-foreign \
        --exclude contenttypes --exclude auth.permission \
        --exclude sessions.session --exclude admin.logentry \
        -o "$data_path"

    # 2. Schema guard: abort if Railway has migrations this branch lacks (prod
    #    is AHEAD). That is exactly the drift that makes loaddata fail on a
    #    column the SQLite dump can't supply — catch it BEFORE flushing. (Local
    #    being ahead is fine: step 5's migrate applies those to Railway.)
    ahead="$(DATABASE_URL="$pg_url" "$py_path" "$mang_path" shell -c '
from django.db import connections
from django.db.migrations.loader import MigrationLoader
loader = MigrationLoader(connections["default"])
extra = sorted(set(loader.applied_migrations) - set(loader.disk_migrations))
print(";".join(f"{a}.{n}" for a, n in extra))
' 2>/dev/null | tail -1)"
    if [[ -n "$ahead" ]]; then
        rm -f "$data_path"
        echo "Schema mismatch: Railway has migrations this branch lacks:"
        echo "  $ahead"
        echo "Bring the branch up to production's schema first. No change was made."
        exit 1
    fi

    # 3. Confirm — the next steps overwrite all Railway data.
    echo "About to OVERWRITE Railway database '$PGDATABASE' on $PGHOST"
    echo "with all data from: $sqlite_abs"
    echo "This DELETES every existing row in Railway before loading."
    read -rp "Proceed? [y/N] " answer
    if [[ ! "$answer" =~ ^[Yy]$ ]]; then
        rm -f "$data_path"
        echo "Aborted."
        exit 0
    fi

    # 4. Safety net: full dump of Railway *before* the flush, so a failed load
    #    is recoverable with `pg.sh -r`. Named like a normal dump so GFS prunes it.
    safety_dump="$SCRIPT_DIR/dump-$(date "+%Y-%m-%dT%H:%M:%S").tar"
    echo "Backing up Railway to $(basename "$safety_dump") before overwrite..."
    pg_dump -h "$PGHOST" -p "$PGPORT" -d "$PGDATABASE" -U "$PGUSER" -w -F t > "$safety_dump"

    # 5. Apply migrations (no-op after the check), clear data (flush re-seeds
    #    contenttypes + permissions via post_migrate), then load. A loaddata
    #    failure leaves Railway flushed, so point at the safety dump rather than
    #    falsely reporting success.
    DATABASE_URL="$pg_url" "$py_path" "$mang_path" migrate --noinput
    DATABASE_URL="$pg_url" "$py_path" "$mang_path" flush --noinput
    if ! DATABASE_URL="$pg_url" "$py_path" "$mang_path" loaddata "$data_path"; then
        echo "" >&2
        echo "loaddata FAILED — Railway is now empty. Restore the safety dump:" >&2
        echo "    bash pg.sh -r $(basename "$safety_dump")" >&2
        rm -f "$data_path"
        exit 1
    fi
    rm -f "$data_path"
    echo "Railway database restored from $(basename "$sqlite_abs")."
    echo "Safety backup kept at $(basename "$safety_dump")."
elif [[ $prune -eq 1 ]]; then
    prune_backups
elif [[ $test_restore -eq 1 ]]; then
    test_latest_dump
else
    pg_restore -h $PGHOST -p $PGPORT -d $PGDATABASE -U $PGUSER -w -c -F t $restore
fi
