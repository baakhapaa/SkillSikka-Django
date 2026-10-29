"""Settle a payment the way the gateway would, without the gateway.

**Sandbox only.** eSewa's test environment cannot be relied on — its reCAPTCHA
quota runs out and nobody can log in at all, which makes everything after the
payment (enrolment goes `active`, the player opens, My Learning picks it up)
untestable. This settles the row through the same `settle_payment` the real
refresh uses, so what you are testing is the real code path with a stub verdict
in front of it.

It refuses to run with `PAYMENT_MODE=live`. A command that marks payments paid
must never exist alongside real money.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.models import Payment
from core.payments import settle_payment


class Command(BaseCommand):
	help = (
		'Sandbox only: settle a payment as if the gateway had confirmed it. '
		'Refuses to run when PAYMENT_MODE=live.'
	)

	def add_arguments(self, parser):
		parser.add_argument('payment', type=int, help='Payment id (see the admin or the DB)')
		parser.add_argument(
			'--status',
			default='successful',
			choices=['successful', 'cancelled', 'failed'],
			help='What to record. `successful` also activates the enrolment.',
		)
		parser.add_argument(
			'--reference',
			default='',
			help='Gateway transaction id to store. Defaults to SANDBOX-<payment id>.',
		)

	def handle(self, *args, **options):
		if settings.PAYMENT_MODE == 'live':
			raise CommandError(
				'Refusing to run with PAYMENT_MODE=live. This marks payments as '
				'paid without the gateway; it exists for sandbox testing only.'
			)

		payment_id = options['payment']
		status = options['status']
		reference = options['reference'] or f'SANDBOX-{payment_id}'

		try:
			before = Payment.objects.select_related('course', 'enrollment').get(pk=payment_id)
		except Payment.DoesNotExist:
			raise CommandError(f'No payment with id {payment_id}.')

		if before.status != 'initiated':
			self.stdout.write(self.style.WARNING(
				f'Payment {payment_id} is already `{before.status}`; nothing to do.'
			))
			return

		payment = settle_payment(payment_id, status, reference)
		enrollment = payment.enrollment
		enrollment.refresh_from_db()

		self.stdout.write(self.style.SUCCESS(
			f'Payment {payment_id} -> {payment.status}  '
			f'({payment.course.title}, {payment.amount})'
		))
		self.stdout.write(f'  enrolment {enrollment.pk} -> {enrollment.status}')
		if status == 'successful':
			self.stdout.write(
				'  The student can now open the course. If the app is already '
				'open, tap "Check now" in the sheet or reopen the course page.'
			)
