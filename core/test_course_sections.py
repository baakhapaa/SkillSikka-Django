from importlib import import_module
from io import StringIO

from django.apps import apps
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import Chapter, Course, CourseReview, Enrollment, Grade, LearningInterest, Lesson, LessonProgress, Role, StudentProfile, Subject, Topic, User


class CourseSectionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.student = self.user('student', 'student')
        self.owner = self.user('owner', 'instructor', verification_status='verified')
        self.other = self.user('other', 'instructor')
        self.admin = self.user('admin', 'super_admin')
        self.course = self.course_for('A Python introduction', description='Practical PROGRAMMING', is_paid=True, price='1299.00')
        self.lesson = Lesson.objects.create(course=self.course, title='Start', content_type='text', content_text='Protected text',
            content_url='https://example.com/private', section='Foundations', duration_seconds=252, order=1)
        self.list_url = reverse('api-course-list-create')
        self.lesson_url = reverse('api-lesson-list-create')
        self.client.force_authenticate(self.student)

    def user(self, name, role, **kwargs):
        return User.objects.create_user(email=f'{name}@example.com', name=name, role=Role.objects.get(name=role), **kwargs)

    def course_for(self, title, **kwargs):
        return Course.objects.create(title=title, instructor=self.owner, course_type='skill', is_published=True, **kwargs)

    def listing(self, **params):
        response = self.client.get(self.list_url, params)
        self.assertEqual(response.status_code, 200)
        return response.data

    def test_search(self):
        self.course_for('Unrelated')
        for search in ['python', 'PYTHON', 'programming', 'PROGRAMMING']:
            with self.subTest(search=search):
                self.assertEqual([row['id'] for row in self.listing(search=search)['results']], [self.course.pk])
        for search in ['', '   ']:
            self.assertEqual(self.listing(search=search)['count'], 2)

    def test_filters(self):
        subject = Subject.objects.create(name='Test Mathematics')
        grade = Grade.objects.first()
        category = LearningInterest.objects.get(slug='coding')
        self.course.skill_category = category
        self.course.save()
        academic = Course.objects.create(title='Academic', instructor=self.owner, course_type='academic', subject=subject, grade=grade, is_published=True)
        draft = Course.objects.create(title='Draft', instructor=self.owner, course_type='skill')
        for params, expected in [({'course_type': 'academic'}, [academic.pk]), ({'subject': subject.pk}, [academic.pk]),
                ({'grade': grade.pk}, [academic.pk]), ({'is_paid': 'true'}, [self.course.pk]),
                ({'is_paid': 'false'}, [academic.pk]), ({'skill_category': category.pk}, [self.course.pk])]:
            with self.subTest(params=params):
                self.assertEqual([r['id'] for r in self.listing(**params)['results']], expected)
        self.assertEqual(self.listing(instructor=self.owner.pk)['count'], 2)
        self.assertEqual(self.listing(instructor=self.other.pk)['count'], 0)
        self.assertEqual(self.listing(is_published='false')['count'], 0)
        self.client.force_authenticate(self.owner)
        self.assertEqual([r['id'] for r in self.listing(is_published='false')['results']], [draft.pk])
        self.assertEqual(self.listing(is_published='true')['count'], 2)

    def test_ordering(self):
        second = self.course_for('Z course', is_paid=True, price='99.00')
        CourseReview.objects.create(course=self.course, student=self.student, rating=1)
        CourseReview.objects.create(course=second, student=self.student, rating=5)
        for field in ['created_at', 'title', 'average_rating', 'price']:
            for prefix in ['', '-']:
                expected = list(Course.objects.with_review_stats().order_by(prefix + field, 'pk').values_list('pk', flat=True))
                self.assertEqual([r['id'] for r in self.listing(ordering=prefix + field)['results']], expected)
        for params in [{}, {'ordering': 'instructor'}, {'ordering': 'title,-price'}, {'ordering': ''}]:
            self.assertEqual([r['id'] for r in self.listing(**params)['results']], [second.pk, self.course.pk])

    def test_pagination_is_local(self):
        for i in range(54):
            self.course_for(f'Course {i}')
        data = self.listing()
        self.assertEqual(set(data), {'count', 'next', 'previous', 'results'})
        self.assertEqual(data['count'], 55)
        self.assertEqual(len(data['results']), 20)
        self.assertIsNone(data['previous'])
        second = self.listing(page=2)
        self.assertEqual(len(second['results']), 20)
        self.assertFalse(set(r['id'] for r in data['results']) & set(r['id'] for r in second['results']))
        self.assertEqual(len(self.listing(page_size=100)['results']), 50)
        self.assertEqual(len(self.listing(page_size=3)['results']), 3)
        self.assertEqual(self.client.get(self.list_url, {'page': 99}).status_code, 404)
        for name in ['api-lesson-list-create', 'api-my-enrollments', 'api-learning-interests']:
            self.assertIsInstance(self.client.get(reverse(name)).data, list)
        response = self.client.get(f'/api/v1/courses/{self.course.pk}/reviews/')
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data, list)
        # Events already used their own pagination before this workstream.
        response = self.client.get('/api/v1/events/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {'count', 'next', 'previous', 'results'})

    def content_responses(self):
        return [self.client.get(self.lesson_url, {'course': self.course.pk}).data[0],
                self.client.get(reverse('api-lesson-detail', args=[self.lesson.pk])).data]

    def test_paywall_all_states_both_routes(self):
        for status in [None, 'pending_payment', 'cancelled', 'active', 'completed']:
            Enrollment.objects.filter(student=self.student).delete()
            if status:
                Enrollment.objects.create(student=self.student, course=self.course, status=status)
            for row in self.content_responses():
                with self.subTest(status=status):
                    self.assertEqual(row['title'], 'Start')
                    self.assertEqual(row['section'], 'Foundations')
                    self.assertEqual(row['duration_seconds'], 252)
                    self.assertFalse(row['is_preview'])
                    self.assertEqual(row['content_text'], 'Protected text' if status in ['active', 'completed'] else None)
                    self.assertEqual(row['content_url'], 'https://example.com/private' if status in ['active', 'completed'] else None)

    def test_preview_owner_admin_other_instructor(self):
        for user, allowed in [(self.owner, True), (self.admin, True), (self.other, False), (self.student, False)]:
            self.client.force_authenticate(user)
            for row in self.content_responses():
                self.assertEqual(row['content_text'], 'Protected text' if allowed else None)
        self.lesson.is_preview = True
        self.lesson.save()
        for row in self.content_responses():
            self.assertEqual(row['content_text'], 'Protected text')

    def test_academic_topic_cannot_bypass_course_paywall(self):
        grade = Grade.objects.first()
        subject = Subject.objects.create(name='Topic subject')
        chapter = Chapter.objects.create(subject=subject, grade=grade, name='Chapter')
        topic = Topic.objects.create(chapter=chapter, name='Topic')
        self.course.course_type = 'academic'
        self.course.subject = subject
        self.course.grade = grade
        self.course.save()
        self.lesson.topic = topic
        self.lesson.save()
        StudentProfile.objects.create(user=self.student, grade=grade)
        # Batch 2: matching-grade academic students access course content without enrollment.
        self.assertEqual(self.client.get(self.lesson_url, {'topic': topic.pk}).data[0]['content_text'], 'Protected text')
        self.assertEqual(self.client.get(reverse('api-lesson-detail', args=[self.lesson.pk])).data['content_text'], 'Protected text')
        self.lesson.course = None
        self.lesson.save()
        self.assertEqual(self.client.get(self.lesson_url, {'topic': topic.pk}).data[0]['content_text'], 'Protected text')

    def test_visibility_and_legacy_null_fields(self):
        self.course.is_published = False
        self.course.save()
        self.assertEqual(self.client.get(self.lesson_url).data, [])
        self.assertEqual(self.client.get(reverse('api-lesson-detail', args=[self.lesson.pk])).status_code, 404)
        self.client.force_authenticate(self.owner)
        self.lesson.section = None
        self.lesson.duration_seconds = None
        self.lesson.save()
        row = self.content_responses()[0]
        self.assertIsNone(row['section'])
        self.assertIsNone(row['duration_seconds'])

    def test_management_fields_and_ownership(self):
        self.client.force_authenticate(self.owner)
        payload = {'course': self.course.pk, 'title': 'New', 'content_type': 'text', 'content_text': 'Example', 'section': 'Practice', 'duration_seconds': 90, 'is_preview': True, 'order': 2}
        response = self.client.post(self.lesson_url, payload)
        self.assertEqual(response.status_code, 201, response.data)
        url = reverse('api-lesson-detail', args=[response.data['id']])
        response = self.client.patch(url, {'duration_seconds': 180, 'section': None, 'is_preview': False}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['duration_seconds'], 180)
        self.assertIsNone(response.data['section'])
        self.assertFalse(response.data['is_preview'])
        self.assertEqual([r['id'] for r in self.client.get(self.lesson_url, {'course': self.course.pk}).data], [self.lesson.pk, response.data['id']])
        self.assertEqual(self.client.patch(url, {'duration_seconds': -1}).status_code, 400)
        category = LearningInterest.objects.get(slug='music')
        detail = reverse('api-course-detail', args=[self.course.pk])
        self.assertEqual(self.client.patch(detail, {'skill_category': category.pk}).data['skill_category_name'], 'Music')
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.patch(url, {'section': 'Forbidden'}).status_code, 403)
        self.assertEqual(self.client.post(self.lesson_url, payload).status_code, 403)
        self.assertEqual(self.client.patch(detail, {'skill_category': None}, format='json').status_code, 403)

    def test_aggregates_and_user_isolation(self):
        for i, status in enumerate(['active', 'completed', 'pending_payment', 'cancelled']):
            Enrollment.objects.create(student=self.user(f'learner{i}', 'student'), course=self.course, status=status)
        Lesson.objects.create(course=self.course, title='Unknown', content_type='text')
        Lesson.objects.create(course=self.course, title='Known', content_type='text', duration_seconds=48)
        for status in ['active', 'completed', 'pending_payment', 'cancelled']:
            Enrollment.objects.update_or_create(student=self.student, course=self.course, defaults={'status': status})
            for row in [self.listing()['results'][0], self.client.get(reverse('api-course-detail', args=[self.course.pk])).data]:
                self.assertEqual(row['students_enrolled'], 3 if status in ['active', 'completed'] else 2)
                self.assertEqual(row['lessons_count'], 3)
                self.assertEqual(row['total_duration_seconds'], 300)
                self.assertEqual(row['is_enrolled'], status in ['active', 'completed'])
        self.client.force_authenticate(self.other)
        self.assertFalse(self.listing()['results'][0]['is_enrolled'])
        empty = self.course_for('Empty')
        row = self.client.get(reverse('api-course-detail', args=[empty.pk])).data
        self.assertEqual(row['lessons_count'], 0)
        self.assertIsNone(row['total_duration_seconds'])
        self.course.lessons.update(duration_seconds=None)
        self.assertIsNone(self.client.get(reverse('api-course-detail', args=[self.course.pk])).data['total_duration_seconds'])

    def test_query_growth(self):
        def count(url):
            cache.clear()
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                list(response.data)
            return len(queries)
        initial_courses = count(self.list_url)
        initial_lessons = count(self.lesson_url)
        self.assertEqual(initial_courses, 2)
        self.assertEqual(initial_lessons, 2)
        for i in range(15):
            course = self.course_for(f'Growth {i}', skill_category=LearningInterest.objects.first())
            Lesson.objects.create(course=course, title='Growth lesson', content_type='text', content_text='Secret')
        self.assertEqual(count(self.list_url), initial_courses)
        self.assertEqual(count(self.lesson_url), initial_lessons)

    def test_seed_idempotency_and_catalogue(self):
        # Existing demo identity is reused, with no seeded passwords.
        self.student.email = 'student@skillsikka.com'
        self.student.save()
        for i in range(4):
            self.user(f'reviewer{i}', 'student')
        for _ in range(2):
            import_module('core.migrations.0044_seed_course_categories').seed_categories(apps, type('Schema', (), {'connection': connection})())
        self.assertEqual(LearningInterest.objects.count(), 15)
        call_command('seed_courses', stdout=StringIO())
        counts = [model.objects.count() for model in [Course, Subject, Lesson, LearningInterest, CourseReview, Enrollment, LessonProgress]]
        call_command('seed_courses', stdout=StringIO())
        self.assertEqual(counts, [model.objects.count() for model in [Course, Subject, Lesson, LearningInterest, CourseReview, Enrollment, LessonProgress]])
        self.assertGreaterEqual(Course.objects.filter(course_type='academic', is_published=True, is_paid=False).count(), 6)
        self.assertTrue(Course.objects.filter(is_paid=True, price='1299.00', is_published=True).exists())
        self.assertTrue(Course.objects.filter(is_published=True, lessons__isnull=True).exists())
        self.assertTrue(Course.objects.filter(is_published=False).exists())
        seeded = Course.objects.get(title='Python: Build Your First Project')
        self.assertEqual(seeded.lessons.values('section').distinct().count(), 3)
        self.assertEqual(set(seeded.reviews.values_list('rating', flat=True)), {1, 2, 3, 4, 5})
        self.assertTrue(seeded.lessons.filter(is_preview=True).exists())
        self.assertEqual(Enrollment.objects.get(student=self.student, course=seeded).status, 'pending_payment')
        self.assertEqual(LessonProgress.objects.filter(student=self.student).count(), 12)

    def test_course_create_category_and_optional_academic_category(self):
        self.client.force_authenticate(self.owner)
        category = LearningInterest.objects.get(slug='drawing')
        response = self.client.post(self.list_url, {'title': 'Drawing techniques', 'course_type': 'skill', 'skill_category': category.pk}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['skill_category'], category.pk)
        self.assertEqual(response.data['skill_category_name'], 'Drawing')
        subject = Subject.objects.create(name='Academic without category')
        response = self.client.post(self.list_url, {'title': 'Academic', 'course_type': 'academic', 'subject': subject.pk, 'grade': Grade.objects.first().pk}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data['skill_category'])

    def test_seed_skips_missing_demo_identity_and_does_not_create_users(self):
        before = User.objects.count()
        output = StringIO()
        call_command('seed_courses', stdout=output)
        self.assertEqual(User.objects.count(), before)
        self.assertIn('Skipped demo enrollment/progress', output.getvalue())
        self.assertIn('Skipped 4 review fixtures', output.getvalue())

    def test_unknown_and_zero_durations_are_distinct(self):
        self.lesson.duration_seconds = 0
        self.lesson.save()
        response = self.client.get(reverse('api-course-detail', args=[self.course.pk]))
        self.assertEqual(response.data['total_duration_seconds'], 0)
        self.lesson.duration_seconds = None
        self.lesson.save()
        response = self.client.get(reverse('api-course-detail', args=[self.course.pk]))
        self.assertIsNone(response.data['total_duration_seconds'])
