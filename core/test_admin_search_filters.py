from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    BookOrder, BootcampProfile, Course, District, EBook, Event, Grade,
    Municipality, Province, Role, School, User,
)


class AdminSearchFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            email='admin-filters@example.com', name='Filter Admin',
            role=Role.objects.get(name='super_admin'),
        )
        cls.instructor = User.objects.create_user(
            email='instructor-filters@example.com', name='Ada Lovelace',
            role=Role.objects.get(name='instructor'),
        )
        cls.student = User.objects.create_user(
            email='student-filters@example.com', name='Filter Student',
            role=Role.objects.get(name='student'),
        )
        cls.event_province = Province.objects.create(name='Admin Filter Province')
        cls.event_district = District.objects.create(name='Admin Filter District', province=cls.event_province)

    def setUp(self):
        self.client.force_login(self.admin)

    def course(self, title, **overrides):
        fields = {
            'title': title, 'instructor': self.instructor, 'course_type': 'skill',
            'description': '', 'is_published': False, 'is_paid': False,
        }
        fields.update(overrides)
        return Course.objects.create(**fields)

    def bootcamp(self, title, **profile_fields):
        course = self.course(title, course_type='bootcamp')
        defaults = {
            'venue_name': 'City Hall', 'days': 2,
            'starts_on': date(2026, 5, 10), 'ends_on': date(2026, 5, 11),
            'status': 'upcoming',
        }
        defaults.update(profile_fields)
        BootcampProfile.objects.create(course=course, **defaults)
        return course

    def event(self, title, **overrides):
        start = timezone.now() + timedelta(days=30)
        fields = {
            'title': title, 'description': '', 'created_by': self.admin,
            'start_at': start, 'end_at': start + timedelta(hours=2),
            'venue_name': 'Main Hall', 'city': 'Kathmandu', 'is_published': False,
            'district': self.event_district,
        }
        fields.update(overrides)
        return Event.objects.create(**fields)

    def test_courses_search_combined_filters_invalid_values_and_pagination(self):
        self.course('Python systems', description='Build an interpreter', is_published=True, is_paid=True)
        self.course('Python practice', is_published=False, is_paid=False)
        self.course('Design systems', course_type='academic', is_published=True, is_paid=True)

        response = self.client.get(reverse('manage_courses'), {
            'q': 'PYTHON', 'type': 'skill', 'publication': 'published', 'price': 'paid',
        })
        self.assertEqual(response.context['courses'].paginator.count, 1)
        self.assertEqual(response.context['courses'][0].title, 'Python systems')
        self.assertContains(response, f'href="{reverse("manage_courses")}">Reset</a>')

        invalid = self.client.get(reverse('manage_courses'), {
            'type': 'unknown', 'publication': 'unknown', 'price': 'unknown',
        })
        self.assertEqual(invalid.context['courses'].paginator.count, 3)

        for number in range(26):
            self.course(f'Pageable course {number:02}', is_published=True, is_paid=True)
        page = self.client.get(reverse('manage_courses'), {
            'q': 'Pageable', 'type': 'skill', 'publication': 'published', 'price': 'paid', 'page': '2',
        })
        self.assertEqual((page.context['courses'].number, page.context['courses'].paginator.count), (2, 26))
        self.assertNotIn('page=', page.context['query_string'])
        for param in ('q=Pageable', 'type=skill', 'publication=published', 'price=paid'):
            self.assertIn(param, page.context['query_string'])

    def test_bootcamp_search_status_publication_dates_and_pagination(self):
        matching = self.bootcamp('AI Foundations', venue_name='North Hall', status='ongoing', starts_on=date(2026, 6, 1), ends_on=date(2026, 6, 2))
        matching.is_published = True
        matching.save(update_fields=['is_published'])
        self.bootcamp('AI Foundations Draft', venue_name='South Hall', status='upcoming')
        self.bootcamp('Design Workshop', venue_name='North Hall', status='ongoing')

        response = self.client.get(reverse('manage_bootcamps'), {
            'q': 'NORTH', 'status': 'ongoing', 'publication': 'published',
            'start_after': '2026-05-01', 'start_before': '2026-06-30',
        })
        self.assertEqual(response.context['bootcamps'].paginator.count, 1)
        self.assertEqual(response.context['bootcamps'][0].title, 'AI Foundations')
        self.assertContains(response, f'href="{reverse("manage_bootcamps")}">Reset</a>')
        self.assertContains(response, 'Instructors')
        self.assertContains(response, 'Enrolled students')

        for number in range(26):
            self.bootcamp(f'Paged bootcamp {number:02}')
        page = self.client.get(reverse('manage_bootcamps'), {'q': 'Paged', 'page': 2})
        self.assertEqual((page.context['bootcamps'].number, page.context['bootcamps'].paginator.count), (2, 26))
        self.assertIn('q=Paged', page.context['query_string'])
        self.assertNotIn('page=', page.context['query_string'])

        invalid = self.client.get(reverse('manage_bootcamps'), {'status': 'invalid', 'publication': 'invalid'})
        self.assertEqual(invalid.context['filters']['status'], '')
        self.assertEqual(invalid.context['filters']['publication'], '')

    def test_events_search_publication_dates_and_pagination(self):
        now = timezone.now()
        self.event('Summer Skills', description='Creative workshop', is_published=True,
                   start_at=now + timedelta(days=12), end_at=now + timedelta(days=12, hours=2))
        self.event('Autumn Meetup', city='Pokhara')

        response = self.client.get(reverse('manage_events'), {
            'q': 'CREATIVE', 'publication': 'published',
            'start_after': (now + timedelta(days=10)).date().isoformat(),
            'start_before': (now + timedelta(days=15)).date().isoformat(),
        })
        self.assertEqual(response.context['events'].paginator.count, 1)
        self.assertEqual(response.context['events'][0].title, 'Summer Skills')
        self.assertContains(response, f'href="{reverse("manage_events")}">Reset</a>')

        for number in range(26):
            self.event(f'Paged event {number:02}')
        page = self.client.get(reverse('manage_events'), {'q': 'Paged', 'page': 2})
        self.assertEqual((page.context['events'].number, page.context['events'].paginator.count), (2, 26))
        self.assertIn('q=Paged', page.context['query_string'])
        self.assertNotIn('page=', page.context['query_string'])
        self.assertContains(page, 'name="is_published"')

    def test_geography_search_preserves_hierarchy_and_paginates_each_list(self):
        province = Province.objects.create(name='West Province')
        district = District.objects.create(name='River District', province=province)
        municipality = Municipality.objects.create(name='Green Municipality', district=district)
        School.objects.create(name='Green School', sector='public', municipality=municipality)
        School.objects.create(name='Blue School', sector='private', municipality=municipality)
        Grade.objects.create(name='Audit Grade Seven')
        Grade.objects.create(name='Audit Grade Eight')

        response = self.client.get(reverse('manage_geography'), {
            'province_q': 'west', 'district_q': 'West Province',
            'municipality_q': 'River District', 'school_q': 'public', 'grade_q': 'Eight',
        })
        self.assertEqual(response.context['province_count'], 1)
        self.assertEqual(response.context['district_count'], 1)
        self.assertEqual(response.context['municipality_count'], 1)
        self.assertEqual(response.context['school_count'], 1)
        self.assertEqual(response.context['grade_count'], 1)
        self.assertContains(response, 'Clear')
        self.assertContains(response, 'West Province')
        self.assertContains(response, 'River District')
        self.assertContains(response, 'Green Municipality')
        self.assertContains(response, 'Green School')

        for number in range(21):
            Grade.objects.create(name=f'Paged geography grade {number:02}')
        page = self.client.get(reverse('manage_geography'), {
            'grade_q': 'Paged', 'grade_page': 2, 'province_q': 'west',
        })
        self.assertEqual((page.context['grades'].number, page.context['grade_count']), (2, 21))
        self.assertIn('province_q=west', page.context['geo_controls']['grade']['page_query'])
        self.assertIn(('grade_page', '2'), page.context['geo_controls']['province']['hidden'])
        self.assertContains(page, 'name="form_type" value="province"')

    def test_geography_crud_post_still_works_with_search_controls(self):
        response = self.client.post(reverse('manage_geography'), {
            'form_type': 'province', 'province-name': 'Added Province',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Province.objects.filter(name='Added Province').exists())

    def test_books_and_commerce_reset_controls_and_order_reference_search(self):
        book = EBook.objects.create(
            title='Searchable Geometry', uploaded_by=self.instructor, price=Decimal('100.00'),
            is_published=True, file_url='https://example.com/geometry.pdf',
        )
        order = BookOrder.objects.create(
            user=self.student, book=book, original_price=Decimal('100.00'), amount=Decimal('100.00'),
        )
        books = self.client.get(reverse('manage_books'), {'q': 'searchable'})
        self.assertContains(books, f'href="{reverse("manage_books")}">Clear filters</a>')

        order_search = str(order.reference)
        commerce = self.client.get(reverse('manage_book_commerce'), {
            'section': 'orders', 'q': order_search, 'status': 'pending',
        })
        self.assertEqual(commerce.context['page'].paginator.count, 1)
        self.assertContains(commerce, f'?section=reviews&amp;q={order_search}')
        self.assertNotContains(commerce, f'?section=reviews&amp;q={order_search}&amp;status=')
        self.assertContains(commerce, f'href="?section=orders">Reset</a>')

        invalid = self.client.get(reverse('manage_book_commerce'), {'section': 'orders', 'status': 'invalid'})
        self.assertEqual(invalid.context['status'], '')
        self.assertEqual(invalid.context['page'].paginator.count, 1)

    def test_search_pages_remain_admin_only(self):
        for route in ('manage_courses', 'manage_bootcamps', 'manage_events', 'manage_geography'):
            with self.subTest(route=route):
                self.client.force_login(self.student)
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 302)
                self.client.force_login(self.admin)
