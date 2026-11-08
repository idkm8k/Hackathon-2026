from django.urls import path
from . import views
urlpatterns = [
    path("", views.index, name="index"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("api/practice/", views.api_practice),
    path("api/log/", views.api_log),
    path("api/tip/", views.api_tip),
    path("api/tts/", views.api_tts),
]
