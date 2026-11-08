from django.db import models

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
    created = models.DateTimeField(auto_now_add=True)
