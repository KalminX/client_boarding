from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()

class Command(BaseCommand):
    help = "Creates or resets default development administrator account (admin / admin123)."

    def handle(self, *args, **options):
        user, created = User.objects.get_or_create(
            username="admin",
            defaults={"email": "admin@example.com", "is_staff": True, "is_superuser": True}
        )
        user.set_password("admin123")
        user.is_staff = True
        user.is_superuser = True
        user.save()
        if created:
            self.stdout.write(self.style.SUCCESS("Created admin user (username: admin, password: admin123)"))
        else:
            self.stdout.write(self.style.SUCCESS("Reset admin user password (username: admin, password: admin123)"))
