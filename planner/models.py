from django.db import models
from django.utils import timezone


class EngineerSettings(models.Model):
    """Singleton-style settings: start/depot location for the day."""

    start_label = models.CharField(
        max_length=200,
        blank=True,
        default='Home / Depot',
        help_text='Label for your start point',
    )
    start_location = models.CharField(
        max_length=255,
        blank=True,
        help_text='Postcode or address you start from',
    )
    start_display = models.CharField(
        max_length=255,
        blank=True,
        help_text='Resolved street / place for the start point',
    )
    start_lat = models.FloatField(null=True, blank=True)
    start_lng = models.FloatField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Engineer settings'
        verbose_name_plural = 'Engineer settings'

    def __str__(self):
        return self.start_location or 'No start location set'

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Job(models.Model):
    class AppointmentType(models.TextChoices):
        AM = 'AM', 'AM (8am – 1pm)'
        PM = 'PM', 'PM (1pm – 6pm)'
        ALLDAY = 'ALLDAY', 'All day'

    job_date = models.DateField(default=timezone.localdate)
    reference = models.CharField(
        max_length=100,
        blank=True,
        help_text='Optional job / TT number',
    )
    location = models.CharField(
        max_length=255,
        help_text='Full address or just a postcode',
    )
    appointment_type = models.CharField(
        max_length=10,
        choices=AppointmentType.choices,
        default=AppointmentType.ALLDAY,
    )
    notes = models.TextField(blank=True)
    lat = models.FloatField(null=True, blank=True)
    lng = models.FloatField(null=True, blank=True)
    geocode_display = models.CharField(max_length=255, blank=True)
    route_order = models.PositiveIntegerField(null=True, blank=True)
    estimated_arrival = models.TimeField(null=True, blank=True)
    leg_miles_from_previous = models.FloatField(null=True, blank=True)
    leg_minutes_from_previous = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Driving minutes from previous stop along roads',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['job_date', 'route_order', 'id']

    def __str__(self):
        ref = f'{self.reference} – ' if self.reference else ''
        return f'{ref}{self.location} ({self.get_appointment_type_display()})'

    @property
    def is_geocoded(self):
        return self.lat is not None and self.lng is not None

    @property
    def appointment_short(self):
        return {
            self.AppointmentType.AM: 'AM',
            self.AppointmentType.PM: 'PM',
            self.AppointmentType.ALLDAY: 'All day',
        }.get(self.appointment_type, self.appointment_type)


class DayRoute(models.Model):
    """Saved road geometry + totals for a planned day."""

    job_date = models.DateField(unique=True)
    geometry = models.JSONField(
        default=list,
        help_text='List of [lat, lng] points along the driving route',
    )
    total_miles = models.FloatField(default=0)
    total_minutes = models.PositiveIntegerField(default=0)
    source = models.CharField(max_length=20, blank=True, default='osrm')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-job_date']

    def __str__(self):
        return f'Route for {self.job_date} ({self.total_miles:.1f} mi)'
