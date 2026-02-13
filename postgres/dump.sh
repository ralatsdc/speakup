# https://www.postgresql.org/docs/17/app-pgdump.html
. .zshenv
echo "password: $PGPASSWORD"
pg_dump -U $PGUSER -h $PGHOST -p $PGPORT -W -F t $PGDATABASE > dump-$(date "+%Y-%m-%dT%H:%M:%S").tar
