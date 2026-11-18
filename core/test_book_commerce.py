from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from .book_commerce import VerifiedBookPayment, fulfill_verified_payment, prepare_book_order, refund_verified_order
from .models import BookChapter, BookEntitlement, BookOrder, BookReadingProgress, BookReview, EBook, Role, SavedBook, User
from .test_books import PDF, pdf


class BookCommerceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        student = Role.objects.get(name='student')
        instructor = Role.objects.get(name='instructor')
        cls.reader = User.objects.create_user(email='reader@example.com', name='Reader', password='test', role=student, email_verified=True)
        cls.other = User.objects.create_user(email='other@example.com', name='Other', password='test', role=student, email_verified=True)
        cls.owner = User.objects.create_user(email='author@example.com', name='Author', password='test', role=instructor, email_verified=True)
        cls.admin = User.objects.create_user(email='admin@example.com', name='Admin', password='test', role=Role.objects.get(name='super_admin'))
        cls.book = EBook.objects.create(
            title='Geometry', author='Sample Writer', uploaded_by=cls.owner, price=Decimal('100.00'),
            is_published=True, file_url='https://private.example/geometry.pdf', category='Math', difficulty='beginner',
        )
        cls.chapter = BookChapter.objects.create(book=cls.book, chapter_number=1, title='Angles', content='An angle measures a turn.')

    def setUp(self):
        cache = override_settings(CACHES={'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': f'commerce-tests-{id(self)}',
        }})
        cache.enable()
        self.addCleanup(cache.disable)
        self.api = APIClient()
        self.api.force_authenticate(self.reader)

    def url(self, name, *args):
        return reverse('api-' + name, args=args or [self.book.pk])

    def detail(self):
        response = self.api.get(self.url('ebook-detail'))
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def make_free(self):
        EBook.objects.filter(pk=self.book.pk).update(price=0)
        response = self.api.post(self.url('book-get-free'))
        self.assertEqual(response.status_code, 201, response.data)

    def provider_payment(self):
        order = prepare_book_order(self.reader, self.book.pk)
        order.provider = 'test-provider'
        order.provider_reference = 'provider-session'
        order.save(update_fields=['provider', 'provider_reference'])
        return order, VerifiedBookPayment(order.reference, order.provider, order.provider_reference, 'receipt-1', order.amount, order.currency, 'paid')

    def test_saved_is_idempotent_private_and_independent_of_reading(self):
        url = self.url('book-save')
        self.assertEqual(self.api.post(url).data, {'is_saved': True})
        self.assertEqual(self.api.post(url).status_code, 200)
        self.assertEqual(SavedBook.objects.count(), 1)
        self.assertTrue(self.detail()['is_saved'])
        self.assertEqual(self.api.get(self.url('book-chapters')).status_code, 403)
        self.api.force_authenticate(self.other)
        self.assertFalse(self.detail()['is_saved'])
        self.assertEqual(self.api.get(reverse('api-book-saved')).data['count'], 0)
        self.assertEqual(self.api.delete(url).status_code, 204)
        self.api.force_authenticate(self.reader)
        self.assertEqual(self.api.get(reverse('api-book-saved')).data['count'], 1)
        EBook.objects.filter(pk=self.book.pk).update(is_published=False)
        self.assertEqual(self.api.get(reverse('api-book-saved')).data['count'], 0)
        self.assertEqual(self.api.post(url).status_code, 404)
        self.assertEqual(self.api.delete(url).status_code, 204)
        self.assertEqual(self.api.delete(url).status_code, 204)
        self.api.force_authenticate(None)
        self.assertEqual(self.api.post(url).status_code, 401)

    def test_reviews_are_validated_private_and_moderatable(self):
        url = self.url('book-reviews')
        self.assertEqual(self.api.post(url, {'rating': 5}).status_code, 403)
        self.make_free()
        for payload in ({'rating': 0}, {'rating': 6}, {'rating': 4, 'review': 'a' * 2001}):
            self.assertEqual(self.api.post(url, payload).status_code, 400)
        response = self.api.post(url, {'rating': 4, 'review': 'Helpful'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.api.post(url, {'rating': 5}).status_code, 409)
        review_id = response.data['id']
        review_url = self.url('book-review', self.book.pk, review_id)
        self.assertEqual(self.api.patch(review_url, {'rating': 5}).status_code, 200)
        self.assertEqual(self.detail()['current_user_review']['id'], review_id)
        self.assertEqual(self.detail()['average_rating'], 5)
        self.api.force_authenticate(self.other)
        self.assertEqual(self.api.patch(review_url, {'rating': 1}).status_code, 404)
        self.assertEqual(self.api.delete(review_url).status_code, 404)
        self.assertNotIn('user', self.api.get(url).data['results'][0])
        dashboard = reverse('manage_book_commerce')
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(dashboard, {'action': 'hide', 'review_id': review_id}).status_code, 403)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(dashboard, {'section': 'reviews'}), 'Helpful')
        self.assertEqual(self.client.post(dashboard, {'action': 'hide', 'review_id': review_id}).status_code, 302)
        self.assertTrue(BookReview.objects.get(pk=review_id).is_hidden)
        self.assertEqual(self.api.get(url).data['count'], 0)
        self.assertEqual(self.detail()['review_count'], 0)
        self.api.force_authenticate(self.reader)
        self.assertEqual(self.api.delete(review_url).status_code, 204)

    def test_catalogue_filters_and_legacy_shape(self):
        EBook.objects.create(title='Legacy', uploaded_by=self.owner, is_published=True, file_url='https://private.example/legacy')
        self.make_free()
        self.api.post(self.url('book-reviews'), {'rating': 4})
        catalogue = reverse('api-ebook-list-create')
        self.assertEqual(self.api.get(catalogue, {'subject': '1', 'grade': '1'}).status_code, 200)
        result = self.api.get(catalogue, {
            'search': 'writer', 'category': 'math', 'difficulty': 'beginner', 'pricing': 'free',
            'min_rating': '3.50', 'max_price': '1', 'ordering': 'highest_rated',
        })
        self.assertEqual([row['id'] for row in result.data], [self.book.pk])
        self.assertEqual(self.api.get(catalogue, {'pricing': 'free', 'page': 1}).data['count'], 1)
        self.assertEqual(self.api.get(catalogue, {'min_price': 3, 'max_price': 2}).status_code, 400)
        self.assertEqual(self.detail()['file_url'], '')
        self.assertNotIn('source_file', self.detail())

    def test_checkout_disabled_and_order_snapshot_ignores_client_amount(self):
        url = self.url('book-buy')
        self.assertEqual(self.api.post(url, {'amount': '0.01', 'currency': 'USD'}).status_code, 503)
        self.assertFalse(BookOrder.objects.exists())
        order = prepare_book_order(self.reader, self.book.pk)
        EBook.objects.filter(pk=self.book.pk).update(price=Decimal('300'))
        self.assertEqual(prepare_book_order(self.reader, self.book.pk).pk, order.pk)
        order.amount = Decimal('0.01')
        with self.assertRaises(ValidationError):
            order.save(update_fields=['amount'])
        with self.assertRaises(IntegrityError), transaction.atomic():
            BookOrder.objects.create(user=self.reader, book=self.book, amount=100, original_price=100)
        self.assertEqual(self.api.get(self.url('book-order', order.pk)).data['amount'], '100.00')
        self.api.force_authenticate(self.other)
        self.assertEqual(self.api.get(self.url('book-order', order.pk)).status_code, 404)
        self.assertEqual(self.api.get(reverse('api-book-orders')).data['count'], 0)
        self.assertEqual(self.api.patch(self.url('book-order', order.pk), {'status': 'paid'}).status_code, 405)
        EBook.objects.filter(pk=self.book.pk).update(price=None)
        self.assertEqual(self.api.post(url).status_code, 409)
        self.assertEqual(self.api.post(self.url('book-get-free')).status_code, 409)
        EBook.objects.filter(pk=self.book.pk).update(is_published=False)
        self.assertEqual(self.api.post(url).status_code, 404)

    def test_acquisition_and_order_preparation_require_real_content(self):
        BookChapter.objects.filter(pk=self.chapter.pk).update(content=' \n ')
        EBook.objects.filter(pk=self.book.pk).update(price=0)
        response = self.api.post(self.url('book-get-free'))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'BOOK_UNAVAILABLE')
        EBook.objects.filter(pk=self.book.pk).update(price=100)
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            prepare_book_order(self.reader, self.book.pk)
        BookChapter.objects.filter(pk=self.chapter.pk).update(content='A real chapter.')
        EBook.objects.filter(pk=self.book.pk).update(price=0)
        self.assertEqual(self.api.post(self.url('book-get-free')).status_code, 201)
        EBook.objects.filter(pk=self.book.pk).update(price=100)
        with self.assertRaisesRegex(ValueError, 'already has access'):
            prepare_book_order(self.reader, self.book.pk)
        BookChapter.objects.filter(pk=self.chapter.pk).update(content='')
        with TemporaryDirectory() as root, override_settings(BOOK_PRIVATE_ROOT=Path(root) / 'private'):
            self.assertEqual(self.api.post(self.url('book-get-free')).status_code, 409)
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                prepare_book_order(self.reader, self.book.pk)
            self.book.source_file = pdf()
            self.book.save()
            order = prepare_book_order(self.other, self.book.pk)
            self.assertEqual(order.book_id, self.book.pk)
            from .book_reader import book_has_usable_content
            self.book.source_file.name = 'content/../../outside.pdf'
            self.assertFalse(book_has_usable_content(self.book))

    def test_free_entitlement_survives_pending_order_settlement_and_refund(self):
        order, payment = self.provider_payment()
        EBook.objects.filter(pk=self.book.pk).update(price=0)
        free = self.api.post(self.url('book-get-free'))
        self.assertEqual(free.status_code, 201, free.data)
        self.assertEqual(self.api.post(self.url('book-get-free')).status_code, 200)
        free_grant = BookEntitlement.objects.get(user=self.reader, book=self.book, source='free')
        fulfill_verified_payment(payment)
        fulfill_verified_payment(payment)
        self.assertEqual(BookEntitlement.objects.filter(user=self.reader, book=self.book).count(), 2)
        paid_grant = BookEntitlement.objects.get(order=order)
        self.assertEqual(paid_grant.source, 'purchase')
        self.assertIsNone(free_grant.revoked_at)
        refund = replace(payment, status='refunded')
        refund_verified_order(refund)
        refund_verified_order(refund)
        free_grant.refresh_from_db()
        paid_grant.refresh_from_db()
        self.assertIsNone(free_grant.revoked_at)
        self.assertIsNotNone(paid_grant.revoked_at)
        self.assertTrue(self.detail()['has_reading_access'])
        self.assertEqual(self.api.get(self.url('book-chapters')).status_code, 200)

    def test_subject_grade_filter_ids_are_bounded_validation_errors(self):
        catalogue = reverse('api-ebook-list-create')
        for field in ('subject', 'grade'):
            for value in ('-1', 'abc', '999999999999999999999999999999999999999999999'):
                response = self.api.get(catalogue, {field: value})
                self.assertEqual(response.status_code, 400, (field, value, response.data))
                self.assertIn(field, response.data)

    def test_catalogue_availability_matches_free_acquisition_content_check(self):
        catalogue = reverse('api-ebook-list-create')

        def action_for(book):
            response = self.api.get(catalogue, {'search': book.title})
            self.assertEqual(response.status_code, 200, response.data)
            row = next(row for row in response.data if row['id'] == book.pk)
            return row['available_action']

        EBook.objects.filter(pk=self.book.pk).update(price=0)
        BookChapter.objects.filter(pk=self.chapter.pk).update(content=' \n\t')
        self.book.refresh_from_db()
        self.assertEqual(action_for(self.book), 'unavailable')
        self.assertEqual(self.api.post(self.url('book-get-free')).status_code, 409)

        BookChapter.objects.filter(pk=self.chapter.pk).update(content='Readable chapter text.')
        self.assertEqual(action_for(self.book), 'get_free')
        self.assertEqual(self.api.post(self.url('book-get-free')).status_code, 201)

        file_book = EBook.objects.create(
            title='File-only book', uploaded_by=self.owner, price=0, is_published=True,
            file_url='https://private.example/file-only.pdf',
        )
        BookChapter.objects.create(book=file_book, chapter_number=1, title='Empty')
        with TemporaryDirectory() as root, override_settings(BOOK_PRIVATE_ROOT=Path(root) / 'private'):
            EBook.objects.filter(pk=file_book.pk).update(source_file='content/missing.pdf')
            file_book.refresh_from_db()
            self.assertEqual(action_for(file_book), 'unavailable')
            self.assertEqual(self.api.post(self.url('book-get-free', file_book.pk)).status_code, 409)
            EBook.objects.filter(pk=file_book.pk).update(price=100)
            self.assertEqual(self.api.post(self.url('book-buy', file_book.pk)).status_code, 409)
            EBook.objects.filter(pk=file_book.pk).update(price=0)

            file_book.source_file = pdf()
            file_book.save()
            self.assertEqual(action_for(file_book), 'get_free')
            self.assertEqual(self.api.post(self.url('book-get-free', file_book.pk)).status_code, 201)

    def test_continue_reading_query_count_is_bounded_for_1_10_20_books(self):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        from django.utils import timezone
        for total in (1, 10, 20):
            EBook.objects.filter(pk=self.book.pk).update(price=0)
            books = [self.book]
            for i in range(total - 1):
                books.append(EBook.objects.create(title=f'Continue {total}-{i}', uploaded_by=self.owner,
                    price=0, is_published=True, file_url=f'https://private.example/{total}-{i}.pdf'))
            for book in books:
                BookEntitlement.objects.get_or_create(user=self.reader, book=book,
                    defaults={'source': BookEntitlement.Source.FREE})
                BookReadingProgress.objects.get_or_create(user=self.reader, book=book,
                    defaults={'last_read_at': timezone.now()})
            with CaptureQueriesContext(connection) as captured:
                response = self.api.get(reverse('api-reader-continue'))
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(len(response.data['books']), total)
            if total == 1:
                baseline = len(captured)
            else:
                self.assertLessEqual(len(captured), baseline + 2, (total, len(captured), baseline))

    def test_pending_failed_mismatched_and_reused_provider_evidence(self):
        order, payment = self.provider_payment()
        self.assertEqual(self.api.get(self.url('book-chapters')).status_code, 403)
        for changed in (
            replace(payment, amount=Decimal('99.99')), replace(payment, currency='USD'),
            replace(payment, provider_reference='unknown'), replace(payment, status='pending'),
            replace(payment, transaction_id=''),
        ):
            with self.assertRaises(ValueError):
                fulfill_verified_payment(changed)
        order.status = 'failed'
        order.save(update_fields=['status'])
        with self.assertRaises(ValueError):
            fulfill_verified_payment(payment)
        self.assertFalse(BookEntitlement.objects.exists())
        self.assertEqual(self.api.get(self.url('book-chapters')).status_code, 403)
        order.status = 'processing'
        order.save(update_fields=['status'])
        fulfill_verified_payment(payment)
        other_order = prepare_book_order(self.other, self.book.pk)
        other_order.provider = order.provider
        other_order.provider_reference = 'different-session'
        other_order.save(update_fields=['provider', 'provider_reference'])
        with self.assertRaises(ValueError):
            fulfill_verified_payment(replace(payment, order_reference=other_order.reference, provider_reference=other_order.provider_reference))
        other_order.refresh_from_db()
        self.assertEqual(other_order.status, 'pending')
        self.assertEqual(BookEntitlement.objects.count(), 1)

    def test_verified_fulfillment_replay_refund_and_management_boundary(self):
        order, payment = self.provider_payment()
        fulfill_verified_payment(payment)
        fulfill_verified_payment(payment)
        self.assertEqual(BookEntitlement.objects.filter(order=order).count(), 1)
        self.assertTrue(self.detail()['is_purchased'])
        self.assertEqual(self.detail()['available_action'], 'read_now')
        self.assertEqual(self.api.get(self.url('book-chapter', self.book.pk, self.chapter.pk)).status_code, 200)
        for name, args in (
            ('book-chapters', [self.book.pk]), ('book-reorder', [self.book.pk]), ('book-import', [self.book.pk]),
            ('book-pdf-extract', [self.book.pk, self.chapter.pk]),
        ):
            self.assertEqual(self.api.post(self.url(name, *args), {}).status_code, 403)
        self.assertEqual(self.api.patch(self.url('book-chapter', self.book.pk, self.chapter.pk), {'title': 'Override'}).status_code, 403)
        self.assertEqual(self.api.patch(self.url('ebook-detail'), {'title': 'Override'}).status_code, 403)
        with self.assertRaises(ValueError):
            prepare_book_order(self.reader, self.book.pk)
        refund_verified_order(replace(payment, status='refunded'))
        refund_verified_order(replace(payment, status='refunded'))
        self.assertFalse(self.detail()['has_reading_access'])
        self.assertEqual(self.api.get(self.url('book-chapters')).status_code, 403)
        with self.assertRaises(ValueError):
            fulfill_verified_payment(payment)
        self.api.force_authenticate(self.owner)
        self.assertEqual(self.api.delete(self.url('ebook-detail')).status_code, 409)
        self.assertTrue(BookOrder.objects.filter(pk=order.pk, status='refunded').exists())

    def test_free_library_progress_and_unpublication(self):
        EBook.objects.filter(pk=self.book.pk).update(price=0)
        self.assertEqual(self.detail()['available_action'], 'get_free')
        self.assertEqual(self.api.get(self.url('book-chapters')).status_code, 403)
        self.make_free()
        self.assertEqual(self.api.post(self.url('book-get-free')).status_code, 200)
        self.assertFalse(BookOrder.objects.exists())
        library = reverse('api-book-library')
        initial = self.api.get(library, {'status': 'not_started'})
        self.assertEqual(initial.status_code, 200, initial.data)
        self.assertEqual(initial.data['results'][0]['completion_status'], 'not_started')
        progress = self.url('book-progress')
        self.assertEqual(self.api.put(progress, {'chapter_id': self.chapter.pk}, format='json').status_code, 200)
        self.assertEqual(self.detail()['available_action'], 'continue_reading')
        self.assertEqual(self.api.get(library, {'status': 'in_progress'}).data['count'], 1)
        self.assertEqual(len(self.api.get(reverse('api-reader-continue')).data['books']), 1)
        self.api.put(progress, {'chapter_id': self.chapter.pk, 'completed': True}, format='json')
        completed = self.api.get(library, {'status': 'completed'})
        self.assertEqual(completed.data['results'][0]['reading_progress']['overall_percentage'], 100)
        self.assertEqual(self.detail()['available_action'], 'read_now')
        self.api.force_authenticate(self.other)
        self.assertEqual(self.api.get(library).data['count'], 0)
        self.api.force_authenticate(self.reader)
        EBook.objects.filter(pk=self.book.pk).update(is_published=False)
        self.assertEqual(self.api.get(progress).status_code, 403)
        self.assertEqual(self.api.get(library).data['count'], 0)

    def test_paid_private_file_and_bookmark_access_ends_on_revocation(self):
        with TemporaryDirectory() as root, override_settings(BOOK_PRIVATE_ROOT=Path(root) / 'private'):
            self.book.source_file = pdf()
            self.book.file_format = 'pdf'
            self.book.save()
            url = self.url('ebook-content')
            self.assertEqual(self.api.get(url).status_code, 403)
            order, payment = self.provider_payment()
            fulfill_verified_payment(payment)
            response = self.api.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Cache-Control'], 'private, no-store')
            self.assertEqual(b''.join(response.streaming_content), PDF)
            response.close()
            bookmarks = self.url('book-bookmarks')
            self.assertEqual(self.api.post(bookmarks, {'chapter_id': self.chapter.pk}, format='json').status_code, 201)
            self.api.force_authenticate(self.other)
            self.assertEqual(self.api.get(bookmarks).status_code, 403)
            self.api.force_authenticate(self.reader)
            refund_verified_order(replace(payment, status='refunded'))
            self.assertEqual(self.api.get(url).status_code, 403)
            self.assertEqual(self.api.get(bookmarks).status_code, 403)
