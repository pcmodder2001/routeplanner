from django.contrib import admin
from django.urls import include, path

from planner.health import health

urlpatterns = [
    path('health/', health, name='health'),
    path("", include("sitematrix_client.urls")),
    path('admin/', admin.site.urls),
    path('', include('planner.urls')),
]
