"""Regression coverage for the five confirmed course/quiz security defects."""
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import (
    BootcampProfile, Certificate, Course, CourseInstructor, CourseResource,
    Enrollment, Grade, LearningInterest, Lesson, LessonProgress, Notification,
    PointTransaction, PremiumCategory, Question, QuestionOption, Quiz, QuizAttempt,
    Redemption, Role, StudentAnswer, StudentBadge, StudentProfile, Subject, User,
)


class CourseSecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.owner = self.user('owner', 'instructor')
        self.other = self.user('other', 'instructor')
        self.admin = self.user('admin', 'super_admin')
        self.student = self.user('student', 'student')
        self.grade = Grade.objects.first()
        self.subject = Subject.objects.create(name='Security audit subject')
        self.profile = StudentProfile.objects.create(user=self.student, grade=self.grade)
        self.skill_category = LearningInterest.objects.first()
        self.premium_category = PremiumCategory.objects.first()
        self.course = self.course_for('skill')
        self.client.force_authenticate(self.owner)

    def user(self, name, role):
        return User.objects.create_user(
            email=f'security-{name}@example.com', name=name,
            role=Role.objects.get(name=role), verification_status='verified',
        )

    def course_for(self, kind, owner=None):
        course = Course.objects.create(
            title=f'Security {kind}', instructor=owner or self.owner,
            course_type=kind, is_published=True,
            is_paid=kind == 'premium', price=100 if kind == 'premium' else None,
            grade=self.grade if kind == 'academic' else None,
            subject=self.subject if kind == 'academic' else None,
            skill_category=self.skill_category if kind == 'skill' else None,
            premium_category=self.premium_category if kind == 'premium' else None,
        )
        if kind == 'bootcamp':
            BootcampProfile.objects.create(
                course=course, venue_name='Audit', days=1,
                starts_on='2026-11-01', ends_on='2026-11-01',
            )
            CourseInstructor.objects.create(course=course, instructor=course.instructor, role='lead')
        return course

    def hierarchy(self, course):
        quiz = Quiz.objects.create(course=course, title='Audit quiz', max_attempts=10)
        question = Question.objects.create(quiz=quiz, text='Question', marks=1, points=10)
        option = QuestionOption.objects.create(question=question, text='Yes', is_correct=True)
        QuestionOption.objects.create(question=question, text='No')
        return quiz, question, option

    def test_destination_ownership_and_admin_privileges(self):
        for user, destination_owner, expected in [
            (self.owner, self.other, 403),
            (self.owner, self.owner, 200),
            (self.admin, self.other, 200),
        ]:
            for index, field, url_name in [
                (0, 'course', 'api-quiz-detail'),
                (1, 'quiz', 'api-question-detail'),
                (2, 'question', 'api-question-option-detail'),
            ]:
                with self.subTest(user=user.email, field=field, expected=expected):
                    source = self.hierarchy(self.course)
                    destination_course = self.course_for('skill', destination_owner)
                    destination = self.hierarchy(destination_course)
                    target = [destination_course, destination[0], destination[1]][index]
                    instance = source[index]
                    original = getattr(instance, field + '_id')
                    self.client.force_authenticate(user)
                    response = self.client.patch(reverse(url_name, args=[instance.pk]), {
                        field: target.pk, 'text': 'Changed', 'title': 'Changed',
                    }, format='json')
                    self.assertEqual(response.status_code, expected, response.data)
                    instance.refresh_from_db()
                    self.assertEqual(getattr(instance, field + '_id'), target.pk if expected == 200 else original)
                    if expected == 403:
                        self.assertEqual(instance.title if index == 0 else instance.text,
                                         'Audit quiz' if index == 0 else ('Question' if index == 1 else 'Yes'))

    def test_bootcamp_hierarchy_moves_remain_admin_only(self):
        camp = self.course_for('bootcamp')
        for source_course, target_course in [(self.course, camp), (camp, self.course)]:
            for index, field, url in [(0, 'course', 'api-quiz-detail'),
                                      (1, 'quiz', 'api-question-detail'),
                                      (2, 'question', 'api-question-option-detail')]:
                for user, expected in [(self.owner, 403), (self.admin, 200)]:
                    with self.subTest(source=source_course.course_type, field=field, user=user.email):
                        source = self.hierarchy(source_course)
                        target = self.hierarchy(target_course)
                        instance = source[index]
                        destination = [target_course, target[0], target[1]][index]
                        original = getattr(instance, field + '_id')
                        self.client.force_authenticate(user)
                        response = self.client.patch(reverse(url, args=[instance.pk]), {field: destination.pk}, format='json')
                        self.assertEqual(response.status_code, expected, response.data)
                        instance.refresh_from_db()
                        self.assertEqual(getattr(instance, field + '_id'), destination.pk if expected == 200 else original)

    def effects(self):
        return {model.__name__: model.objects.count() for model in (
            StudentAnswer, PointTransaction, Certificate, StudentBadge, Redemption,
            LessonProgress, Notification,
        )}

    def start(self, course):
        quiz, question, option = self.hierarchy(course)
        Quiz.objects.filter(pk=quiz.pk).update(is_published=True)
        response = self.client.post(reverse('start-quiz-attempt', args=[quiz.pk]))
        self.assertEqual(response.status_code, 201, response.data)
        return QuizAttempt.objects.get(pk=response.data['id']), {
            'answers': [{'question': question.pk, 'selected_option': option.pk}],
        }

    def assert_rejected_without_effects(self, attempt, payload, code):
        before = self.effects()
        state = QuizAttempt.objects.values().get(pk=attempt.pk)
        with patch('core.api_views._check_and_award_badges') as award:
            response = self.client.post(reverse('submit-quiz-attempt', args=[attempt.pk]), payload, format='json')
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(response.data['code'], code)
        self.assertEqual(self.effects(), before)
        self.assertEqual(QuizAttempt.objects.values().get(pk=attempt.pk), state)
        award.assert_not_called()

    def test_submission_rechecks_current_enrollment(self):
        self.client.force_authenticate(self.student)
        for kind in ['skill', 'bootcamp', 'premium']:
            for revoked in ['cancelled', 'pending_payment']:
                with self.subTest(kind=kind, status=revoked):
                    course = self.course_for(kind)
                    enrollment = Enrollment.objects.create(student=self.student, course=course, status='active')
                    attempt, payload = self.start(course)
                    Enrollment.objects.filter(pk=enrollment.pk).update(status=revoked)
                    self.assert_rejected_without_effects(attempt, payload, 'NOT_ENROLLED')

    def test_submission_preserves_academic_grade_access(self):
        self.client.force_authenticate(self.student)
        course = self.course_for('academic')
        attempt, payload = self.start(course)
        other_grade = Grade.objects.exclude(pk=self.grade.pk).first()
        self.profile.grade = other_grade
        self.profile.save()
        # force_authenticate keeps the User instance; discard cached profile too.
        self.student._state.fields_cache.clear()
        self.assert_rejected_without_effects(attempt, payload, 'ACADEMIC_NOT_ELIGIBLE')
        self.profile.grade = self.grade
        self.profile.save()
        self.student._state.fields_cache.clear()
        response = self.client.post(reverse('submit-quiz-attempt', args=[attempt.pk]), payload, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(Enrollment.objects.filter(student=self.student, course=course).exists())

    def test_submission_uses_current_quiz_course_before_validating_answers(self):
        self.client.force_authenticate(self.student)
        Enrollment.objects.create(student=self.student, course=self.course, status='active')
        attempt, payload = self.start(self.course)
        destination = self.course_for('premium')
        Quiz.objects.filter(pk=attempt.quiz_id).update(course=destination)
        # The old enrollment cannot authorize the quiz's new canonical course.
        self.assert_rejected_without_effects(attempt, payload, 'NOT_ENROLLED')
        self.assert_rejected_without_effects(attempt, {'answers': 'invalid'}, 'NOT_ENROLLED')

    def test_active_and_completed_enrollments_can_submit(self):
        self.client.force_authenticate(self.student)
        for kind in ['skill', 'bootcamp', 'premium']:
            for state in ['active', 'completed']:
                with self.subTest(kind=kind, state=state):
                    course = self.course_for(kind)
                    Enrollment.objects.create(student=self.student, course=course, status=state)
                    attempt, payload = self.start(course)
                    response = self.client.post(reverse('submit-quiz-attempt', args=[attempt.pk]), payload, format='json')
                    self.assertEqual(response.status_code, 200, response.data)
                    attempt.refresh_from_db()
                    self.assertIsNotNone(attempt.completed_at)

    def test_course_id_filters(self):
        self.client.force_authenticate(self.student)
        academic = self.course_for('academic')
        existing = {'subject': (self.subject.pk, academic), 'grade': (self.grade.pk, academic),
                    'instructor': (self.owner.pk, self.course), 'skill_category': (self.skill_category.pk, self.course)}
        url = reverse('api-course-list-create')
        for field, (pk, course) in existing.items():
            for invalid in ['abc', '1.5', '--1', '-1', '', '0', '9223372036854775808', '9' * 5000]:
                with self.subTest(field=field, value=invalid[:30]):
                    response = self.client.get(url, {field: invalid})
                    self.assertEqual(response.status_code, 400, response.data)
                    self.assertIn(field, response.data)
            for valid in [str(pk), '0' + str(pk)]:
                response = self.client.get(url, {field: valid})
                self.assertEqual(response.status_code, 200, response.data)
                self.assertIn(course.pk, [row['id'] for row in response.data['results']])
            response = self.client.get(url, {field: '9223372036854775807'})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data['results'], [])

    def test_resource_lesson_id_filter(self):
        lesson = Lesson.objects.create(course=self.course, title='Audit lesson', content_type='text')
        resource = CourseResource.objects.create(course=self.course, lesson=lesson, title='Audit', file_format='pdf', file_url='https://example.com/a.pdf')
        url = reverse('api-course-resources', args=[self.course.pk])
        for invalid in ['abc', '1.5', '--1', '-1', '', '0', '9223372036854775808', '9' * 5000]:
            with self.subTest(value=invalid[:30]):
                response = self.client.get(url, {'lesson': invalid})
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn('lesson', response.data)
        response = self.client.get(url, {'lesson': lesson.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['id'] for row in response.data], [resource.pk])
        response = self.client.get(url, {'lesson': '9223372036854775807'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])
        # HEAD and resource-authoring policy must remain unchanged.
        Enrollment.objects.create(student=self.student, course=self.course, status='active')
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.head(url).status_code, 200)

    def test_category_type_transitions_normalize_only_incompatible_category(self):
        for source in ['academic', 'skill', 'premium', 'bootcamp']:
            for target in ['academic', 'skill', 'premium', 'bootcamp']:
                with self.subTest(source=source, target=target):
                    course = self.course_for(source)
                    self.client.force_authenticate(self.admin)
                    data = {'course_type': target}
                    if target == 'premium':
                        data.update(is_paid=True, price='100.00')
                    if target == 'academic':
                        data.update(subject=self.subject.pk, grade=self.grade.pk)
                    response = self.client.patch(reverse('api-course-detail', args=[course.pk]), data, format='json')
                    if source != target and 'bootcamp' in [source, target]:
                        self.assertEqual(response.status_code, 400, response.data)
                        course.refresh_from_db()
                        self.assertEqual(course.course_type, source)
                    else:
                        self.assertEqual(response.status_code, 200, response.data)
                        course.refresh_from_db()
                        self.assertEqual(course.course_type, target)
                        self.assertIsNone(course.skill_category_id if target == 'premium' else course.premium_category_id)
                        if source == target == 'skill':
                            self.assertEqual(course.skill_category_id, self.skill_category.pk)
                        if source == target == 'premium':
                            self.assertEqual(course.premium_category_id, self.premium_category.pk)
                    course.full_clean()

    def test_explicit_incompatible_category_is_cleared_on_every_type(self):
        self.client.force_authenticate(self.admin)
        for kind in ['academic', 'skill', 'premium', 'bootcamp']:
            with self.subTest(kind=kind):
                course = self.course_for(kind)
                data = {'skill_category': self.skill_category.pk, 'premium_category': self.premium_category.pk}
                response = self.client.patch(reverse('api-course-detail', args=[course.pk]), data, format='json')
                self.assertEqual(response.status_code, 200, response.data)
                course.refresh_from_db()
                self.assertIsNone(course.skill_category_id if kind == 'premium' else course.premium_category_id)
                course.full_clean()
