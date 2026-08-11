from django.urls import path

from .views import LockedView

app_name = "sitematrix_client"

urlpatterns = [
    path("locked/", LockedView.as_view(), name="locked"),
]
