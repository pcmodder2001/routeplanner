from django.contrib import admin

from .models import DayRoute, EngineerSettings, Job, VanKitItem


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'job_date',
        'reference',
        'location',
        'appointment_type',
        'work_type',
        'status',
        'route_order',
        'estimated_arrival',
        'leg_minutes_from_previous',
    )
    list_filter = ('user', 'job_date', 'appointment_type', 'work_type', 'status')
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


@admin.register(VanKitItem)
class VanKitItemAdmin(admin.ModelAdmin):
    list_display = (
        'product_code',
        'name',
        'ordered',
        'ordered_at',
        'sort_order',
    )
    list_filter = ('ordered',)
    search_fields = ('product_code', 'name', 'notes')
    list_editable = ('ordered', 'sort_order')
