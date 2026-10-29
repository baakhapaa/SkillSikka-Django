"""Browser pages the payment gateways send the user through (no login: they
are reached inside the gateway's flow, and only act on gateway-confirmed state)."""
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from .models import Payment
from .payments import GatewayError, esewa_form, refresh_payment


class _AppRedirect(HttpResponseRedirect):
	"""A redirect that may leave http(s).

	`HttpResponseRedirect` trusts only `http`, `https` and `ftp` and raises
	`DisallowedRedirect` — which reaches the student as a 400 in their browser —
	for anything else. The return URL is a custom scheme on purpose:
	`skillsikka://payment` is what makes the OS hand the redirect to the app
	instead of opening another web page. Without this the student pays, the
	gateway sends them back, and they land on a 400 instead of in the course.

	`skillsikka` is the scheme the Flutter client registers in `AndroidManifest`
	and `Info.plist`. An https universal link in production passes the default
	check unchanged, so this only widens what is allowed, it does not bypass it.
	"""

	allowed_schemes = [*HttpResponseRedirect.allowed_schemes, 'skillsikka']


def _finish(request, payment):
	"""Send the browser on to the app deep link, or to the result page."""
	params = urlencode({'payment_id': payment.pk, 'status': payment.status})
	if settings.PAYMENT_APP_RETURN_URL:
		return _AppRedirect(f'{settings.PAYMENT_APP_RETURN_URL}?{params}')
	return redirect(f"{reverse('payment-complete', args=[payment.transaction_reference])}?{params}")


def _refresh_quietly(payment):
	try:
		return refresh_payment(payment.pk)
	except GatewayError:
		# Stays "initiated"; the app can ask again via GET /payments/{id}/.
		return payment


@require_GET
def esewa_checkout(request, reference):
	payment = get_object_or_404(Payment.objects.select_related('course'), transaction_reference=reference, provider='esewa')
	if payment.status != 'initiated':
		return _finish(request, payment)

	action, fields = esewa_form(
		payment,
		success_url=request.build_absolute_uri(reverse('payment-esewa-return', args=[reference])),
		failure_url=request.build_absolute_uri(reverse('payment-esewa-return', args=[reference])),
	)
	return render(request, 'payments/esewa_checkout.html', {'action': action, 'fields': fields, 'payment': payment})


@require_GET
def esewa_return(request, reference):
	payment = get_object_or_404(Payment, transaction_reference=reference, provider='esewa')
	return _finish(request, _refresh_quietly(payment))


@require_GET
def khalti_return(request, reference):
	payment = get_object_or_404(Payment, transaction_reference=reference, provider='khalti')
	return _finish(request, _refresh_quietly(payment))


@require_GET
def payment_complete(request, reference):
	payment = get_object_or_404(Payment.objects.select_related('course'), transaction_reference=reference)
	return render(request, 'payments/complete.html', {'payment': payment})
