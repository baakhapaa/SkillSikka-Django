"""Khalti and eSewa gateways. A payment only becomes successful after the
gateway itself confirms it to the server; nothing the client sends is trusted."""
import base64
import hashlib
import hmac
import logging
from decimal import Decimal

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Notification, Payment


logger = logging.getLogger(__name__)

GATEWAY_TIMEOUT = 15
KHALTI_MIN_AMOUNT = Decimal('10')


class GatewayError(Exception):
	"""The gateway could not be reached or rejected the request."""


class GatewayNotConfigured(GatewayError):
	pass


# =========================================================
# Khalti (ePayment API)
# =========================================================

def _khalti_post(path, payload):
	if not settings.KHALTI_SECRET_KEY:
		raise GatewayNotConfigured('Khalti is not configured on the server.')
	try:
		response = requests.post(
			settings.KHALTI_BASE_URL.rstrip('/') + '/' + path.lstrip('/'),
			json=payload,
			headers={'Authorization': f'Key {settings.KHALTI_SECRET_KEY}'},
			timeout=GATEWAY_TIMEOUT,
		)
	except requests.RequestException as exc:
		raise GatewayError(f'Khalti is unreachable: {exc}') from exc

	try:
		body = response.json()
	except ValueError:
		body = {'raw': response.text[:500]}
	if response.status_code >= 400:
		logger.warning('Khalti %s failed (%s): %s', path, response.status_code, body)
		raise GatewayError(f'Khalti rejected the request: {body}')
	return body


def khalti_initiate(payment, return_url, website_url):
	if payment.amount < KHALTI_MIN_AMOUNT:
		raise GatewayError('Khalti requires an amount of at least Rs. 10.')

	student = payment.student
	customer = {'name': student.name, 'email': student.email}
	if student.phone_number:
		customer['phone'] = student.phone_number

	body = _khalti_post('epayment/initiate/', {
		'return_url': return_url,
		'website_url': website_url,
		'amount': int(payment.amount * 100),  # paisa
		'purchase_order_id': payment.transaction_reference,
		'purchase_order_name': payment.course.title[:100],
		'customer_info': customer,
	})
	payment.gateway_token = body['pidx']
	payment.gateway_response = {'initiate': body}
	payment.save(update_fields=['gateway_token', 'gateway_response'])
	return body['payment_url']


KHALTI_STATUS_MAP = {
	'Completed': 'successful',
	'User canceled': 'cancelled',
	'Expired': 'failed',
	'Refunded': 'failed',
	'Partially Refunded': 'failed',
	# Pending / Initiated: still waiting, leave as initiated.
}


def khalti_check(payment):
	"""(new status or None if still pending, gateway transaction id, raw body)."""
	body = _khalti_post('epayment/lookup/', {'pidx': payment.gateway_token})
	new_status = KHALTI_STATUS_MAP.get(body.get('status'))
	if new_status == 'successful' and Decimal(body.get('total_amount', 0)) != payment.amount * 100:
		logger.error('Khalti amount mismatch for payment %s: %s', payment.pk, body)
		new_status = 'failed'
	return new_status, body.get('transaction_id') or '', body


# =========================================================
# eSewa (ePay v2)
# =========================================================

def esewa_amount(amount):
	"""The exact amount string eSewa signs and echoes back, e.g. '1500' or '99.5'."""
	return format(amount.normalize(), 'f')


def esewa_signature(message):
	digest = hmac.new(settings.ESEWA_SECRET_KEY.encode(), message.encode(), hashlib.sha256).digest()
	return base64.b64encode(digest).decode()


def esewa_form(payment, success_url, failure_url):
	if not (settings.ESEWA_PRODUCT_CODE and settings.ESEWA_SECRET_KEY):
		raise GatewayNotConfigured('eSewa is not configured on the server.')

	total = esewa_amount(payment.amount)
	fields = {
		'amount': total,
		'tax_amount': '0',
		'total_amount': total,
		'transaction_uuid': payment.transaction_reference,
		'product_code': settings.ESEWA_PRODUCT_CODE,
		'product_service_charge': '0',
		'product_delivery_charge': '0',
		'success_url': success_url,
		'failure_url': failure_url,
		'signed_field_names': 'total_amount,transaction_uuid,product_code',
	}
	fields['signature'] = esewa_signature(
		f'total_amount={total},transaction_uuid={payment.transaction_reference},'
		f'product_code={settings.ESEWA_PRODUCT_CODE}'
	)
	return settings.ESEWA_FORM_URL, fields


ESEWA_STATUS_MAP = {
	'COMPLETE': 'successful',
	'CANCELED': 'cancelled',
	'NOT_FOUND': 'failed',
	'FULL_REFUND': 'failed',
	'PARTIAL_REFUND': 'failed',
	# PENDING / AMBIGUOUS: still waiting, leave as initiated.
}


def esewa_check(payment):
	"""(new status or None if still pending, eSewa ref_id, raw body)."""
	try:
		response = requests.get(settings.ESEWA_STATUS_URL, params={
			'product_code': settings.ESEWA_PRODUCT_CODE,
			'total_amount': esewa_amount(payment.amount),
			'transaction_uuid': payment.transaction_reference,
		}, timeout=GATEWAY_TIMEOUT)
		body = response.json()
	except (requests.RequestException, ValueError) as exc:
		raise GatewayError(f'eSewa status check failed: {exc}') from exc

	new_status = ESEWA_STATUS_MAP.get(body.get('status'))
	if new_status == 'successful' and Decimal(str(body.get('total_amount', 0))) != payment.amount:
		logger.error('eSewa amount mismatch for payment %s: %s', payment.pk, body)
		new_status = 'failed'
	return new_status, body.get('ref_id') or '', body


# =========================================================
# Shared
# =========================================================

def refresh_payment(payment_id):
	"""Ask the gateway about an initiated payment and apply the result once.

	Safe to call repeatedly and concurrently. Returns the payment.
	"""
	with transaction.atomic():
		payment = Payment.objects.select_for_update().select_related('enrollment', 'course').get(pk=payment_id)
		if payment.status != 'initiated':
			return payment
		if payment.provider == 'khalti' and not payment.gateway_token:
			return payment

		check = khalti_check if payment.provider == 'khalti' else esewa_check
		new_status, gateway_transaction_id, body = check(payment)

		payment.gateway_response = {**payment.gateway_response, 'last_check': body}
		updated = ['gateway_response']
		if new_status is not None:
			payment.status = new_status
			payment.verified_at = timezone.now()
			payment.gateway_transaction_id = gateway_transaction_id
			updated += ['status', 'verified_at', 'gateway_transaction_id']
		payment.save(update_fields=updated)

		if new_status == 'successful':
			enrollment = payment.enrollment
			enrollment.status = 'active'
			enrollment.amount_paid = payment.amount
			enrollment.payment_reference = payment.transaction_reference
			enrollment.save(update_fields=['status', 'amount_paid', 'payment_reference'])

		if new_status is not None:
			_notify_result(payment)

	return payment


def _notify_result(payment):
	if payment.status == 'successful':
		title = 'Payment successful'
		message = f'Your payment for "{payment.course.title}" was successful.'
	else:
		title = 'Payment not completed'
		message = f'Your payment for "{payment.course.title}" was not completed. Please try again.'
	Notification.objects.create(
		recipient=payment.student,
		notification_type='payment',
		title=title,
		message=message,
		related_type='payment',
		related_id=payment.pk,
	)
