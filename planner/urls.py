from django.urls import path

from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('jobs/add/', views.add_job, name='add_job'),
    path('jobs/<int:pk>/delete/', views.delete_job, name='delete_job'),
    path('jobs/<int:pk>/appointment/', views.update_appointment, name='update_appointment'),
    path('jobs/<int:pk>/notes/', views.update_notes, name='update_notes'),
    path('plan/', views.plan_route, name='plan_route'),
    path('clear/', views.clear_route, name='clear_route'),
    path('settings/', views.settings_view, name='settings'),
]
