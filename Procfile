web: gunicorn config.wsgi
release: python manage.py collectstatic --noinput && python manage.py migrate --noinput
