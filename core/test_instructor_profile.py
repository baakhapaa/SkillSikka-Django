from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from .models import Course, CourseReview, Enrollment, InstructorProfile, Role, User


class InstructorProfileSetup(TestCase):
    def setUp(self):
        cache.clear()
        self.teacher = self.user('teacher@example.com', 'Shuvanga Karki', 'instructor')
        InstructorProfile.objects.create(user=self.teacher, qualification='Adobe Certified Instructor')
        self.student = self.user('student@example.com', 'Suman', 'student')
        self.client = APIClient()
        self.client.force_authenticate(self.student)

    def user(self, email, name, role, **kwargs):
        kwargs.setdefault('verification_status', 'verified')
        return User.objects.create_user(email=email, name=name, role=Role.objects.get(name=role), **kwargs)

    def course(self, title, paid=False, published=True, teacher=None):
        return Course.objects.create(title=title, instructor=teacher or self.teacher, course_type='skill',
            is_paid=paid, price=Decimal('24.99') if paid else None, is_published=published)

    def students(self, course, count):
        for _ in range(count):
            n = User.objects.count()
            Enrollment.objects.create(course=course, status='active',
                student=self.user(f's{n}@example.com', f'S{n}', 'student'))

    def review(self, course, rating=5, text='Great teacher', student=None):
        if student is None:
            n = User.objects.count()
            student = self.user(f'r{n}@example.com', f'Reviewer {n}', 'student')
        return CourseReview.objects.create(course=course, student=student, rating=rating, review=text)

    def profile(self, teacher=None, expect=200):
        response = self.client.get(f'/api/v1/instructors/{(teacher or self.teacher).pk}/')
        self.assertEqual(response.status_code, expect, getattr(response, 'data', None))
        return response.data

    def reviews(self, teacher=None, expect=200, **params):
        response = self.client.get(f'/api/v1/instructors/{(teacher or self.teacher).pk}/reviews/', params)
        self.assertEqual(response.status_code, expect, getattr(response, 'data', None))
        return response.data


class InstructorBioTests(InstructorProfileSetup):
    def test_instructor_sets_bio_shown_on_me_and_public_profile(self):
        self.course('Art')
        self.client.force_authenticate(self.teacher)
        self.assertIsNone(self.client.get('/api/v1/me/').data['bio'])
        response = self.client.patch('/api/v1/me/', {'bio': '  Illustrator for 12 years.  '}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['bio'], 'Illustrator for 12 years.')
        self.client.force_authenticate(self.student)
        self.assertEqual(self.profile()['bio'], 'Illustrator for 12 years.')

    def test_bio_can_be_cleared_and_is_limited_to_1000_characters(self):
        self.client.force_authenticate(self.teacher)
        self.assertEqual(self.client.patch('/api/v1/me/', {'bio': 'x' * 1001}, format='json').status_code, 400)
        self.assertEqual(self.client.patch('/api/v1/me/', {'bio': 'x' * 1000}, format='json').status_code, 200)
        self.assertIsNone(self.client.patch('/api/v1/me/', {'bio': ''}, format='json').data['bio'])
        self.course('Art')
        self.assertEqual(self.profile()['bio'], '')

    def test_bio_is_instructor_only(self):
        response = self.client.patch('/api/v1/me/', {'bio': 'Hi'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('bio', response.data)
        self.assertIsNone(self.client.get('/api/v1/me/').data['bio'])

    def test_bio_creates_a_missing_instructor_profile(self):
        bare = self.user('bare@example.com', 'Bare', 'instructor')
        self.client.force_authenticate(bare)
        self.assertEqual(self.client.patch('/api/v1/me/', {'bio': 'Hello'}, format='json').status_code, 200)
        self.assertEqual(InstructorProfile.objects.get(user=bare).bio, 'Hello')


class InstructorProfileCourseTests(InstructorProfileSetup):
    def test_premium_courses_are_the_paid_published_ones(self):
        free = self.course('Free')
        paid = self.course('Paid', paid=True)
        self.course('Paid draft', paid=True, published=False)
        data = self.profile()
        self.assertEqual([c['id'] for c in data['premium_courses']], [paid.pk])
        self.assertEqual({c['id'] for c in data['courses']}, {free.pk, paid.pk})
        self.assertEqual(data['premium_courses'][0], next(c for c in data['courses'] if c['id'] == paid.pk))

    def test_popular_courses_rank_by_students_then_rating_then_newest(self):
        few = self.course('Few')
        many = self.course('Many')
        rated_low = self.course('Rated low')
        rated_high = self.course('Rated high')
        unrated_old = self.course('Unrated old')
        unrated_new = self.course('Unrated new')
        self.students(few, 1)
        self.students(many, 3)
        for course in [rated_low, rated_high]:
            self.students(course, 2)
        self.review(rated_low, 3)
        self.review(rated_high, 5)
        Course.objects.filter(pk=unrated_old.pk).update(created_at=unrated_new.created_at - timedelta(days=1))
        data = self.profile()
        self.assertEqual([c['id'] for c in data['popular_courses']],
                         [many.pk, rated_high.pk, rated_low.pk, few.pk, unrated_new.pk])
        self.assertNotIn(unrated_old.pk, [c['id'] for c in data['popular_courses']])

    def test_is_me_only_for_the_instructor_themselves(self):
        self.course('Art')
        self.assertFalse(self.profile()['is_me'])
        self.client.force_authenticate(self.teacher)
        self.assertTrue(self.profile()['is_me'])
        other = self.user('other@example.com', 'Other', 'instructor')
        self.client.force_authenticate(other)
        self.assertFalse(self.profile()['is_me'])

    def test_owner_sees_own_page_before_it_is_public_with_drafts(self):
        self.teacher.verification_status = 'pending'
        self.teacher.save(update_fields=['verification_status'])
        draft = self.course('Draft', paid=True, published=False)
        self.profile(expect=404)
        self.reviews(expect=404)
        self.client.force_authenticate(self.teacher)
        data = self.profile()
        self.assertTrue(data['is_me'])
        self.assertEqual([c['id'] for c in data['courses']], [draft.pk])
        self.assertFalse(data['courses'][0]['is_published'])
        # Premium and popular show what students see.
        self.assertEqual(data['premium_courses'], [])
        self.assertEqual(data['popular_courses'], [])
        self.assertEqual(data['total_courses'], 0)
        self.assertEqual(self.reviews()['count'], 0)

    def test_students_never_see_drafts(self):
        published = self.course('Published')
        self.course('Draft', published=False)
        self.assertEqual([c['id'] for c in self.profile()['courses']], [published.pk])


class InstructorReviewTests(InstructorProfileSetup):
    def setUp(self):
        super().setUp()
        self.art = self.course('The Art of Problem Solving')

    def test_recent_reviews_newest_five_with_text_and_course(self):
        reviews = [self.review(self.art, text=f'Review {i}') for i in range(6)]
        self.review(self.art, text='')
        data = self.profile()
        self.assertEqual([r['id'] for r in data['recent_reviews']], [r.pk for r in reversed(reviews[1:])])
        row = data['recent_reviews'][0]
        self.assertEqual(row['course'], {'id': self.art.pk, 'title': 'The Art of Problem Solving'})
        self.assertEqual(row['student']['name'], reviews[-1].student.name)
        self.assertEqual(row['rating'], 5)
        self.assertEqual(row['review'], 'Review 5')
        # The header counts every review, rating-only ones too.
        self.assertEqual(data['review_count'], 7)

    def test_reviews_of_unpublished_courses_only_reach_the_owner(self):
        old = self.course('Retired')
        hidden = self.review(old, text='From when it was live')
        Course.objects.filter(pk=old.pk).update(is_published=False)
        shown = self.review(self.art)
        self.assertEqual([r['id'] for r in self.profile()['recent_reviews']], [shown.pk])
        self.assertEqual([r['id'] for r in self.reviews()['results']], [shown.pk])
        self.client.force_authenticate(self.teacher)
        self.assertEqual([r['id'] for r in self.profile()['recent_reviews']], [shown.pk, hidden.pk])
        self.assertEqual(self.reviews()['count'], 2)

    def test_reviews_endpoint_is_paginated_newest_first(self):
        other = self.course('Other', teacher=self.user('t2@example.com', 'T2', 'instructor'))
        self.review(other)
        mine = [self.review(self.art, text=f'Review {i}') for i in range(3)]
        data = self.reviews(page_size=2)
        self.assertEqual(data['count'], 3)
        self.assertEqual([r['id'] for r in data['results']], [mine[2].pk, mine[1].pk])
        self.assertIsNotNone(data['next'])
        self.assertEqual([r['id'] for r in self.reviews(page_size=2, page=2)['results']], [mine[0].pk])

    def test_reviews_endpoint_hides_non_public_instructors(self):
        missing = User.objects.order_by('-pk').first().pk + 100
        self.assertEqual(self.client.get(f'/api/v1/instructors/{missing}/reviews/').status_code, 404)
        self.reviews(teacher=self.student, expect=404)
        self.client.force_authenticate(None)
        self.reviews(expect=401)

    def test_profile_query_count_does_not_grow_with_reviews_or_courses(self):
        self.review(self.art)
        with CaptureQueriesContext(connection) as before:
            self.profile()
        for i in range(5):
            course = self.course(f'Course {i}', paid=True)
            self.students(course, 1)
            self.review(course)
        with CaptureQueriesContext(connection) as after:
            data = self.profile()
        self.assertEqual(len(after), len(before))
        self.assertEqual(len(data['recent_reviews']), 5)
        self.assertEqual(len(data['popular_courses']), 5)
