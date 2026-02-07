import os
import django
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
User = get_user_model()

# 1. Run Migrations
from django.core.management import call_command
print("Running Migrations...")
call_command('migrate')

print("Collecting static files...")
# This generates the 'staticfiles' folder so Whitenoise can serve CSS
call_command('collectstatic', interactive=False, clear=True)

# 2. Create Superuser if missing
SU_NAME = os.getenv('DJANGO_SUPERUSER_USERNAME', 'admin')
SU_EMAIL = os.getenv('DJANGO_SUPERUSER_EMAIL', 'admin@example.com')
SU_PASS = os.getenv('DJANGO_SUPERUSER_PASSWORD', 'AdminPass123!')

if not User.objects.filter(username=SU_NAME).exists():
    print(f"Creating superuser: {SU_NAME}")
    User.objects.create_superuser(username=SU_NAME, email=SU_EMAIL, password=SU_PASS)
else:
    print("Superuser already exists.")
