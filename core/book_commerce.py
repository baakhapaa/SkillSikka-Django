"""Book order settlement boundary for a future trusted provider adapter."""
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import BookEntitlement, BookOrder, EBook
from .book_reader import book_has_usable_content


@transaction.atomic
def prepare_book_order(user, book_id):
    """Snapshot the single-book price when a trusted adapter starts checkout."""
    from .book_reader import active_book_entitlements

    book = EBook.objects.select_for_update().get(pk=book_id, is_published=True)
    if book.price is None or book.price <= 0 or not book_has_usable_content(book):
        raise ValueError('Book is unavailable for paid checkout.')
    if active_book_entitlements(user).filter(book=book).exists():
        raise ValueError('The user already has access to this book.')
    order, _ = BookOrder.objects.filter(status__in=[
        BookOrder.Status.PENDING, BookOrder.Status.PROCESSING, BookOrder.Status.PAID,
    ]).get_or_create(user=user, book=book, defaults={
        'original_price': book.price, 'amount': book.price, 'currency': book.currency,
    })
    if order.status == BookOrder.Status.PAID:
        raise ValueError('The user already paid for this book.')
    return order


@dataclass(frozen=True)
class VerifiedBookPayment:
    order_reference: UUID
    provider: str
    provider_reference: str
    transaction_id: str
    amount: Decimal
    currency: str
    status: str


def fulfill_verified_payment(payment):
    """Consume evidence from an authenticated server-side lookup only."""
    try:
        with transaction.atomic():
            book_id = BookOrder.objects.values_list('book_id', flat=True).get(reference=payment.order_reference)
            EBook.objects.select_for_update().get(pk=book_id)
            order = BookOrder.objects.select_for_update().get(reference=payment.order_reference)
            if (
                payment.status != 'paid' or not order.provider or not order.provider_reference
                or not payment.transaction_id or len(payment.transaction_id) > 128
                or (order.provider, order.provider_reference, order.amount, order.currency)
                != (payment.provider, payment.provider_reference, payment.amount, payment.currency)
            ):
                raise ValueError('Verified payment does not match the book order.')
            if order.status == BookOrder.Status.PAID and order.provider_transaction == payment.transaction_id:
                return order
            if order.status not in (BookOrder.Status.PENDING, BookOrder.Status.PROCESSING):
                raise ValueError('Book order cannot be fulfilled in its current state.')
            now = timezone.now()
            order.status = BookOrder.Status.PAID
            order.provider_transaction = payment.transaction_id
            order.paid_at = now
            order.save(update_fields=['status', 'provider_transaction', 'paid_at', 'updated_at'])
            BookEntitlement.objects.get_or_create(
                user=order.user, book=order.book, order=order,
                defaults={'source': BookEntitlement.Source.PURCHASE, 'granted_at': now},
            )
            return order
    except (BookOrder.DoesNotExist, IntegrityError) as exc:
        raise ValueError('Unknown book order or reused provider transaction.') from exc


def refund_verified_order(payment):
    """Apply a verified terminal refund and revoke its grant atomically."""
    with transaction.atomic():
        order = BookOrder.objects.select_for_update().get(reference=payment.order_reference)
        if (
            payment.status != 'refunded' or not payment.transaction_id
            or (order.provider, order.provider_reference, order.provider_transaction, order.amount, order.currency)
            != (payment.provider, payment.provider_reference, payment.transaction_id, payment.amount, payment.currency)
        ):
            raise ValueError('Verified refund does not match the book order.')
        if order.status == BookOrder.Status.REFUNDED:
            return order
        if order.status != BookOrder.Status.PAID:
            raise ValueError('Only paid book orders can be refunded.')
        order.status = BookOrder.Status.REFUNDED
        order.save(update_fields=['status', 'updated_at'])
        BookEntitlement.objects.filter(order=order, revoked_at__isnull=True).update(revoked_at=timezone.now())
        return order
