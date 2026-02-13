from django.contrib.auth import get_user_model
from django.utils.crypto import get_random_string

User = get_user_model()


def convert_guest_attendance_to_user(attendance):
    """
    Converts a guest attendance record to a linked User account.
    Returns (user, created) tuple.
    """
    if attendance.user or not attendance.guest_email:
        return None, False

    email = attendance.guest_email.strip().lower()
    first_name = attendance.guest_first_name.strip()
    last_name = attendance.guest_last_name.strip()

    existing = User.objects.filter(email=email).first()
    if existing:
        attendance.user = existing
        attendance.save()
        return existing, False

    username = email.split("@")[0]
    base_username = username
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f"{base_username}{counter}"
        counter += 1

    new_user = User.objects.create_user(
        username=username,
        email=email,
        password=get_random_string(12),
        first_name=first_name,
        last_name=last_name,
        is_guest=True,
    )

    attendance.user = new_user
    attendance.save()
    return new_user, True
