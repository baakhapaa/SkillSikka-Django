from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
	AdminAuditLog, BookEntitlement, BookOrder, Course, EBook, Enrollment, Event,
	EventRegistration, Payment, Role, User,
)


class AdminStage4WorkflowTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.admin_role = Role.objects.get_or_create(name='super_admin')[0]
		cls.student_role = Role.objects.get(name='student')
		cls.instructor_role = Role.objects.get(name='instructor')
		cls.admin = User.objects.create_user(
			email='stage4-admin@example.com', name='Stage Four Admin', password='pass', role=cls.admin_role,
		)
		cls.student = User.objects.create_user(
			email='stage4-student@example.com', name='Asha Learner', password='pass', role=cls.student_role,
		)
		cls.instructor = User.objects.create_user(
			email='stage4-teacher@example.com', name='Stage Four Teacher', password='pass', role=cls.instructor_role,
		)
		cls.course = Course.objects.create(
			title='Stage Four Chemistry', instructor=cls.instructor, course_type='skill',
		)
		cls.book = EBook.objects.create(
			title='Stage Four Book', uploaded_by=cls.instructor,
			file_url='https://example.test/book.pdf', price=Decimal('10.00'),
		)

	def setUp(self):
		self.client.force_login(self.admin)

	def test_verification_search_pagination_and_decision_audit(self):
		pending = [self.student]
		for index in range(26):
			pending.append(User.objects.create_user(
				email=f'pending-{index}@example.com', name=f'Pending Person {index}',
				password='pass', role=self.student_role, verification_status='pending',
			))
		User.objects.filter(pk=self.student.pk).update(verification_status='pending')

		page = self.client.get(reverse('verification_queue'), {'q': 'Pending Person'})
		self.assertEqual(page.context['pending_users'].paginator.count, 26)
		self.assertTrue(page.context['pending_users'].has_next())
		self.assertContains(page, 'page=2')
		filtered = self.client.get(reverse('verification_queue'), {'q': pending[-1].email})
		self.assertEqual(filtered.context['pending_users'].paginator.count, 1)
		self.assertContains(filtered, reverse('edit_user', args=[pending[-1].pk]))

		url = reverse('review_verification', args=[pending[-1].pk])
		response = self.client.post(url, {
			'action': 'approve', 'next': reverse('verification_queue') + '?q=Pending+Person&page=2',
		})
		self.assertRedirects(response, reverse('verification_queue') + '?q=Pending+Person&page=2', fetch_redirect_response=False)
		pending[-1].refresh_from_db()
		self.assertEqual(pending[-1].verification_status, 'verified')
		self.assertTrue(AdminAuditLog.objects.filter(
			admin=self.admin, target_user=pending[-1], action='verification_approved',
		).exists())

	def test_verification_queue_is_admin_only(self):
		self.client.force_login(self.student)
		response = self.client.get(reverse('verification_queue'))
		self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)

	def test_user_deactivation_confirmation_and_server_protections(self):
		response = self.client.get(reverse('manage_users'))
		self.assertContains(response, 'onsubmit="return confirm(')
		self.client.post(reverse('toggle_user_active', args=[self.admin.pk]), {'action': 'deactivate'})
		self.admin.refresh_from_db()
		self.assertTrue(self.admin.is_active)
		self.client.post(reverse('toggle_user_active', args=[self.student.pk]), {'action': 'deactivate'})
		self.student.refresh_from_db()
		self.assertFalse(self.student.is_active)

		inactive_admin = User.objects.create_user(
			email='inactive-admin@example.com', name='Inactive Admin', password='pass',
			role=self.admin_role, is_active=False,
		)
		self.client.force_login(inactive_admin)
		self.client.post(reverse('toggle_user_active', args=[self.admin.pk]), {'action': 'deactivate'})
		self.admin.refresh_from_db()
		self.assertTrue(self.admin.is_active)

	def test_commerce_pages_link_related_user_and_book_and_review_feedback(self):
		order = BookOrder.objects.create(
			user=self.student, book=self.book, amount=Decimal('10.00'), original_price=Decimal('10.00'),
		)
		entitlement = BookEntitlement.objects.create(
			user=self.student, book=self.book, source=BookEntitlement.Source.FREE,
		)
		from .models import BookReview
		review = BookReview.objects.create(book=self.book, user=self.student, rating=5, review='Good')
		for section in ('orders', 'entitlements'):
			response = self.client.get(reverse('manage_book_commerce'), {'section': section})
			self.assertContains(response, reverse('edit_user', args=[self.student.pk]))
			self.assertContains(response, reverse('edit_book', args=[self.book.pk]))
		response = self.client.post(reverse('manage_book_commerce'), {
			'action': 'hide', 'review_id': review.pk,
			'next': reverse('manage_book_commerce') + '?section=reviews',
		})
		self.assertRedirects(response, reverse('manage_book_commerce') + '?section=reviews', fetch_redirect_response=False)
		self.assertContains(self.client.get(response.url), 'Review hidden from readers.')
		self.assertTrue(BookOrder.objects.filter(pk=order.pk).exists())
		self.assertTrue(BookEntitlement.objects.filter(pk=entitlement.pk).exists())

	def test_payment_rows_link_student_and_filtered_course_list(self):
		enrollment = Enrollment.objects.create(student=self.student, course=self.course, status='pending_payment')
		Payment.objects.create(
			student=self.student, course=self.course, enrollment=enrollment,
			amount=Decimal('10.00'), provider='esewa', transaction_reference='stage4-ref',
		)
		response = self.client.get(reverse('manage_payments'))
		self.assertContains(response, reverse('edit_user', args=[self.student.pk]))
		self.assertContains(response, reverse('manage_courses') + '?q=Stage%20Four%20Chemistry')
		self.assertContains(response, 'Global revenue')

	def test_event_registrations_search_pagination_and_admin_permission(self):
		now = timezone.now()
		event = Event.objects.create(
			title='Stage Four Event', start_at=now + timedelta(days=1), end_at=now + timedelta(days=1, hours=1),
			created_by=self.admin,
		)
		attendees = []
		for index in range(27):
			attendee = User.objects.create_user(
				email=f'attendee-{index}@example.com', name=f'Attendee {index}',
				password='pass', role=self.student_role,
			)
			attendees.append(attendee)
			EventRegistration.objects.create(event=event, user=attendee, status='registered')
		response = self.client.get(reverse('edit_event', args=[event.pk]))
		self.assertEqual(response.context['registrations'].paginator.count, 27)
		self.assertContains(response, 'registration_page=2')
		response = self.client.get(reverse('edit_event', args=[event.pk]), {'registration_q': attendees[-1].email})
		self.assertEqual(response.context['registrations'].paginator.count, 1)
		self.assertContains(response, attendees[-1].name)
		self.client.force_login(self.student)
		self.assertRedirects(self.client.get(reverse('edit_event', args=[event.pk])), reverse('dashboard'), fetch_redirect_response=False)
