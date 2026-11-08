from django.db import models

class EnclosureChar(models.Model):
    character = models.CharField(max_length=4, primary_key=True)
    family = models.CharField(max_length=20)
    frame_component = models.CharField(max_length=4)
    pattern = models.CharField(max_length=32)


class Attempt(models.Model):
    user = models.CharField(max_length=50, db_index=True)
    character = models.CharField(max_length=4)
    mistakes = models.IntegerField(default=0)
    completed = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

class StrokeMistake(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="stroke_mistakes")
    user = models.CharField(max_length=50, db_index=True)
    character = models.CharField(max_length=4)
    stroke_num = models.IntegerField()  # 1-indexed
    drawn_points = models.TextField(blank=True, default="[]")  # JSON list of [x, y]
    board_size = models.IntegerField(default=300)
    diagnosis = models.CharField(max_length=40, blank=True, default="")
    habit = models.CharField(max_length=64, blank=True, default="", db_index=True)
    rule = models.CharField(max_length=64, blank=True, default="", db_index=True)
    explanation = models.TextField(blank=True, default="")
    created = models.DateTimeField(auto_now_add=True)


class ExplanationCache(models.Model):
    user = models.CharField(max_length=50, db_index=True)
    character = models.CharField(max_length=4)
    rule = models.CharField(max_length=64)
    level = models.CharField(max_length=16)
    history_signature = models.TextField()
    explanation = models.TextField()
    source = models.CharField(max_length=16, default="rule")
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["user", "character", "rule", "level"],
            name="unique_enclosure_explanation_cache",
        )]
