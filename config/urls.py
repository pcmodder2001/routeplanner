from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("", include("sitematrix_client.urls")),
    path('admin/', admin.site.urls),
    path('', include('planner.urls')),
]
