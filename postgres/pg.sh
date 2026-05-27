#!/opt/local/bin/bash
# Print usage
usage() {
    cat << EOF

NAME
    pg - Dump, convert, or restore Speak Up Cambridge database

SYNOPSIS
    pg [OPTIONS]

DESCRIPTION
    Dump or restore the Railway PostgreSQL database for Speak Up
    Cambridge with a datetime stamp, or convert it to SQLite. The
    host, port, database, user, and password must be set in the
    environment. Prune old backups using GFS rotation, with
    confirmation.

OPTIONS
    -d    Dump to an archive

    -c    Convert to SQLite

    -r    Restore from an archive

    -p    Prune old backups (GFS rotation)

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
prune=0
while getopts ":dcr:phex" opt; do
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
        p)
            prune=1
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

if [[ $dump -eq 0 && $convert -eq 0 && $restore == "" && $prune -eq 0 ]]; then
    echo "Must select dump, convert, restore, or prune"
    exit 1
elif [[ $(( $dump + $convert + $prune + $([[ $restore != "" ]] && echo 1 || echo 0) )) -gt 1 ]]; then
    echo "Can only select one of dump, convert, restore, or prune"
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

# Source environment variables (not needed for prune)
if [[ $prune -eq 0 ]]; then
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
elif [[ $prune -eq 1 ]]; then
    prune_backups
else
    pg_restore -h $PGHOST -p $PGPORT -d $PGDATABASE -U $PGUSER -w -c -F t $restore
fi
