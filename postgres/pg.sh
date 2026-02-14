#!/opt/local/bin/bash
# Print usage
usage() {
    cat << EOF

NAME
    pg - Dump or restore Speak Up Cambridge database

SYNOPSIS
    pg [OPTIONS]

DESCRIPTION
    Dump or restore the Railway PostgreSQL database for Speak Up
    Cambridge with a datetime stamp. The host, port, database, user,
    and password must be set in the environment.

OPTIONS 
    -d    Dump

    -r    Restore

    -h    Help

    -e    Exit immediately if a command returns a non-zero status

    -x    Print a trace of simple commands

SEE
    https://www.postgresql.org/docs/17/app-pgdump.html

EOF
}

# Parse command line options
dump=0
restore=""
while getopts ":dr:hex" opt; do
    case $opt in
        d)
            dump=1
            ;;
        r)
	    restore="${OPTARG}"
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

if [[ $dump -eq 0 && $restore == "" ]]; then
    echo "Must select dump or restore"
    exit 1
elif [[ $dump -eq 1 && $restore != "" ]]; then
    echo "Can only select dump OR restore"
    exit 1
fi

# Parse command line arguments
shift `expr ${OPTIND} - 1`
if [[ "$#" -ne 0 ]]; then
    echo "No arguments requires"
    exit 1
fi

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source environment variables using the absolute path
if [ -f "$SCRIPT_DIR/.env" ]; then
    source "$SCRIPT_DIR/.env"
else
    echo ".env file not found at $SCRIPT_DIR/.env"
    exit 1
fi

if [[ $dump -eq 1 ]]; then
    pg_dump -h $PGHOST -p $PGPORT -d $PGDATABASE -U $PGUSER -w -F t > dump-$(date "+%Y-%m-%dT%H:%M:%S").tar
else
    pg_restore -h $PGHOST -p $PGPORT -d $PGDATABASE -U $PGUSER -w -c -F t $restore
fi
