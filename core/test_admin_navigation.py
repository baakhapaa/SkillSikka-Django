from html.parser import HTMLParser

from django.test import TestCase
from django.urls import reverse

from .models import Role, User


class AdminNavigationParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        classes = values.get('class', '').split()
        if tag == 'a' and 'nav-item' in classes:
            self.items.append(values)


class AdminNavigationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            email='navigation-admin@example.com', name='Navigation Admin',
            role=Role.objects.get(name='super_admin'),
        )
        cls.student = User.objects.create_user(
            email='navigation-student@example.com', name='Navigation Student',
            role=Role.objects.get(name='student'),
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def active_navigation_items(self, response):
        parser = AdminNavigationParser()
        parser.feed(response.content.decode(response.charset))
        return [item for item in parser.items if 'active' in item.get('class', '').split()]

    def test_shared_navigation_destinations_and_single_active_state(self):
        routes = [
            ('dashboard', [], 'dashboard'),
            ('manage_users', [], 'manage_users'),
            ('manage_courses', [], 'manage_courses'),
            ('manage_books', [], 'manage_books'),
            ('manage_book_commerce', [], 'manage_book_commerce'),
            ('manage_payments', [], 'manage_payments'),
            ('manage_certificate_criteria', [], 'manage_certificate_criteria'),
        ]
        shared_destinations = [
            'verification_queue', 'manage_geography', 'manage_users', 'manage_courses',
            'manage_bootcamps', 'manage_books', 'manage_book_commerce', 'manage_events',
            'manage_banners', 'manage_payments', 'manage_streak_settings',
            'manage_certificate_criteria',
        ]

        for route, args, expected_active in routes:
            with self.subTest(route=route):
                response = self.client.get(reverse(route, args=args))
                self.assertEqual(response.status_code, 200)
                active = self.active_navigation_items(response)
                self.assertEqual(len(active), 1)
                self.assertEqual(active[0].get('aria-current'), 'page')
                self.assertIn(reverse(expected_active), active[0]['href'])
                for destination in shared_destinations:
                    self.assertContains(response, f'href="{reverse(destination)}"')

    def test_related_detail_route_keeps_parent_navigation_active(self):
        target = User.objects.create_user(
            email='navigation-target@example.com', name='Target User',
            role=Role.objects.get(name='student'),
        )
        response = self.client.get(reverse('edit_user', args=[target.pk]))
        self.assertEqual(response.status_code, 200)
        active = self.active_navigation_items(response)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].get('href'), reverse('manage_users'))
        self.assertEqual(active[0].get('aria-current'), 'page')

    def test_recent_users_anchor_is_dashboard_only_and_dashboard_has_shortcuts(self):
        dashboard = self.client.get(reverse('dashboard'))
        self.assertContains(dashboard, 'href="#users"')
        self.assertContains(dashboard, 'Recent Users')
        for route in ('manage_users', 'manage_courses'):
            response = self.client.get(reverse(route))
            self.assertNotContains(response, 'href="#users"')

        for route in (
            'manage_users', 'manage_courses', 'manage_bootcamps', 'manage_books',
            'manage_book_commerce', 'manage_payments', 'manage_certificate_criteria',
        ):
            with self.subTest(shortcut=route):
                self.assertContains(dashboard, f'href="{reverse(route)}"')

    def test_mobile_navigation_has_accessible_toggle_drawer_and_close_control(self):
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'aria-controls="admin-sidebar"')
        self.assertContains(response, 'aria-expanded="false"')
        self.assertContains(response, 'aria-label="Open admin navigation"')
        self.assertContains(response, 'id="admin-sidebar" aria-label="Admin navigation"')
        self.assertContains(response, 'aria-label="Close admin navigation"')
        self.assertContains(response, 'data-sidebar-toggle')
        self.assertContains(response, 'data-sidebar-close')

    def test_non_admin_cannot_use_admin_dashboard_or_management(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('dashboard'))
        self.assertRedirects(response, reverse('login'))
        self.client.force_login(self.student)
        response = self.client.get(reverse('manage_users'))
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
