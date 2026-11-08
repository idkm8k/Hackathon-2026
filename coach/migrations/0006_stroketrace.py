from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("coach", "0005_enclosure_rules_and_cache"),
    ]

    operations = [
        migrations.CreateModel(
            name="StrokeTrace",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("user", models.CharField(db_index=True, max_length=50)),
                ("character", models.CharField(max_length=4)),
                ("sequence", models.PositiveIntegerField()),
                ("stroke_num", models.PositiveIntegerField()),
                ("correct", models.BooleanField(default=False)),
                ("drawn_points", models.TextField(blank=True, default="[]")),
                ("board_size", models.IntegerField(default=900)),
                ("diagnosis", models.CharField(blank=True, default="", max_length=40)),
                ("rule", models.CharField(blank=True, db_index=True, default="", max_length=64)),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("attempt", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="stroke_traces", to="coach.attempt")),
            ],
            options={"ordering": ("sequence", "id")},
        ),
    ]
