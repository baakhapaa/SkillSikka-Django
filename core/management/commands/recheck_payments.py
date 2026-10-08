from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Payment
from core.payments import GatewayError, refresh_payment


class Command(BaseCommand):
    help = (
        'Ask Khalti/eSewa about payments still marked "initiated" (e.g. the student '
        'closed the app mid-payment) and apply the result. Run it on a schedule, '
        'e.g. every 10 minutes.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--older-than-minutes', type=int, default=5,
            help='Only check payments started at least this long ago (default 5).',
        )
        parser.add_argument(
            '--max-age-days', type=int, default=7,
            help='Ignore payments older than this (default 7).',
        )

    def handle(self, *args, **options):
        now = timezone.now()
        pending = Payment.objects.filter(
            status='initiated',
            created_at__lte=now - timedelta(minutes=options['older_than_minutes']),
            created_at__gte=now - timedelta(days=options['max_age_days']),
        ).order_by('created_at').values_list('pk', flat=True)

        counts = {}
        for payment_id in pending:
            try:
                status = refresh_payment(payment_id).status
            except GatewayError as exc:
                status = 'gateway error'
                self.stderr.write(f'payment {payment_id}: {exc}')
            counts[status] = counts.get(status, 0) + 1

        summary = ', '.join(f'{n} {s}' for s, n in sorted(counts.items())) or 'nothing to check'
        self.stdout.write(f'Checked {sum(counts.values())} payment(s): {summary}')
