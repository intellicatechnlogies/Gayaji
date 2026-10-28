from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tourism", "0009_storedcredentialapiuser"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="place",
            name="image",
        ),
    ]
