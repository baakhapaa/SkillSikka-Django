"""The Q&A tab on a **skill** course.

`test_bootcamps.py` covers the endpoint's original home. This file covers what
changed on 2026-10-29: the discussion table is no longer bootcamp-only, so the
same three endpoints must serve every course type with the same rules —
readable by any authenticated user on a published course, writable only by
someone with access.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import (
    Course,
    CourseDiscussion,
    CourseInstructor,
    DiscussionLike,
    Enrollment,
    Role,
    User,
)


class CourseDiscussionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = self.user('admin', 'super_admin')
        self.owner = self.user('owner', 'instructor', verification_status='verified')
        self.coach = self.user('coach', 'instructor', verification_status='verified')
        self.stranger_instructor = self.user(
            'stranger', 'instructor', verification_status='verified'
        )
        self.student = self.user('student', 'student')
        self.other = self.user('other', 'student')

        self.course = Course.objects.create(
            title='Flutter Foundations',
            instructor=self.owner,
            course_type='skill',
            is_published=True,
        )
        CourseInstructor.objects.create(
            course=self.course, instructor=self.owner, role='lead'
        )
        CourseInstructor.objects.create(
            course=self.course, instructor=self.coach, role='coach', order=1
        )
        self.client.force_authenticate(self.student)

    # ── helpers ───────────────────────────────────────────────────────────────

    def user(self, name, role, **kwargs):
        return User.objects.create_user(
            email=f'{name}@example.com',
            name=name,
            role=Role.objects.get(name=role),
            **kwargs,
        )

    def url(self, suffix='', course=None):
        return f'/api/v1/courses/{(course or self.course).pk}/{suffix}'

    def enroll(self, status='active', user=None):
        return Enrollment.objects.update_or_create(
            student=user or self.student,
            course=self.course,
            defaults={'status': status},
        )[0]

    def thread(self, **kwargs):
        return CourseDiscussion.objects.create(
            course=kwargs.pop('course', self.course),
            author=kwargs.pop('author', self.student),
            body=kwargs.pop('body', 'How do I run the app on a device?'),
            **kwargs,
        )

    def post(self, body, **kwargs):
        return self.client.post(
            self.url('discussions/'), {'body': body, **kwargs}, format='json'
        )

    def error(self, response, code, status=400):
        self.assertEqual(response.status_code, status, response.data)
        self.assertEqual(response.data['code'], code)

    # ── reading ───────────────────────────────────────────────────────────────

    def test_read_requires_authentication(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url('discussions/')).status_code, 401)

    def test_enrolled_and_unenrolled_students_can_read(self):
        """Reading is not gated on enrollment — a preview watcher still sees Q&A."""
        self.thread()
        response = self.client.get(self.url('discussions/'))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            set(response.data), {'count', 'next', 'previous', 'results'}
        )
        self.assertEqual(response.data['count'], 1)
        row = response.data['results'][0]
        self.assertEqual(row['author']['name'], 'student')
        self.assertEqual(row['author']['role_label'], 'Student')
        self.assertTrue(row['is_mine'])
        self.assertEqual(row['replies_count'], 0)
        self.assertFalse(row['is_liked'])

    def test_unpublished_course_is_not_readable(self):
        self.course.is_published = False
        self.course.save(update_fields=['is_published'])
        self.error(
            self.client.get(self.url('discussions/')),
            'COURSE_NOT_PUBLISHED',
            403,
        )

    def test_unknown_course_is_404(self):
        self.error(
            self.client.get('/api/v1/courses/999999/discussions/'),
            'COURSE_NOT_FOUND',
            404,
        )

    # ── writing ───────────────────────────────────────────────────────────────

    def test_enrolled_student_can_post(self):
        self.enroll()
        response = self.post('What editor do you use?')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['body'], 'What editor do you use?')
        self.assertEqual(response.data['course'], self.course.pk)
        self.assertIsNone(response.data['parent'])
        self.assertTrue(response.data['is_mine'])
        self.assertEqual(CourseDiscussion.objects.count(), 1)

    def test_unenrolled_student_cannot_post(self):
        self.error(self.post('Hello'), 'NOT_ENROLLED', 403)

    def test_pending_payment_cannot_post(self):
        """Enrolled but unpaid grants no lesson access, so it grants no voice either."""
        self.enroll(status='pending_payment')
        self.error(self.post('Hello'), 'NOT_ENROLLED', 403)

    def test_completed_student_can_post(self):
        self.enroll(status='completed')
        self.assertEqual(self.post('Finished it').status_code, 201)

    def test_owner_roster_and_admin_can_post_without_enrollment(self):
        for user in [self.owner, self.coach, self.admin]:
            self.client.force_authenticate(user)
            response = self.post('Hello')
            self.assertEqual(
                response.status_code, 201, f'{user.email} was refused: {response.data}'
            )

    def test_unrelated_instructor_cannot_post(self):
        """A roster is per course. Being an instructor is not a skeleton key."""
        self.client.force_authenticate(self.stranger_instructor)
        self.error(self.post('Hello'), 'NOT_ENROLLED', 403)

    def test_empty_and_oversized_bodies(self):
        self.enroll()
        for body in [None, '', '   ']:
            data = {} if body is None else {'body': body}
            response = self.client.post(
                self.url('discussions/'), data, format='json'
            )
            self.error(response, 'BODY_REQUIRED')
        self.error(self.post('a' * 2001), 'BODY_TOO_LONG')
        self.assertEqual(self.post('a' * 2000).status_code, 201)

    # ── threading ─────────────────────────────────────────────────────────────

    def test_reply_and_reply_to_reply(self):
        self.enroll()
        parent = self.thread()
        response = self.post('Try the emulator.', parent=parent.pk)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['parent'], parent.pk)

        reply = CourseDiscussion.objects.get(pk=response.data['id'])
        nested = self.post('Thanks!', parent=reply.pk)
        self.error(nested, 'DISCUSSION_NOT_FOUND', 400)

    def test_reply_cannot_cross_courses(self):
        self.enroll()
        elsewhere = Course.objects.create(
            title='Other', instructor=self.owner, course_type='skill',
            is_published=True,
        )
        foreign = self.thread(course=elsewhere)
        self.error(self.post('Wrong thread', parent=foreign.pk), 'DISCUSSION_NOT_FOUND', 404)

    def test_parent_id_must_exist(self):
        self.enroll()
        self.error(self.post('Ghost', parent=999999), 'DISCUSSION_NOT_FOUND', 404)

    def test_replies_come_back_inline_and_counted(self):
        self.enroll()
        parent = self.thread()
        CourseDiscussion.objects.create(
            course=self.course, author=self.other, parent=parent, body='One'
        )
        CourseDiscussion.objects.create(
            course=self.course, author=self.other, parent=parent, body='Two'
        )
        row = self.client.get(self.url('discussions/')).data['results'][0]
        self.assertEqual(row['replies_count'], 2)
        self.assertEqual([r['body'] for r in row['replies']], ['One', 'Two'])

    # ── likes ─────────────────────────────────────────────────────────────────

    def test_like_and_unlike_are_idempotent(self):
        self.enroll()
        thread = self.thread()
        like = self.url(f'discussions/{thread.pk}/like/')

        first = self.client.post(like)
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(first.data, {'discussion_id': thread.pk, 'is_liked': True, 'likes_count': 1})
        self.assertEqual(self.client.post(like).data['likes_count'], 1)
        self.assertEqual(DiscussionLike.objects.count(), 1)

        removed = self.client.delete(like)
        self.assertEqual(removed.data['is_liked'], False)
        self.assertEqual(removed.data['likes_count'], 0)
        self.assertEqual(self.client.delete(like).data['likes_count'], 0)
        self.assertEqual(DiscussionLike.objects.count(), 0)

    def test_like_needs_access(self):
        thread = self.thread()
        self.error(
            self.client.post(self.url(f'discussions/{thread.pk}/like/')),
            'NOT_ENROLLED',
            403,
        )

    def test_hidden_thread_cannot_be_liked(self):
        self.enroll()
        thread = self.thread(is_hidden=True)
        self.error(
            self.client.post(self.url(f'discussions/{thread.pk}/like/')),
            'DISCUSSION_NOT_FOUND',
            404,
        )

    # ── moderation ────────────────────────────────────────────────────────────

    def test_author_deletes_own_thread_and_its_replies(self):
        self.enroll()
        parent = self.thread()
        reply = CourseDiscussion.objects.create(
            course=self.course, author=self.other, parent=parent, body='Reply'
        )
        DiscussionLike.objects.create(discussion=reply, user=self.other)

        response = self.client.delete(self.url(f'discussions/{parent.pk}/'))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(CourseDiscussion.objects.filter(pk=parent.pk).exists())
        self.assertFalse(CourseDiscussion.objects.filter(pk=reply.pk).exists())
        self.assertEqual(DiscussionLike.objects.count(), 0)

    def test_other_students_thread_cannot_be_deleted(self):
        self.enroll()
        thread = self.thread(author=self.other)
        response = self.client.delete(self.url(f'discussions/{thread.pk}/'))
        self.assertEqual(response.status_code, 403, response.data)
        self.assertTrue(CourseDiscussion.objects.filter(pk=thread.pk).exists())

    def test_admin_hides_and_students_stop_seeing_it(self):
        self.enroll()
        thread = self.thread()
        detail = self.url(f'discussions/{thread.pk}/')

        self.error(
            self.client.patch(detail, {'is_hidden': True}, format='json'),
            'ADMIN_ONLY',
            403,
        )

        self.client.force_authenticate(self.admin)
        response = self.client.patch(detail, {'is_hidden': True}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['is_hidden'])

        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.get(self.url('discussions/')).data['count'], 0)

        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(self.url('discussions/')).data['count'], 1)

    def test_hidden_reply_is_excluded_from_the_count(self):
        self.enroll()
        parent = self.thread()
        CourseDiscussion.objects.create(
            course=self.course, author=self.other, parent=parent, body='Visible'
        )
        CourseDiscussion.objects.create(
            course=self.course, author=self.other, parent=parent, body='Hidden',
            is_hidden=True,
        )
        row = self.client.get(self.url('discussions/')).data['results'][0]
        self.assertEqual(row['replies_count'], 1)
        self.assertEqual([r['body'] for r in row['replies']], ['Visible'])

    def test_moderation_accepts_only_is_hidden(self):
        self.enroll()
        thread = self.thread()
        self.client.force_authenticate(self.admin)
        response = self.client.patch(
            self.url(f'discussions/{thread.pk}/'),
            {'is_hidden': True, 'body': 'edited'},
            format='json',
        )
        self.assertEqual(response.status_code, 400, response.data)
