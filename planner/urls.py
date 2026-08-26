from django.urls import path

from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('engineers/', views.engineers_view, name='engineers'),
    path('engineers/<int:user_id>/view/', views.view_as_user, name='view_as_user'),
    path('engineers/stop/', views.stop_view_as, name='stop_view_as'),
    path('', views.dashboard, name='dashboard'),
    path('jobs/add/', views.add_job, name='add_job'),
    path('jobs/bulk/preview/', views.bulk_add_preview, name='bulk_add_preview'),
    path('jobs/bulk/confirm/', views.bulk_add_confirm, name='bulk_add_confirm'),
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
