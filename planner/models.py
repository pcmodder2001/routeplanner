from django.conf import settings
from django.db import models
from django.utils import timezone
from decimal import Decimal

from .planner_day import planner_today


class EngineerSettings(models.Model):
    """Per-user start/depot location for the day."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='engineer_settings',
        null=True,
        blank=True,
    )
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
        who = self.user.username if self.user_id else 'unassigned'
        return f'{who}: {self.start_location or "No start location set"}'

    @classmethod
    def for_user(cls, user):
        obj, _ = cls.objects.get_or_create(user=user)
        return obj


class Job(models.Model):
    class AppointmentType(models.TextChoices):
        AM = 'AM', 'AM (8am – 1pm)'
        PM = 'PM', 'PM (1pm – 6pm)'
        ALLDAY = 'ALLDAY', 'All day'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        DONE = 'done', 'Complete'
        MPU = 'mpu', 'MPU'
        FAILED = 'failed', 'Failed'
        SKIPPED = 'skipped', 'Skipped'

    MPU_RATE = Decimal('15.00')

    class WorkType(models.TextChoices):
        MANAGED_INSTALL = 'managed_install', 'Managed install'
        SELF_INSTALL = 'self_install', 'Self install'
        SOGEA_REPAIR = 'sogea_repair', 'SOGEA repair'
        OGEA_REPAIR = 'ogea_repair', 'OGEA repair'
        COPPER_REPAIR = 'copper_repair', 'Copper repair'

    WORK_TYPE_RATES = {
        WorkType.MANAGED_INSTALL: Decimal('22.50'),
        WorkType.SELF_INSTALL: Decimal('11.50'),
        WorkType.SOGEA_REPAIR: Decimal('30.00'),
        WorkType.OGEA_REPAIR: Decimal('30.00'),
        WorkType.COPPER_REPAIR: Decimal('30.00'),
    }

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='jobs',
        null=True,
        blank=True,
    )
    job_date = models.DateField(
        default=planner_today,
        help_text='Planning day (rolls to tomorrow after 9pm local)',
    )
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
    work_type = models.CharField(
        max_length=20,
        choices=WorkType.choices,
        blank=True,
        default='',
        help_text='Parsed from task description on bulk import',
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
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
    def is_active(self):
        return self.status == self.Status.PENDING

    @property
    def appointment_short(self):
        return {
            self.AppointmentType.AM: 'AM',
            self.AppointmentType.PM: 'PM',
            self.AppointmentType.ALLDAY: 'All day',
        }.get(self.appointment_type, self.appointment_type)

    @property
    def work_type_label(self):
        if not self.work_type:
            return ''
        return self.get_work_type_display()

    @property
    def work_rate(self) -> Decimal | None:
        if not self.work_type:
            return None
        return self.WORK_TYPE_RATES.get(self.work_type)

    @property
    def work_rate_display(self) -> str:
        rate = self.work_rate
        if rate is None:
            return ''
        return f'£{rate:.2f}'

    @property
    def allows_mpu(self) -> bool:
        """MPU part-payment is only valid on repair work types."""
        return self.work_type in (
            self.WorkType.SOGEA_REPAIR,
            self.WorkType.OGEA_REPAIR,
            self.WorkType.COPPER_REPAIR,
        )

    @property
    def effective_rate_display(self) -> str:
        if self.status == self.Status.FAILED:
            return '£0.00'
        if self.status == self.Status.SKIPPED:
            return ''
        if self.status == self.Status.MPU:
            return f'£{self.MPU_RATE:.2f}'
        if not self.work_type:
            return ''
        return self.work_rate_display


class DayRoute(models.Model):
    """Saved road geometry + totals for a planned day (per user)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='day_routes',
        null=True,
        blank=True,
    )
    job_date = models.DateField()
    geometry = models.JSONField(
        default=list,
        help_text='List of [lat, lng] points along the driving route',
    )
    total_miles = models.FloatField(default=0)
    total_minutes = models.PositiveIntegerField(default=0)
    source = models.CharField(max_length=20, blank=True, default='osrm')
    order_locked = models.BooleanField(
        default=False,
        help_text='When true, keep manual drag order instead of auto-optimising',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-job_date']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'job_date'],
                name='planner_dayroute_user_job_date_uniq',
            ),
        ]

    def __str__(self):
        who = self.user.username if self.user_id else 'unassigned'
        return f'{who} route for {self.job_date} ({self.total_miles:.1f} mi)'


class VanKitItem(models.Model):
    """Always-carry van stock checklist (superuser ordering tracker)."""

    name = models.CharField(max_length=200)
    product_code = models.CharField(
        max_length=64,
        unique=True,
        help_text='Code used when marking as ordered',
    )
    notes = models.CharField(max_length=255, blank=True)
    ordered = models.BooleanField(
        default=False,
        help_text='Green when this product has been ordered',
    )
    ordered_at = models.DateTimeField(null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'name', 'id']

    def __str__(self):
        return f'{self.product_code} — {self.name}'

    @staticmethod
    def normalise_code(code: str) -> str:
        text = (code or '').strip().lstrip("'\"")
        return ''.join(text.split()).upper()


class BulkPasteLog(models.Model):
    """Archived work-pack paste text (superuser searchable history)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='bulk_pastes',
        help_text='Engineer whose route the paste was applied to',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bulk_pastes_created',
        help_text='Account that submitted the paste',
    )
    job_date = models.DateField(
        help_text='Planner day the paste was applied to',
    )
    raw_text = models.TextField()
    search_text = models.TextField(
        blank=True,
        help_text='Lowercased refs, postcodes, addresses for search',
    )
    jobs_added = models.PositiveIntegerField(default=0)
    jobs_removed = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        when = self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else '?'
        who = self.user.username if self.user_id else '?'
        return f'Paste {when} · {who} ({self.jobs_added} added)'
