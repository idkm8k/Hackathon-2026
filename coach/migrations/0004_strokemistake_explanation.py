from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("coach", "0003_strokemistake_habit"),
    ]

    operations = [
        migrations.AddField(
            model_name="strokemistake",
            name="explanation",
            field=models.TextField(blank=True, default=""),
        ),
    ]
