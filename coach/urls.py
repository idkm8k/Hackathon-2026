from django.urls import path
from . import views
urlpatterns = [
    path("", views.index, name="index"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("replay/<int:attempt_id>/", views.replay, name="replay"),
    path("api/practice/", views.api_practice),
    path("api/heads_up/", views.api_heads_up),
    path("api/log/", views.api_log),
    path("api/explain/", views.api_explain),
    path("api/tip/", views.api_tip),
    path("api/ask/", views.api_ask),
    path("api/tts/", views.api_tts),
]
