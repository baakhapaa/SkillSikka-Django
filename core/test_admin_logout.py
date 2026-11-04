from pathlib import Path

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.models import Session
from django.template import RequestContext, Template
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from .models import Role, User


class AdminLogoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            email='logout-admin@example.com', name='Logout Admin',
            role=Role.objects.get(name='super_admin'),
        )

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.admin)

    def test_post_logout_flushes_session_and_redirects_to_login(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'admin/sidebar_footer.html')
        session = self.client.session
        session['private_admin_data'] = 'must be cleared'
        session.save()
        old_session_key = session.session_key
        token = self.client.cookies[settings.CSRF_COOKIE_NAME].value

        response = self.client.post(reverse('logout'), {'csrfmiddlewaretoken': token})

        self.assertRedirects(response, reverse('login'))
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertNotIn('private_admin_data', self.client.session)
        self.assertFalse(Session.objects.filter(session_key=old_session_key).exists())
        self.assertRedirects(
            self.client.get(reverse('dashboard')),
            f"{reverse('login')}?next={reverse('dashboard')}",
        )

    def test_get_logout_is_rejected_and_keeps_session(self):
        response = self.client.get(reverse('logout'))
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.headers['Allow'], 'POST')
        self.assertIn(SESSION_KEY, self.client.session)

    def test_logout_requires_valid_csrf_token(self):
        for data in ({}, {'csrfmiddlewaretoken': 'invalid'}):
            with self.subTest(data=data):
                self.assertEqual(self.client.post(reverse('logout'), data).status_code, 403)
                self.assertIn(SESSION_KEY, self.client.session)

    def test_all_dashboard_routes_require_login(self):
        anonymous = Client()
        routes = [
            ('dashboard', []), ('manage_geography', []),
            ('verification_queue', []), ('review_verification', [1]),
            ('view_document', [1]), ('manage_users', []), ('edit_user', [1]),
            ('toggle_user_active', [1]), ('manage_courses', []),
            ('manage_bootcamps', []), ('add_bootcamp', []),
            ('manage_bootcamp_instructors', [1]), ('manage_bootcamp_content', [1]),
            ('manage_events', []), ('edit_event', [1]), ('delete_event', [1]),
            ('manage_payments', []), ('recheck_payment', [1]),
            ('manage_streak_settings', []), ('manage_certificate_criteria', []),
        ]
        for name, args in routes:
            url = reverse(name, args=args)
            for method in ('get', 'post'):
                with self.subTest(route=name, method=method):
                    self.assertRedirects(
                        getattr(anonymous, method)(url),
                        f"{reverse('login')}?next={url}",
                    )

    def test_every_sidebar_renders_shared_post_logout_control(self):
        request = RequestFactory().get(reverse('dashboard'))
        request.user = self.admin
        templates = Path(settings.BASE_DIR) / 'templates' / 'admin'
        sidebar_templates = [
            path for path in templates.glob('*.html')
            if '<aside class="sidebar">' in path.read_text(encoding='utf-8')
        ]
        self.assertTrue(sidebar_templates)
        for path in sidebar_templates:
            with self.subTest(template=path.name):
                source = path.read_text(encoding='utf-8')
                self.assertIn("{% include 'admin/sidebar_footer.html' %}", source)
                sidebar = source.split('<aside class="sidebar">', 1)[1].split('</aside>', 1)[0]
                html = Template(sidebar).render(RequestContext(request))
                self.assertIn(f'method="post" action="{reverse("logout")}"', html)
                self.assertIn('name="csrfmiddlewaretoken"', html)
                self.assertIn('<span>Logout</span>', html)
                self.assertIn('class="logout-button" type="submit"', html)
                self.assertNotIn(f'href="{reverse("logout")}"', html)
