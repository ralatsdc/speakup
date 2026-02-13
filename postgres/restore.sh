# https://www.postgresql.org/docs/17/app-pgrestore.html
. .zshenv
echo "password: $PGPASSWORD"
pg_restore -U $PGUSER -h $PGHOST -p $PGPORT -c -W -F t -d $PGDATABASE $1
