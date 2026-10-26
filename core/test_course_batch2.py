from contextlib import redirect_stderr
from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (Certificate, Course, CourseReview, Enrollment, Grade, Lesson, LessonProgress,
    Question, QuestionOption, Quiz, QuizAttempt, Role, StudentProfile, Subject, User)


class CourseBatch2Tests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.owner = self.user('owner', 'instructor')
        self.student = self.user('student', 'student')
        self.other = self.user('other', 'student')
        self.admin = self.user('admin', 'super_admin')
        self.grade = Grade.objects.get(name='Grade 6')
        StudentProfile.objects.create(user=self.student, grade=self.grade)
        StudentProfile.objects.create(user=self.other, grade=Grade.objects.get(name='Grade 7'))
        self.skill = Course.objects.create(title='Skill', course_type='skill', instructor=self.owner, is_published=True)
        self.academic = Course.objects.create(title='Academic', course_type='academic', instructor=self.owner,
            grade=self.grade, subject=Subject.objects.create(name='Batch 2 Subject'), is_published=True)
        self.lesson = Lesson.objects.create(course=self.academic, title='Academic lesson', content_type='text', content_text='Academic secret')
        self.client.force_authenticate(self.student)

    def user(self, name, role):
        return User.objects.create_user(email=f'batch2-{name}@example.com', name=name, role=Role.objects.get(name=role))

    def progress_url(self, course):
        return reverse('api-course-progress', args=[course.pk])

    def quiz_url(self, course):
        return reverse('api-course-quizzes', args=[course.pk])

    def quiz(self, course=None, **kwargs):
        return Quiz.objects.create(course=course or self.skill, title='Knowledge check', is_published=True, max_attempts=3, **kwargs)

    def assert_code(self, response, code, status):
        self.assertEqual(response.status_code, status, response.data)
        self.assertEqual(response.data['code'], code)
        self.assertTrue(response.data['detail'])

    def test_academic_learning_without_enrollment(self):
        for url in [reverse('api-lesson-detail', args=[self.lesson.pk]), reverse('api-lesson-list-create') + f'?course={self.academic.pk}']:
            data = self.client.get(url).data
            row = data[0] if isinstance(data, list) else data
            self.assertEqual(row['content_text'], 'Academic secret')
        self.assertEqual(self.client.get(self.progress_url(self.academic)).data['progress_percentage'], 0)
        response = self.client.post(reverse('api-complete-lesson', args=[self.lesson.pk]))
        self.assertEqual(response.status_code, 200, response.data)
        progress = LessonProgress.objects.get(student=self.student, lesson=self.lesson)
        self.assertIsNone(progress.enrollment_id)
        response = self.client.get(self.progress_url(self.academic))
        self.assertEqual(response.data['progress_percentage'], 100)
        self.assertTrue(response.data['is_completed'])
        self.assertFalse(Enrollment.objects.filter(course=self.academic).exists())

    def test_wrong_grade_academic_access_and_preview(self):
        self.client.force_authenticate(self.other)
        self.lesson.is_preview = True
        self.lesson.save()
        self.assertIsNone(self.client.get(reverse('api-lesson-detail', args=[self.lesson.pk])).data['content_text'])
        self.assertIsNone(self.client.get(reverse('api-lesson-list-create'), {'course': self.academic.pk}).data[0]['content_text'])
        for response in [self.client.post(reverse('api-complete-lesson', args=[self.lesson.pk])), self.client.get(self.progress_url(self.academic))]:
            self.assert_code(response, 'ACADEMIC_NOT_ELIGIBLE', 403)
        self.assertFalse(LessonProgress.objects.exists())

    def test_unpublished_academic_and_management(self):
        self.academic.is_published = False
        self.academic.save()
        self.assertEqual(self.client.get(reverse('api-lesson-detail', args=[self.lesson.pk])).status_code, 404)
        self.assert_code(self.client.post(reverse('api-complete-lesson', args=[self.lesson.pk])), 'COURSE_NOT_PUBLISHED', 403)
        self.assert_code(self.client.get(self.progress_url(self.academic)), 'COURSE_NOT_PUBLISHED', 403)
        for user in [self.owner, self.admin]:
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(reverse('api-lesson-detail', args=[self.lesson.pk])).data['content_text'], 'Academic secret')
            self.assertEqual(self.client.get(self.progress_url(self.academic)).status_code, 200)
        self.assertFalse(Enrollment.objects.exists())

    def test_inactive_or_profile_missing_academic(self):
        for user in [self.student, self.user('no-profile', 'student'), self.owner]:
            if user == self.student:
                user.is_active = False
                user.save()
            self.client.force_authenticate(user)
            self.assertEqual(self.client.post(reverse('api-complete-lesson', args=[self.lesson.pk])).status_code, 403)

    def test_zero_lessons_and_undefined_grade(self):
        self.academic.lessons.all().delete()
        self.academic.grade = None
        self.academic.save()
        self.client.force_authenticate(self.other)
        data = self.client.get(self.progress_url(self.academic)).data
        self.assertEqual(data['total_lessons'], 0)
        self.assertEqual(data['progress_percentage'], 0)
        self.assertFalse(data['is_completed'])

    def test_skill_enrollment_and_paid_gating_preserved(self):
        lesson = Lesson.objects.create(course=self.skill, title='Skill secret', content_type='text', content_text='Secret')
        self.skill.is_paid = True
        self.skill.price = '1299.00'
        self.skill.save()
        for state in [None, 'pending_payment', 'cancelled', 'active', 'completed']:
            Enrollment.objects.filter(student=self.student).delete()
            if state:
                Enrollment.objects.create(student=self.student, course=self.skill, status=state)
            allowed = state in ['active', 'completed']
            self.assertEqual(self.client.get(reverse('api-lesson-detail', args=[lesson.pk])).data['content_text'], 'Secret' if allowed else None)
            response = self.client.get(self.progress_url(self.skill))
            self.assertEqual(response.status_code, 200 if allowed else 403)
            if not allowed:
                self.assert_code(response, 'NOT_ENROLLED', 403)

    def test_grade_certificate_uses_new_academic_progress(self):
        self.assert_code(self.client.post(reverse('api-check-grade-certificate')), 'CERTIFICATE_NOT_ELIGIBLE', 400)
        self.client.post(reverse('api-complete-lesson', args=[self.lesson.pk]))
        response = self.client.post(reverse('api-check-grade-certificate'))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Certificate.objects.get(student=self.student).grade_id, self.grade.pk)
        self.assertFalse(Enrollment.objects.exists())

    def test_quiz_discovery_metadata_attempts_and_isolation(self):
        enrollment = Enrollment.objects.create(student=self.student, course=self.skill)
        quiz = self.quiz()
        Quiz.objects.create(course=self.skill, title='Draft', is_published=False)
        question = Question.objects.create(quiz=quiz, text='Private question')
        QuestionOption.objects.create(question=question, text='Private answer', is_correct=True)
        for percentage, passed in [(25, False), (80, True)]:
            QuizAttempt.objects.create(student=self.student, quiz=quiz, enrollment=enrollment, percentage=percentage, is_passed=passed, completed_at=timezone.now())
        QuizAttempt.objects.create(student=self.student, quiz=quiz, enrollment=enrollment, percentage=99)
        other_enrollment = Enrollment.objects.create(student=self.other, course=self.skill)
        QuizAttempt.objects.create(student=self.other, quiz=quiz, enrollment=other_enrollment, percentage=100, is_passed=True, completed_at=timezone.now())
        response = self.client.get(self.quiz_url(self.skill))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        row = response.data[0]
        self.assertEqual(set(row), {'id', 'title', 'description', 'pass_percentage', 'max_attempts', 'attempts_used', 'best_percentage', 'is_passed'})
        self.assertEqual(row['attempts_used'], 2)
        self.assertEqual(row['best_percentage'], '80.00')
        self.assertTrue(row['is_passed'])
        self.assertEqual(row['max_attempts'], 3)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(self.quiz_url(self.skill)).data[0]['attempts_used'], 1)

    def test_quiz_discovery_access(self):
        self.quiz()
        academic_quiz = self.quiz(self.academic)
        self.assert_code(self.client.get(self.quiz_url(self.skill)), 'NOT_ENROLLED', 403)
        self.assertEqual(self.client.get(self.quiz_url(self.academic)).data[0]['id'], academic_quiz.pk)
        self.client.force_authenticate(self.other)
        self.assert_code(self.client.get(self.quiz_url(self.academic)), 'ACADEMIC_NOT_ELIGIBLE', 403)
        self.academic.is_published = False
        self.academic.save()
        self.assert_code(self.client.get(self.quiz_url(self.academic)), 'COURSE_NOT_PUBLISHED', 403)
        Quiz.objects.create(course=self.academic, title='Draft quiz')
        for user in [self.owner, self.admin]:
            self.client.force_authenticate(user)
            self.assertEqual(len(self.client.get(self.quiz_url(self.academic)).data), 2)

    def test_academic_quiz_can_be_started_and_submitted(self):
        quiz = self.quiz(self.academic)
        question = Question.objects.create(quiz=quiz, text='What is 2+2?', marks=1)
        option = QuestionOption.objects.create(question=question, text='4', is_correct=True)
        response = self.client.post(reverse('start-quiz-attempt', args=[quiz.pk]))
        self.assertEqual(response.status_code, 201, response.data)
        attempt_id = response.data['id']
        self.assertIsNone(QuizAttempt.objects.get(pk=attempt_id).enrollment_id)
        response = self.client.post(reverse('submit-quiz-attempt', args=[attempt_id]), {'answers': [{'question': question.pk, 'selected_option': option.pk}]}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(self.client.get(self.quiz_url(self.academic)).data[0]['is_passed'])
        self.assertFalse(Enrollment.objects.exists())

    def test_quiz_queries_constant(self):
        Enrollment.objects.create(student=self.student, course=self.skill)
        self.quiz()
        def queries():
            with CaptureQueriesContext(connection) as captured:
                self.assertEqual(self.client.get(self.quiz_url(self.skill)).status_code, 200)
            return len(captured)
        initial = queries()
        for _ in range(15):
            self.quiz()
        self.assertEqual(queries(), initial)
        self.assertEqual(initial, 3)

    def test_skill_quiz_assessment_regression(self):
        quiz = self.quiz()
        question = Question.objects.create(quiz=quiz, text='Which answer is correct?', marks=2)
        option = QuestionOption.objects.create(question=question, text='Correct', is_correct=True)
        start = reverse('start-quiz-attempt', args=[quiz.pk])
        detail = f'/api/v1/student/quizzes/{quiz.pk}/'
        enrollment = Enrollment.objects.create(student=self.student, course=self.skill, status='pending_payment')
        self.assert_code(self.client.get(detail), 'NOT_ENROLLED', 403)
        self.assert_code(self.client.post(start), 'NOT_ENROLLED', 403)
        enrollment.status = 'active'
        enrollment.save()
        self.assertEqual(self.client.get(detail).status_code, 200)
        response = self.client.post(start)
        self.assertEqual(response.status_code, 201)
        attempt_id = response.data['id']
        self.assertEqual(QuizAttempt.objects.get(pk=attempt_id).enrollment_id, enrollment.pk)
        self.assertEqual(self.client.post(start).status_code, 200)
        response = self.client.post(reverse('submit-quiz-attempt', args=[attempt_id]),
            {'answers': [{'question': question.pk, 'selected_option': option.pk}]}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        attempt = QuizAttempt.objects.get(pk=attempt_id)
        self.assertTrue(attempt.is_passed)
        self.assertEqual(attempt.percentage, 100)
        self.client.force_authenticate(self.other)
        response = self.client.post(reverse('submit-quiz-attempt', args=[attempt_id]), {'answers': []}, format='json')
        self.assertEqual(response.status_code, 404)

    def test_stable_course_error_codes(self):
        self.assert_code(self.client.post(reverse('api-enroll-course', args=[999999])), 'COURSE_NOT_FOUND', 404)
        self.assert_code(self.client.get(reverse('api-course-detail', args=[999999])), 'COURSE_NOT_FOUND', 404)
        self.assert_code(self.client.get(reverse('api-course-quizzes', args=[999999])), 'COURSE_NOT_FOUND', 404)
        self.assert_code(self.client.get(reverse('api-course-progress', args=[999999])), 'COURSE_NOT_FOUND', 404)
        self.assert_code(self.client.post(reverse('api-enroll-course', args=[self.academic.pk])), 'COURSE_NOT_ENROLLABLE', 400)
        enrollment = Enrollment.objects.create(student=self.student, course=self.skill)
        self.assert_code(self.client.post(reverse('api-enroll-course', args=[self.skill.pk])), 'ALREADY_ENROLLED', 400)
        self.assert_code(self.client.post(reverse('api-check-course-certificate', args=[self.skill.pk])), 'CERTIFICATE_NOT_ELIGIBLE', 400)
        quiz = self.quiz()
        for _ in range(3):
            QuizAttempt.objects.create(quiz=quiz, student=self.student, enrollment=enrollment, completed_at=timezone.now())
        self.assert_code(self.client.post(reverse('start-quiz-attempt', args=[quiz.pk])), 'MAX_ATTEMPTS_REACHED', 400)
        self.skill.is_published = False
        self.skill.save()
        self.assert_code(self.client.post(reverse('api-enroll-course', args=[self.skill.pk])), 'COURSE_NOT_PUBLISHED', 400)

    def test_review_duplicate_and_me_lifecycle(self):
        Enrollment.objects.create(student=self.student, course=self.skill)
        url = reverse('api-course-reviews', args=[self.skill.pk])
        me = reverse('api-my-course-review', args=[self.skill.pk])
        self.assertEqual(self.client.get(me).status_code, 404)
        self.assertEqual(self.client.post(url, {'rating': 3}).status_code, 201)
        self.assert_code(self.client.post(url, {'rating': 4}), 'REVIEW_EXISTS', 400)
        row = self.client.get(me).data
        self.assertEqual(row['student'], {'id': self.student.pk, 'name': self.student.name, 'profile_photo_url': None})
        self.assertEqual(self.client.patch(me, {'rating': 5, 'review': 'Useful'}).status_code, 200)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(me).status_code, 404)
        self.assertEqual(self.client.patch(me, {'rating': 1}).status_code, 403)
        Enrollment.objects.create(student=self.other, course=self.skill)
        self.assertEqual(self.client.patch(me, {'rating': 1}).status_code, 404)
        self.assertEqual(self.client.delete(me).status_code, 404)
        self.client.force_authenticate(self.student)
        for payload in [{'rating': 0}, {'rating': 6}, {'rating': 2.5}, {'student': self.other.pk}, {'course': self.academic.pk}]:
            self.assertEqual(self.client.patch(me, payload, format='json').status_code, 400)
        self.assertEqual(self.client.delete(me).status_code, 204)

    def test_review_photo_compatibility(self):
        CourseReview.objects.create(course=self.skill, student=self.student, rating=4)
        url = reverse('api-course-reviews', args=[self.skill.pk])
        for value in ['profile-photos/demo.jpg', '/media/profile-photos/old.jpg', 'https://cdn.example.com/demo.jpg', '']:
            self.student.profile_photo_url = value
            self.student.save()
            photo = self.student.profile_photo_src
            expected = ('http://testserver' + photo if photo.startswith('/') else photo) if photo else None
            self.assertEqual(self.client.get(url).data[0]['student']['profile_photo_url'], expected)

    def test_course_lists_defaults_and_management(self):
        self.client.force_authenticate(self.owner)
        url = reverse('api-course-list-create')
        response = self.client.post(url, {'title': 'New detail', 'course_type': 'skill', 'learning_outcomes': ['  Build a project  '], 'requirements': ['  Curiosity ']}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['learning_outcomes'], ['Build a project'])
        self.assertEqual(response.data['requirements'], ['Curiosity'])
        detail = reverse('api-course-detail', args=[response.data['id']])
        self.assertEqual(self.client.patch(detail, {'requirements': []}, format='json').data['requirements'], [])
        data = self.client.get(reverse('api-course-detail', args=[self.skill.pk])).data
        self.assertEqual(data['learning_outcomes'], [])
        self.assertEqual(data['requirements'], [])
        self.assertIn('learning_outcomes', self.client.get(url).data['results'][0])
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.patch(reverse('api-course-detail', args=[self.skill.pk]), {'requirements': ['Override']}, format='json').status_code, 403)

    def test_course_lists_reject_invalid_json(self):
        self.client.force_authenticate(self.owner)
        url = reverse('api-course-detail', args=[self.skill.pk])
        for field in ['learning_outcomes', 'requirements']:
            for value in ['text', {'nested': 'object'}, [['nested']], [3], [True], [None], [' '], ['x' * 501], ['ok'] * 51, None]:
                with self.subTest(field=field, value=value):
                    response = self.client.patch(url, {field: value}, format='json')
                    self.assertEqual(response.status_code, 400, response.data)

    def test_admin_form_course_lists(self):
        from .forms import CourseForm
        base = {'title': 'Form course', 'instructor': self.owner.pk, 'course_type': 'skill', 'requirements': '[]'}
        form = CourseForm({**base, 'learning_outcomes': '["  Explain fractions  "]'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['learning_outcomes'], ['Explain fractions'])
        for invalid in ['false', '0', '{"nested": "data"}', '[42]', '[" "]']:
            form = CourseForm({**base, 'learning_outcomes': invalid})
            self.assertFalse(form.is_valid())
            self.assertIn('learning_outcomes', form.errors)

    def test_batch2_seed_idempotency(self):
        call_command('seed_courses', stdout=StringIO())
        counts = [model.objects.count() for model in [User, Course, Lesson, Quiz, Question, QuestionOption, Enrollment]]
        call_command('seed_courses', stdout=StringIO())
        self.assertEqual(counts, [model.objects.count() for model in [User, Course, Lesson, Quiz, Question, QuestionOption, Enrollment]])
        seeded = Course.objects.get(title='Python: Build Your First Project')
        self.assertTrue(seeded.learning_outcomes)
        self.assertTrue(seeded.requirements)
        self.assertEqual(seeded.quizzes.count(), 1)


class CourseSchemaTests(TestCase):
    def test_course_dashboard_schema_contract(self):
        from drf_spectacular.generators import SchemaGenerator
        with redirect_stderr(StringIO()):
            schema = SchemaGenerator().get_schema(public=True)
        components = schema['components']['schemas']
        def resolve(node):
            return components[node['$ref'].split('/')[-1]] if '$ref' in node else node
        specs = [('/api/v1/courses/{course_id}/enroll/', 'post', '201'),
            ('/api/v1/courses/{course_id}/progress/', 'get', '200'),
            ('/api/v1/courses/{course_id}/quizzes/', 'get', '200'),
            ('/api/v1/my-learning/', 'get', '200'), ('/api/v1/home/', 'get', '200'),
            ('/api/v1/courses/{course_id}/initiate-payment/', 'post', '201')]
        for path, method, status in specs:
            operation = schema['paths'][path][method]
            body = operation['responses'][status]['content']['application/json']['schema']
            self.assertTrue(body)
            schemes = schema['components']['securitySchemes']
            self.assertTrue(any(schemes[name].get('scheme') == 'bearer' for security in operation['security'] for name in security))
        payment = resolve(schema['paths'][specs[-1][0]]['post']['responses']['201']['content']['application/json']['schema'])
        self.assertIn('payment_url', payment['properties'])
        course = components['Course']['properties']
        self.assertEqual(course['average_rating']['type'], 'number')
        self.assertTrue(course['average_rating']['nullable'])
        self.assertEqual(course['review_count']['type'], 'integer')
        self.assertEqual(course['price']['type'], 'string')
        self.assertEqual(components['CourseReview']['properties']['student']['type'], 'object')
        listing = schema['paths']['/api/v1/courses/']['get']
        self.assertTrue({'search', 'ordering', 'page', 'page_size', 'skill_category'} <= {p['name'] for p in listing['parameters']})
        envelope = resolve(listing['responses']['200']['content']['application/json']['schema'])
        self.assertEqual(set(envelope['properties']), {'count', 'next', 'previous', 'results'})
