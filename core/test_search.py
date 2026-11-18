from datetime import timedelta

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Course, Enrollment, InstructorProfile, LearningInterest, Role, SearchQuery, Short, User


class SearchSetup(TestCase):
    def setUp(self):
        cache.clear()
        self.coding = LearningInterest.objects.get(slug='coding')
        self.sarah = self.instructor('sarah@example.com', 'Sarah Codes', 'Python and data expert')
        self.alex = self.instructor('alex@example.com', 'Alex Dev', 'Frontend engineer')
        self.python = Course.objects.create(title='Python Data Science', instructor=self.sarah, course_type='skill',
            skill_category=self.coding, level='beginner', is_published=True)
        self.react = Course.objects.create(title='React Architecture', description='Hooks, state and patterns',
            instructor=self.alex, course_type='skill', level='advanced', is_published=True)
        self.draft = Course.objects.create(title='React Draft', instructor=self.alex, course_type='skill')
        self.student = self.make_student()
        self.client = APIClient()
        self.client.force_authenticate(self.student)

    def instructor(self, email, name, qualification, verified=True):
        user = User.objects.create_user(email=email, name=name, role=Role.objects.get(name='instructor'),
            verification_status='verified' if verified else 'pending')
        InstructorProfile.objects.create(user=user, qualification=qualification)
        return user

    def make_student(self):
        n = User.objects.count()
        return User.objects.create_user(email=f'student{n}@example.com', name=f'Student {n}', role=Role.objects.get(name='student'))

    def enroll(self, course, days_ago=1):
        enrollment = Enrollment.objects.create(student=self.make_student(), course=course, status='active')
        Enrollment.objects.filter(pk=enrollment.pk).update(enrolled_at=timezone.now() - timedelta(days=days_ago))

    def search(self, expect=200, **params):
        response = self.client.get('/api/v1/search/', params)
        self.assertEqual(response.status_code, expect, getattr(response, 'data', None))
        return response.data

    def discover(self):
        response = self.client.get('/api/v1/search/discover/')
        self.assertEqual(response.status_code, 200)
        return response.data


class SearchDiscoverTests(SearchSetup):
    def test_popular_courses_rank_by_recent_students_and_skip_drafts(self):
        self.enroll(self.react)
        self.enroll(self.react)
        for _ in range(3):
            self.enroll(self.python, days_ago=60)  # old: does not count as recent
        cards = self.discover()['popular_courses']
        self.assertEqual([c['id'] for c in cards], [self.react.pk, self.python.pk])
        for key in ('title', 'thumbnail_url', 'average_rating', 'level', 'is_enrolled', 'instructor_name'):
            self.assertIn(key, cards[0])
        self.assertEqual(cards[0]['level'], 'advanced')

    def test_trending_creators_are_verified_instructors_ranked_by_recent_students(self):
        self.instructor('pending@example.com', 'Pending Person', 'x', verified=False)
        Course.objects.create(title='Pending course', instructor=User.objects.get(email='pending@example.com'),
            course_type='skill', is_published=True)
        self.enroll(self.react)
        creators = self.discover()['trending_creators']
        self.assertEqual([c['id'] for c in creators], [self.alex.pk, self.sarah.pk])
        self.assertEqual(set(creators[0]) >= {'name', 'profile_photo_url', 'qualification', 'total_students'}, True)

    def test_trending_falls_back_to_real_topics_without_history(self):
        self.assertEqual(self.discover()['trending_searches'], ['Coding'])

    def test_trending_needs_two_people_and_a_result(self):
        other = self.make_student()
        self.search(q='react')
        self.assertEqual(self.discover()['trending_searches'], ['Coding'])  # one person is not a trend
        self.client.force_authenticate(other)
        self.search(q='  React ')
        for user in (self.student, other):
            self.client.force_authenticate(user)
            self.search(q='zzqx nothing')                               # no results never trends
        self.assertEqual(self.discover()['trending_searches'], ['React', 'Coding'])

    def test_trending_window_and_limit(self):
        users = [self.make_student() for _ in range(2)]
        terms = ['python', 'react', 'data', 'science', 'hooks', 'architecture', 'patterns']
        for user in users:
            for term in terms:
                SearchQuery.objects.create(user=user, query=term.title(), normalized=term, results_count=1)
        SearchQuery.objects.filter(normalized='patterns').update(created_at=timezone.now() - timedelta(days=8))
        trending = self.discover()['trending_searches']
        self.assertEqual(len(trending), 6)
        self.assertNotIn('Patterns', trending)
        self.assertNotIn('Coding', trending)


class RecentSearchTests(SearchSetup):
    url = '/api/v1/search/recent/'

    def searched(self, user, query, minutes_ago):
        row = SearchQuery.objects.create(user=user, query=query, normalized=' '.join(query.lower().split()), results_count=0)
        SearchQuery.objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(minutes=minutes_ago))

    def test_newest_first_distinct_own_and_in_discover(self):
        self.searched(self.student, 'react', 30)
        self.searched(self.student, 'Python', 20)
        self.searched(self.student, 'React', 10)          # same search again, new spelling
        self.searched(self.make_student(), 'secret', 5)   # someone else's
        expected = ['React', 'Python']
        self.assertEqual(self.client.get(self.url).data['recent_searches'], expected)
        self.assertEqual(self.discover()['recent_searches'], expected)

    def test_a_search_shows_up_even_without_results_and_list_is_capped(self):
        self.search(q='zzqx nothing')
        self.assertEqual(self.client.get(self.url).data['recent_searches'], ['zzqx nothing'])
        for i in range(12):
            self.searched(self.student, f'term {i}', 100 - i)
        self.assertEqual(len(self.client.get(self.url).data['recent_searches']), 10)

    def test_remove_one_or_clear_all_only_touches_own_history(self):
        other = self.make_student()
        self.searched(self.student, 'React', 10)
        self.searched(self.student, 'react ', 30)
        self.searched(self.student, 'Python', 20)
        self.searched(other, 'React', 5)
        response = self.client.delete(self.url + '?q=REACT')
        self.assertEqual((response.status_code, response.data['recent_searches']), (200, ['Python']))
        self.assertEqual(self.client.delete(self.url + '?q=%20').status_code, 400)
        self.assertEqual(self.client.delete(self.url).data['recent_searches'], [])
        self.assertFalse(SearchQuery.objects.filter(user=self.student).exists())
        self.assertEqual(SearchQuery.objects.filter(user=other).count(), 1)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)


class SearchResultTests(SearchSetup):
    def test_courses_creators_and_shorts(self):
        Short.objects.create(title='Flexbox in 60s', caption='Layouts #css', instructor=self.alex,
            video_url='https://example.com/v', is_published=True)
        Short.objects.create(title='Draft CSS', caption='#css', instructor=self.alex, video_url='https://example.com/d')
        body = self.search(q='react')
        self.assertEqual([c['id'] for c in body['courses']], [self.react.pk])
        self.assertEqual(body['counts'], {'courses': 1, 'creators': 0, 'shorts': 0})
        body = self.search(q='sarah')
        self.assertEqual([c['id'] for c in body['creators']], [self.sarah.pk])
        self.assertEqual([c['id'] for c in body['courses']], [self.python.pk])     # by instructor name
        self.assertEqual([c['id'] for c in self.search(q='frontend')['creators']], [self.alex.pk])
        body = self.search(q='#CSS')
        self.assertEqual([s['title'] for s in body['shorts']], ['Flexbox in 60s'])

    def test_every_word_must_match_somewhere_and_titles_rank_first(self):
        self.assertEqual([c['id'] for c in self.search(q='react hooks')['courses']], [self.react.pk])
        self.assertEqual(self.search(q='react python')['counts']['courses'], 0)
        hooks = Course.objects.create(title='Hooks in depth', instructor=self.alex, course_type='skill', is_published=True)
        self.assertEqual([c['id'] for c in self.search(q='hooks')['courses']], [hooks.pk, self.react.pk])
        self.assertEqual([c['id'] for c in self.search(q='coding')['courses']], [self.python.pk])  # by category

    def test_type_and_paging(self):
        for i in range(3):
            Course.objects.create(title=f'Python {i}', instructor=self.sarah, course_type='skill', is_published=True)
        body = self.search(q='python', type='courses', limit=2)
        self.assertEqual(set(body), {'query', 'type', 'counts', 'courses'})
        self.assertEqual((body['counts']['courses'], len(body['courses'])), (4, 2))
        rest = self.search(q='python', type='courses', limit=2, offset=2)['courses']
        self.assertEqual(len({c['id'] for c in body['courses'] + rest}), 4)

    def test_bad_requests(self):
        for params in ({}, {'q': '   '}, {'q': 'x' * 101}, {'q': 'a', 'type': 'people'},
                       {'q': 'a', 'limit': 0}, {'q': 'a', 'limit': 51}, {'q': 'a', 'offset': -1}, {'q': 'a', 'limit': 'ten'}):
            self.search(expect=400, **params)
        self.client.force_authenticate(None)
        self.search(expect=401, q='react')

    def test_searches_are_recorded_once_per_person_and_first_page_only(self):
        self.search(q='React')
        self.search(q='react ')
        self.search(q='react', offset=10)
        row = SearchQuery.objects.get()
        self.assertEqual((row.query, row.normalized, row.results_count, row.user), ('React', 'react', 1, self.student))
        SearchQuery.objects.update(created_at=timezone.now() - timedelta(minutes=11))
        self.search(q='react')
        self.assertEqual(SearchQuery.objects.count(), 2)

    def test_query_count_does_not_grow_with_results(self):
        def queries():
            SearchQuery.objects.all().delete()  # same recording path both times
            with CaptureQueriesContext(connection) as captured:
                self.search(q='course')
            return len(captured)
        for i in range(2):
            Course.objects.create(title=f'Course {i}', instructor=self.sarah, course_type='skill', is_published=True)
        baseline = queries()
        for i in range(8):
            Course.objects.create(title=f'More course {i}', instructor=self.alex, course_type='skill', is_published=True)
        self.assertEqual(queries(), baseline)
