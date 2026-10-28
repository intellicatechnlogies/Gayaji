from django.urls import include, path

from tourism import views

urlpatterns = [
    path("", views.home, name="home"),
    path("admin/", views.admin_page, name="admin-page"),
    path("api/", include("tourism.urls")),
]
