from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (Course, Enrollment, PointTransaction, Question, QuestionOption, Quiz, QuizAttempt, Role,
    StudentAnswer, User)


class ModuleQuizSetup(TestCase):
    def setUp(self):
        cache.clear()
        self.teacher = self.user('teacher', 'instructor')
        self.student = self.user('student', 'student')
        self.stranger = self.user('stranger', 'student')
        self.course = Course.objects.create(title='Physics', instructor=self.teacher, course_type='skill',
            is_published=True)
        Enrollment.objects.create(student=self.student, course=self.course, status='active')
        self.quiz = Quiz.objects.create(course=self.course, title='Forces Quiz', section='Forces and motion',
            is_published=True, max_attempts=2, pass_percentage=60)
        self.q1, self.q1_right, self.q1_wrong = self.question(self.quiz, 'SI unit of force?', 0,
            hint='A push or a pull.', explanation='A newton (N) is the SI unit of force.', points=5)
        self.q2, self.q2_right, self.q2_wrong = self.question(self.quiz, 'Unit of mass?', 1)
        self.client = APIClient()
        self.client.force_authenticate(self.student)

    def user(self, name, role):
        return User.objects.create_user(email=f'{name}@example.com', name=name.title(),
            role=Role.objects.get(name=role), verification_status='verified')

    def question(self, quiz, text, order, **kwargs):
        question = Question.objects.create(quiz=quiz, text=text, order=order, **kwargs)
        right = QuestionOption.objects.create(question=question, text='Right', is_correct=True)
        wrong = QuestionOption.objects.create(question=question, text='Wrong')
        return question, right, wrong

    def start(self):
        response = self.client.post(f'/api/v1/student/quizzes/{self.quiz.pk}/start/')
        self.assertIn(response.status_code, (200, 201), response.data)
        return response.data['id']

    def check(self, attempt_id, question, option):
        return self.client.post(f'/api/v1/student/quiz-attempts/{attempt_id}/answer/',
            {'question': question.pk, 'selected_option': option.pk}, format='json')

    def submit(self, attempt_id, answers=()):
        return self.client.post(f'/api/v1/student/quiz-attempts/{attempt_id}/submit/',
            {'answers': [{'question': q.pk, 'selected_option': o.pk} for q, o in answers]}, format='json')


class QuizSectionTests(ModuleQuizSetup):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.teacher)

    def create(self, **data):
        return self.client.post('/api/v1/quizzes/', {'course': self.course.pk, 'title': 'Quiz', **data},
            format='json')

    def test_one_quiz_per_module(self):
        response = self.create(section='Forces and motion')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {'section': ['This module already has a quiz.']})
        response = self.create(section='Energy', pass_percentage=60, max_attempts=2)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['section'], 'Energy')
        self.assertFalse(response.data['is_published'])
        self.assertFalse(response.data['has_completed_attempts'])

    def test_section_text_is_compared_exactly(self):
        self.assertEqual(self.create(section='forces and motion').status_code, 201)
        self.assertEqual(self.create(section=' Forces and motion').data['section'], ' Forces and motion')

    def test_quizzes_without_a_section_do_not_collide(self):
        for _ in range(2):
            response = self.create()
            self.assertEqual(response.status_code, 201, response.data)
            self.assertIsNone(response.data['section'])
        self.assertIsNone(self.create(section='').data['section'])
        self.assertEqual(Quiz.objects.filter(course=self.course, section__isnull=True).count(), 3)

    def test_rename_module_and_rename_onto_a_taken_module(self):
        energy = Quiz.objects.create(course=self.course, title='Energy', section='Energy')
        response = self.client.patch(f'/api/v1/quizzes/{energy.pk}/', {'section': 'Work and energy'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['section'], 'Work and energy')
        response = self.client.patch(f'/api/v1/quizzes/{energy.pk}/', {'section': 'Forces and motion'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('section', response.data)
        # Saving the quiz's own section again is not a clash.
        response = self.client.patch(f'/api/v1/quizzes/{self.quiz.pk}/', {'section': 'Forces and motion'},
            format='json')
        self.assertEqual(response.status_code, 200)

    def test_database_rejects_a_duplicate_module(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Quiz.objects.create(course=self.course, title='Again', section='Forces and motion')

    def test_list_filters_by_course(self):
        other = Course.objects.create(title='Maths', instructor=self.teacher, course_type='skill')
        Quiz.objects.create(course=other, title='Algebra')
        response = self.client.get('/api/v1/quizzes/', {'course': self.course.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([q['id'] for q in response.data], [self.quiz.pk])
        self.assertEqual(len(self.client.get('/api/v1/quizzes/').data), 2)
        self.assertEqual(self.client.get('/api/v1/quizzes/', {'course': 'abc'}).status_code, 400)
        question = response.data[0]['questions'][0]
        self.assertEqual(question['hint'], 'A push or a pull.')
        self.assertEqual(question['explanation'], 'A newton (N) is the SI unit of force.')
        self.assertIn('is_correct', question['options'][0])

    def test_question_create_with_hint_and_explanation(self):
        draft = Quiz.objects.create(course=self.course, title='Draft', section='Energy')
        response = self.client.post('/api/v1/questions/', {'quiz': draft.pk, 'text': 'What is work?', 'marks': 1,
            'points': 0, 'order': 0, 'hint': 'Force times distance.', 'explanation': 'W = F x d.'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Question.objects.get(pk=response.data['id']).explanation, 'W = F x d.')

    def test_publishing_still_requires_a_complete_quiz(self):
        draft = Quiz.objects.create(course=self.course, title='Draft', section='Energy')
        url = f'/api/v1/quizzes/{draft.pk}/'
        self.assertEqual(self.client.patch(url, {'is_published': True}, format='json').status_code, 400)
        question = Question.objects.create(quiz=draft, text='Q')
        QuestionOption.objects.create(question=question, text='A')
        QuestionOption.objects.create(question=question, text='B')
        self.assertEqual(self.client.patch(url, {'is_published': True}, format='json').status_code, 400)
        QuestionOption.objects.filter(question=question, text='A').update(is_correct=True)
        self.assertEqual(self.client.patch(url, {'is_published': True}, format='json').status_code, 200)


class QuizLockTests(ModuleQuizSetup):
    def complete_attempt(self):
        QuizAttempt.objects.create(student=self.student, quiz=self.quiz, completed_at=timezone.now())

    def test_questions_and_options_lock_after_a_completed_attempt(self):
        QuizAttempt.objects.create(student=self.student, quiz=self.quiz)  # Open attempts do not lock.
        self.client.force_authenticate(self.teacher)
        self.assertEqual(self.client.patch(f'/api/v1/questions/{self.q1.pk}/', {'text': 'Edited'},
            format='json').status_code, 200)
        self.complete_attempt()
        locked = {'detail': 'This quiz already has attempts, so its questions are locked.'}
        for method, url, data in [
            ('patch', f'/api/v1/questions/{self.q1.pk}/', {'text': 'Again'}),
            ('delete', f'/api/v1/questions/{self.q1.pk}/', None),
            ('patch', f'/api/v1/question-options/{self.q1_wrong.pk}/', {'text': 'Again'}),
            ('delete', f'/api/v1/question-options/{self.q1_wrong.pk}/', None),
            ('post', '/api/v1/questions/', {'quiz': self.quiz.pk, 'text': 'New'}),
            ('post', '/api/v1/question-options/', {'question': self.q1.pk, 'text': 'New'}),
        ]:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, data, format='json')
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data, locked)
        self.assertEqual(Question.objects.get(pk=self.q1.pk).text, 'Edited')
        self.assertTrue(QuestionOption.objects.filter(pk=self.q1_wrong.pk).exists())

    def test_settings_stay_editable_and_flag_is_reported(self):
        self.complete_attempt()
        self.client.force_authenticate(self.teacher)
        response = self.client.patch(f'/api/v1/quizzes/{self.quiz.pk}/',
            {'title': 'Forces', 'pass_percentage': 50, 'max_attempts': 3, 'section': 'Forces'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['has_completed_attempts'])
        self.assertTrue(self.client.get('/api/v1/quizzes/').data[0]['has_completed_attempts'])

    def test_cannot_move_a_question_into_a_locked_quiz(self):
        draft = Quiz.objects.create(course=self.course, title='Draft', section='Energy')
        loose = Question.objects.create(quiz=draft, text='Loose')
        self.complete_attempt()
        self.client.force_authenticate(self.teacher)
        response = self.client.patch(f'/api/v1/questions/{loose.pk}/', {'quiz': self.quiz.pk}, format='json')
        self.assertEqual(response.status_code, 400)


class StudentQuizViewTests(ModuleQuizSetup):
    def test_student_quiz_shows_hint_but_not_answers(self):
        response = self.client.get(f'/api/v1/student/quizzes/{self.quiz.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['section'], 'Forces and motion')
        question = response.data['questions'][0]
        self.assertEqual(question['hint'], 'A push or a pull.')
        self.assertNotIn('explanation', question)
        self.assertEqual(set(question['options'][0]), {'id', 'text'})

    def test_course_quiz_list_has_section_and_question_count(self):
        Quiz.objects.create(course=self.course, title='Draft', section='Energy')
        QuizAttempt.objects.create(student=self.student, quiz=self.quiz, completed_at=timezone.now(), percentage=50)
        QuizAttempt.objects.create(student=self.student, quiz=self.quiz, completed_at=timezone.now(), percentage=80)
        rows = self.client.get(f'/api/v1/courses/{self.course.pk}/quizzes/').data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['section'], 'Forces and motion')
        self.assertEqual(rows[0]['question_count'], 2)
        self.assertEqual(rows[0]['attempts_used'], 2)  # Not multiplied by the question count.
        self.client.force_authenticate(self.teacher)
        rows = self.client.get(f'/api/v1/courses/{self.course.pk}/quizzes/').data
        self.assertEqual([(r['section'], r['question_count']) for r in rows], [('Forces and motion', 2), ('Energy', 0)])


class CheckAnswerTests(ModuleQuizSetup):
    def test_wrong_then_right_answer(self):
        attempt = self.start()
        response = self.check(attempt, self.q1, self.q1_wrong)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {'is_correct': False, 'correct_option': self.q1_right.pk,
            'explanation': 'A newton (N) is the SI unit of force.', 'marks_awarded': '0.00'})
        response = self.check(attempt, self.q2, self.q2_right)
        self.assertEqual(response.data, {'is_correct': True, 'correct_option': self.q2_right.pk,
            'explanation': '', 'marks_awarded': '1.00'})

    def test_second_check_is_rejected_and_keeps_the_first(self):
        attempt = self.start()
        self.check(attempt, self.q1, self.q1_wrong)
        response = self.check(attempt, self.q1, self.q1_right)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {'code': 'ALREADY_ANSWERED', 'detail': 'This question was already answered.'})
        answer = StudentAnswer.objects.get(attempt_id=attempt, question=self.q1)
        self.assertEqual(answer.selected_option_id, self.q1_wrong.pk)
        self.assertFalse(answer.is_correct)

    def test_question_and_option_must_match(self):
        attempt = self.start()
        other_quiz = Quiz.objects.create(course=self.course, title='Other', section='Energy')
        foreign, foreign_option, _ = self.question(other_quiz, 'Foreign', 0)
        response = self.check(attempt, foreign, foreign_option)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['detail'], f'Question {foreign.pk} does not belong to this quiz.')
        response = self.check(attempt, self.q1, self.q2_right)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['detail'], f'Option {self.q2_right.pk} does not belong to question {self.q1.pk}.')
        response = self.client.post(f'/api/v1/student/quiz-attempts/{attempt}/answer/', {}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(StudentAnswer.objects.exists())

    def test_only_the_owner_while_enrolled_and_before_submit(self):
        attempt = self.start()
        self.client.force_authenticate(self.stranger)
        self.assertEqual(self.check(attempt, self.q1, self.q1_right).status_code, 404)
        self.client.force_authenticate(self.student)
        Enrollment.objects.filter(student=self.student).update(status='cancelled')
        response = self.check(attempt, self.q1, self.q1_right)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['code'], 'NOT_ENROLLED')
        Enrollment.objects.filter(student=self.student).update(status='active')
        self.assertEqual(self.submit(attempt, [(self.q1, self.q1_right), (self.q2, self.q2_right)]).status_code, 200)
        response = self.check(attempt, self.q1, self.q1_right)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['detail'], 'This quiz attempt has already been submitted.')
        self.assertFalse(StudentAnswer.objects.filter(attempt_id=attempt).exclude(
            question__in=[self.q1, self.q2]).exists())


class SubmitAfterCheckTests(ModuleQuizSetup):
    def test_submit_with_every_answer_checked_and_nothing_sent(self):
        attempt = self.start()
        self.check(attempt, self.q1, self.q1_right)
        self.check(attempt, self.q2, self.q2_wrong)
        response = self.submit(attempt)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['attempt']['score'], '1.00')
        self.assertEqual(response.data['attempt']['percentage'], '50.00')
        self.assertFalse(response.data['attempt']['is_passed'])
        self.assertIsNotNone(response.data['attempt']['completed_at'])
        self.assertEqual(response.data['points_earned'], 5)
        self.assertEqual(StudentAnswer.objects.filter(attempt_id=attempt).count(), 2)

    def test_resent_options_cannot_change_checked_answers(self):
        attempt = self.start()
        self.check(attempt, self.q1, self.q1_wrong)
        response = self.submit(attempt, [(self.q1, self.q1_right), (self.q2, self.q2_right)])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['attempt']['percentage'], '50.00')
        self.assertEqual(StudentAnswer.objects.get(attempt_id=attempt, question=self.q1).selected_option_id,
            self.q1_wrong.pk)
        self.assertEqual(response.data['points_earned'], 0)

    def test_mixed_checked_and_submitted_answers(self):
        attempt = self.start()
        self.check(attempt, self.q1, self.q1_right)
        response = self.submit(attempt, [(self.q2, self.q2_right)])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['attempt']['percentage'], '100.00')
        self.assertTrue(response.data['attempt']['is_passed'])

    def test_skipping_a_question_is_still_rejected(self):
        attempt = self.start()
        self.check(attempt, self.q1, self.q1_right)
        for answers in [(), [(self.q1, self.q1_right)]]:
            response = self.submit(attempt, answers)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data['detail'], 'You must answer every question before submitting the quiz.')
        self.assertIsNone(QuizAttempt.objects.get(pk=attempt).completed_at)

    def test_points_are_awarded_once_across_attempts(self):
        first = self.start()
        self.check(first, self.q1, self.q1_right)
        self.assertEqual(self.submit(first, [(self.q2, self.q2_right)]).data['points_earned'], 5)
        second = self.start()
        self.check(second, self.q1, self.q1_right)
        self.check(second, self.q2, self.q2_right)
        self.assertEqual(self.submit(second).data['points_earned'], 0)
        self.assertEqual(PointTransaction.objects.filter(student=self.student, question=self.q1).count(), 1)

    def test_classic_submit_without_checking_still_works(self):
        attempt = self.start()
        response = self.submit(attempt, [(self.q1, self.q1_right), (self.q2, self.q2_right)])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['attempt']['percentage'], '100.00')
        self.assertEqual(self.submit(attempt, [(self.q1, self.q1_right)]).status_code, 400)
        self.assertEqual(self.client.post(f'/api/v1/student/quiz-attempts/{attempt}/submit/', {},
            format='json').status_code, 400)

    def test_max_attempts_still_enforced(self):
        for _ in range(2):
            attempt = self.start()
            self.check(attempt, self.q1, self.q1_right)
            self.check(attempt, self.q2, self.q2_right)
            self.assertEqual(self.submit(attempt).status_code, 200)
        response = self.client.post(f'/api/v1/student/quizzes/{self.quiz.pk}/start/')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'MAX_ATTEMPTS_REACHED')
