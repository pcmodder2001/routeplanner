from django.contrib import admin

from .models import DayRoute, EngineerSettings, Job


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = (
        'job_date',
        'reference',
        'location',
        'appointment_type',
        'status',
        'route_order',
        'estimated_arrival',
        'leg_minutes_from_previous',
    )
    list_filter = ('job_date', 'appointment_type', 'status')
    search_fields = ('location', 'reference', 'notes')


@admin.register(EngineerSettings)
class EngineerSettingsAdmin(admin.ModelAdmin):
    list_display = ('start_label', 'start_location', 'start_lat', 'start_lng')


@admin.register(DayRoute)
class DayRouteAdmin(admin.ModelAdmin):
    list_display = (
        'job_date',
        'total_miles',
        'total_minutes',
        'source',
        'order_locked',
        'updated_at',
    )
