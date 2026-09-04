from django.test import TestCase
from django.urls import reverse

from .models import Permission, Role, User


class AuthenticationFlowTests(TestCase):
	def setUp(self):
		self.role = Role.objects.get(name='school_admin')
		self.user = User.objects.create_user(
			email='admin@example.com',
			password='A-strong-password-123',
			name='Admin User',
			role=self.role,
		)

	def test_login_page_is_custom(self):
		response = self.client.get(reverse('login'))
		self.assertContains(response, 'Welcome back')
		self.assertContains(response, 'Admin access')

	def test_incomplete_onboarding_cannot_login(self):
		response = self.client.post(reverse('login'), {
			'email': self.user.email,
			'password': 'A-strong-password-123',
		})
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Complete onboarding before signing in.')
		self.assertNotIn('_auth_user_id', self.client.session)

	def test_completed_user_can_open_dashboard(self):
		self.user.onboarding_completed = True
		self.user.save(update_fields=['onboarding_completed'])
		response = self.client.post(reverse('login'), {
			'email': self.user.email,
			'password': 'A-strong-password-123',
		})
		self.assertRedirects(response, reverse('dashboard'))
		self.assertContains(self.client.get(reverse('dashboard')), 'Recent users')

	def test_role_permission_lookup(self):
		permission = Permission.objects.get(name='verify_instructor')
		self.role.role_permissions.get_or_create(permission=permission)
		self.assertTrue(self.user.has_role_permission('verify_instructor'))

	def test_superuser_is_stored_with_super_admin_role(self):
		superuser = User.objects.create_superuser(
			email='owner@example.com',
			password='A-strong-password-123',
			name='Platform Owner',
		)
		self.assertEqual(superuser.role.name, 'super_admin')
		self.assertTrue(superuser.onboarding_completed)
