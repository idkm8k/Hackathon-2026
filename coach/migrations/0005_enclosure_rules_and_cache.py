from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("coach", "0004_strokemistake_explanation"),
    ]

    operations = [
        migrations.CreateModel(
            name="EnclosureChar",
            fields=[
                ("character", models.CharField(max_length=4, primary_key=True, serialize=False)),
                ("family", models.CharField(max_length=20)),
                ("frame_component", models.CharField(max_length=4)),
                ("pattern", models.CharField(max_length=32)),
            ],
        ),
        migrations.AddField(
            model_name="strokemistake",
            name="rule",
            field=models.CharField(blank=True, db_index=True, default="", max_length=64),
        ),
        migrations.CreateModel(
            name="ExplanationCache",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("user", models.CharField(db_index=True, max_length=50)),
                ("character", models.CharField(max_length=4)),
                ("rule", models.CharField(max_length=64)),
                ("level", models.CharField(max_length=16)),
                ("history_signature", models.TextField()),
                ("explanation", models.TextField()),
                ("source", models.CharField(default="rule", max_length=16)),
                ("updated", models.DateTimeField(auto_now=True)),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("user", "character", "rule", "level"), name="unique_enclosure_explanation_cache")],
            },
        ),
    ]
