from django.urls import path

from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('', views.dashboard, name='dashboard'),
    path('jobs/add/', views.add_job, name='add_job'),
    path('jobs/<int:pk>/delete/', views.delete_job, name='delete_job'),
    path('jobs/<int:pk>/appointment/', views.update_appointment, name='update_appointment'),
    path('jobs/<int:pk>/notes/', views.update_notes, name='update_notes'),
    path('jobs/<int:pk>/mark/', views.mark_job, name='mark_job'),
    path('jobs/reorder/', views.reorder_jobs, name='reorder_jobs'),
    path('places/autocomplete/', views.places_autocomplete, name='places_autocomplete'),
    path('places/details/', views.place_details, name='place_details'),
    path('unlock/', views.unlock_order, name='unlock_order'),
    path('plan/', views.plan_route, name='plan_route'),
    path('clear/', views.clear_route, name='clear_route'),
    path('settings/', views.settings_view, name='settings'),
]
