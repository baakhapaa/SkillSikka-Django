"""Regression coverage for the four confirmed backend audit findings."""
from datetime import date
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from .models import (
    BootcampProfile, BootcampResource, Certificate, Course, CourseInstructor,
    Enrollment, Grade, LearningInterest, LearningStreak, Lesson, LessonProgress,
    Notification, PointTransaction, Question, QuestionOption, Quiz, QuizAttempt,
    Redemption, Role, StreakHistory, StudentAnswer, StudentBadge, StudentProfile,
    Subject, User,
)


class BackendBugFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        def user(name, role):
            return User.objects.create_user(
                email=f'{name}@audit.example', name=name,
                role=Role.objects.get(name=role), email_verified=True,
                verification_status='verified',
            )
        cls.owner = user('owner', 'instructor')
        cls.other = user('other', 'instructor')
        cls.admin = user('admin', 'super_admin')
        cls.student = user('student', 'student')
        cls.grade = Grade.objects.get(name='Grade 6')
        StudentProfile.objects.create(user=cls.student, grade=cls.grade)
        cls.subject = Subject.objects.create(name='Audit subject')
        cls.category = LearningInterest.objects.first()
        cls.skill = Course.objects.create(
            title='Owned skill', instructor=cls.owner, course_type='skill', is_published=True,
        )
        cls.own_destination = Course.objects.create(
            title='Owned destination', instructor=cls.owner, course_type='skill', is_published=True,
        )
        cls.foreign = Course.objects.create(
            title='Foreign destination', instructor=cls.other, course_type='skill', is_published=True,
        )
        cls.academic = Course.objects.create(
            title='Academic', instructor=cls.owner, course_type='academic', is_published=True,
            subject=cls.subject, grade=cls.grade, skill_category=cls.category,
        )
        cls.bootcamp = Course.objects.create(
            title='Bootcamp', instructor=cls.owner, course_type='bootcamp', is_published=True,
        )
        BootcampProfile.objects.create(
            course=cls.bootcamp, venue_name='Audit venue', days=1,
            starts_on=date(2026, 10, 1), ends_on=date(2026, 10, 1),
        )
        CourseInstructor.objects.create(course=cls.bootcamp, instructor=cls.owner, role='lead')
        cls.resource = BootcampResource.objects.create(
            course=cls.bootcamp, title='Resource', file_format='pdf', file_url='https://example.com/a.pdf',
        )

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()

    def quiz_content(self, course):
        quiz = Quiz.objects.create(course=course, title='Quiz')
        question = Question.objects.create(quiz=quiz, text='Question', points=10)
        option = QuestionOption.objects.create(question=question, text='Correct', is_correct=True)
        QuestionOption.objects.create(question=question, text='Incorrect')
        return quiz, question, option


class QuizDestinationOwnershipTests(BackendBugFixture):
    def assert_moves(self, actor, destination, expected, code=None):
        self.client.force_authenticate(actor)
        for method in ['patch', 'put']:
            for kind in ['quiz', 'question', 'option']:
                with self.subTest(method=method, kind=kind, destination=destination.pk):
                    source = self.quiz_content(self.skill)
                    target = self.quiz_content(destination)
                    if kind == 'quiz':
                        obj, parent, field, route = source[0], destination, 'course', 'quizzes'
                        data = {'course': parent.pk, 'title': 'Changed'}
                    elif kind == 'question':
                        obj, parent, field, route = source[1], target[0], 'quiz', 'questions'
                        data = {'quiz': parent.pk, 'text': 'Changed'}
                    else:
                        obj, parent, field, route = source[2], target[1], 'question', 'question-options'
                        data = {'question': parent.pk, 'text': 'Changed', 'is_correct': False}
                    before = type(obj).objects.filter(pk=obj.pk).values().get()
                    response = getattr(self.client, method)(f'/api/v1/{route}/{obj.pk}/', data, format='json')
                    self.assertEqual(response.status_code, expected, response.data)
                    obj.refresh_from_db()
                    if expected == 200:
                        self.assertEqual(getattr(obj, field + '_id'), parent.pk)
                    else:
                        self.assertEqual(type(obj).objects.filter(pk=obj.pk).values().get(), before)
                        if code:
                            self.assertEqual(response.data['code'], code)

    def test_foreign_destinations_rejected_without_partial_save_patch_and_put(self):
        self.assert_moves(self.owner, self.foreign, 403)

    def test_same_owner_destinations_allowed_patch_and_put(self):
        self.assert_moves(self.owner, self.own_destination, 200)

    def test_admin_foreign_destinations_allowed_patch_and_put(self):
        self.assert_moves(self.admin, self.foreign, 200)

    def test_bootcamp_destinations_admin_only_patch_and_put(self):
        self.assert_moves(self.owner, self.bootcamp, 403, 'ADMIN_ONLY')

    def test_admin_bootcamp_destinations_allowed_patch_and_put(self):
        self.assert_moves(self.admin, self.bootcamp, 200)

    def test_foreign_sources_remain_unmanageable(self):
        self.assert_moves(self.other, self.foreign, 404)

    def test_lesson_destination_ownership_already_enforced(self):
        self.client.force_authenticate(self.owner)
        lesson = Lesson.objects.create(course=self.skill, title='Lesson', content_type='text', content_text='Content')
        for method in ['patch', 'put']:
            response = getattr(self.client, method)(f'/api/v1/lessons/{lesson.pk}/', {
                'course': self.foreign.pk, 'title': 'Changed', 'content_type': 'text', 'content_text': 'Changed',
            }, format='json')
            self.assertEqual(response.status_code, 403, response.data)
            lesson.refresh_from_db()
            self.assertEqual(lesson.course_id, self.skill.pk)
            self.assertEqual(lesson.title, 'Lesson')


class QuizSubmissionAccessTests(BackendBugFixture):
    def start(self, course, enrollment_status='active'):
        enrollment = None
        if course.course_type != 'academic':
            enrollment = Enrollment.objects.create(student=self.student, course=course, status=enrollment_status)
        quiz, question, option = self.quiz_content(course)
        quiz.is_published = True
        quiz.save()
        self.client.force_authenticate(self.student)
        response = self.client.post(f'/api/v1/student/quizzes/{quiz.pk}/start/')
        self.assertEqual(response.status_code, 201, response.data)
        return QuizAttempt.objects.get(pk=response.data['id']), question, option, enrollment

    def submit(self, attempt, question, option):
        return self.client.post(f'/api/v1/student/quiz-attempts/{attempt.pk}/submit/', {
            'answers': [{'question': question.pk, 'selected_option': option.pk}],
        }, format='json')

    def assert_rejected_without_effects(self, attempt, question, option, code):
        models = [StudentAnswer, PointTransaction, Certificate, Redemption, StudentBadge,
                  LearningStreak, StreakHistory, LessonProgress, Notification, Enrollment]
        before = {model: list(model.objects.order_by('pk').values()) for model in models}
        attempt_before = QuizAttempt.objects.filter(pk=attempt.pk).values().get()
        with patch('core.api_views._check_and_award_badges') as badges:
            response = self.submit(attempt, question, option)
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(response.data['code'], code)
        badges.assert_not_called()
        self.assertEqual(QuizAttempt.objects.filter(pk=attempt.pk).values().get(), attempt_before)
        attempt.refresh_from_db()
        self.assertIsNone(attempt.completed_at)
        for model in models:
            self.assertEqual(list(model.objects.order_by('pk').values()), before[model], model.__name__)

    def test_cancelled_skill_submission_has_zero_side_effects(self):
        self.check_revoked(self.skill, 'cancelled')

    def test_cancelled_bootcamp_submission_has_zero_side_effects(self):
        self.check_revoked(self.bootcamp, 'cancelled')

    def test_pending_skill_submission_has_zero_side_effects(self):
        self.check_revoked(self.skill, 'pending_payment')

    def test_pending_bootcamp_submission_has_zero_side_effects(self):
        self.check_revoked(self.bootcamp, 'pending_payment')

    def check_revoked(self, course, status):
        attempt, question, option, enrollment = self.start(course)
        enrollment.status = status
        enrollment.save()
        self.assert_rejected_without_effects(attempt, question, option, 'NOT_ENROLLED')

    def test_missing_enrollment_submission_rejected(self):
        attempt, question, option, enrollment = self.start(self.skill)
        # Nullable attempts can outlive their enrollment association.
        attempt.enrollment = None
        attempt.save()
        enrollment.delete()
        self.assert_rejected_without_effects(attempt, question, option, 'NOT_ENROLLED')

    def test_active_and_completed_enrollments_still_submit(self):
        for course in [self.skill, self.bootcamp]:
            for status in ['active', 'completed']:
                with self.subTest(course=course.course_type, status=status):
                    Enrollment.objects.filter(student=self.student, course=course).delete()
                    attempt, question, option, _ = self.start(course, status)
                    response = self.submit(attempt, question, option)
                    self.assertEqual(response.status_code, 200, response.data)
                    attempt.refresh_from_db()
                    self.assertIsNotNone(attempt.completed_at)
                    self.assertTrue(StudentAnswer.objects.filter(attempt=attempt).exists())
                    self.assertTrue(PointTransaction.objects.filter(quiz_attempt=attempt).exists())

    def test_eligible_academic_submission_without_enrollment(self):
        attempt, question, option, _ = self.start(self.academic)
        self.assertEqual(self.submit(attempt, question, option).status_code, 200)
        self.assertFalse(Enrollment.objects.filter(course=self.academic).exists())

    def test_academic_grade_revocation_has_zero_side_effects(self):
        attempt, question, option, _ = self.start(self.academic)
        StudentProfile.objects.filter(user=self.student).update(grade=Grade.objects.get(name='Grade 7'))
        self.student._state.fields_cache.pop('student_profile', None)
        self.assert_rejected_without_effects(attempt, question, option, 'ACADEMIC_NOT_ELIGIBLE')


class CourseFilterValidationTests(BackendBugFixture):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.student)

    def test_each_malformed_id_returns_field_specific_400(self):
        for field in ['subject', 'grade', 'instructor', 'skill_category']:
            for value in ['abc', '1.5', '1.0', '-1', '0', '', str(2**63), '9' * 5000]:
                with self.subTest(field=field, value=value[:30]):
                    response = self.client.get('/api/v1/courses/', {field: value})
                    self.assertEqual(response.status_code, 400, response.data)
                    self.assertIn(field, response.data)
                    self.assertIsInstance(response.data[field], list)

    def test_each_existing_id_filters_successfully(self):
        for field, value in [('subject', self.subject.pk), ('grade', self.grade.pk),
                             ('instructor', self.owner.pk), ('skill_category', self.category.pk)]:
            with self.subTest(field=field):
                response = self.client.get('/api/v1/courses/', {field: value})
                self.assertEqual(response.status_code, 200, response.data)
                self.assertIn(self.academic.pk, [row['id'] for row in response.data['results']])

    def test_each_nonexistent_valid_id_returns_empty_results(self):
        for field in ['subject', 'grade', 'instructor', 'skill_category']:
            response = self.client.get('/api/v1/courses/', {field: 2**63 - 1})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data['count'], 0)

    def test_combined_filters_validate_and_intersect(self):
        params = {'subject': self.subject.pk, 'grade': self.grade.pk,
                  'instructor': self.owner.pk, 'skill_category': self.category.pk}
        response = self.client.get('/api/v1/courses/', params)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row['id'] for row in response.data['results']], [self.academic.pk])
        response = self.client.get('/api/v1/courses/', dict(params, subject='abc', grade='1.5'))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.data), {'subject', 'grade'})


class BootcampResourceSafeMethodTests(BackendBugFixture):
    def test_read_permissions_match_for_get_and_head(self):
        url = f'/api/v1/courses/{self.bootcamp.pk}/resources/'
        for user, enrolled, expected in [(self.student, True, 200), (self.student, False, 403),
                                         (self.owner, False, 200), (self.other, False, 200), (self.admin, False, 200)]:
            with self.subTest(user=user.name, enrolled=enrolled):
                Enrollment.objects.filter(student=self.student, course=self.bootcamp).delete()
                if enrolled:
                    Enrollment.objects.create(student=self.student, course=self.bootcamp, status='active')
                self.client.force_authenticate(user)
                get = self.client.get(url)
                head = self.client.head(url)
                self.assertEqual(get.status_code, expected, get.data)
                self.assertEqual(head.status_code, expected)
                self.assertEqual(head.content, b'')
                if expected == 403:
                    self.assertEqual(get.data['code'], 'NOT_ENROLLED')
                    self.assertEqual(head.data['code'], 'NOT_ENROLLED')
                self.assertEqual(self.client.options(url).status_code, 200)

    def test_student_and_roster_lead_still_cannot_mutate_resources(self):
        url = f'/api/v1/courses/{self.bootcamp.pk}/resources/'
        Enrollment.objects.create(student=self.student, course=self.bootcamp, status='active')
        for user in [self.student, self.owner]:
            self.client.force_authenticate(user)
            for method, path, data in [('post', url, {'title': 'New', 'file_format': 'pdf', 'file_url': 'https://example.com/new.pdf'}),
                                       ('patch', f'{url}{self.resource.pk}/', {'title': 'Changed'}),
                                       ('delete', f'{url}{self.resource.pk}/', {})]:
                with self.subTest(user=user.name, method=method):
                    response = getattr(self.client, method)(path, data, format='json')
                    self.assertEqual(response.status_code, 403, response.data)
                    self.assertEqual(response.data['code'], 'ADMIN_ONLY')
                    self.resource.refresh_from_db()
                    self.assertEqual(self.resource.title, 'Resource')
                    self.assertEqual(BootcampResource.objects.count(), 1)

    def test_detail_read_methods_remain_unsupported(self):
        self.client.force_authenticate(self.student)
        url = f'/api/v1/courses/{self.bootcamp.pk}/resources/{self.resource.pk}/'
        for method in ['get', 'head']:
            self.assertEqual(getattr(self.client, method)(url).status_code, 405)
