from django.urls import include, path

from tourism.views import home

urlpatterns = [
    path("", home, name="home"),
    path("api/", include("tourism.urls")),
]
