from django.contrib import admin

from .models import DayRoute, EngineerSettings, Job


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'job_date',
        'reference',
        'location',
        'appointment_type',
        'status',
        'route_order',
        'estimated_arrival',
        'leg_minutes_from_previous',
    )
    list_filter = ('user', 'job_date', 'appointment_type', 'status')
    search_fields = ('location', 'reference', 'notes', 'user__username')
    raw_id_fields = ('user',)


@admin.register(EngineerSettings)
class EngineerSettingsAdmin(admin.ModelAdmin):
    list_display = ('user', 'start_label', 'start_location', 'start_lat', 'start_lng')
    raw_id_fields = ('user',)


@admin.register(DayRoute)
class DayRouteAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'job_date',
        'total_miles',
        'total_minutes',
        'source',
        'order_locked',
        'updated_at',
    )
    list_filter = ('user', 'source', 'order_locked')
    raw_id_fields = ('user',)
