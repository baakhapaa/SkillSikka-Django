"""The Resources tab on a **skill** course, and per-lesson attachment.

`test_bootcamps.py` covers the endpoint's original home. This file covers what
changed on 2026-10-29: the resource table is no longer bootcamp-only and a row
may now belong to one lesson, so the builder can attach files while editing a
lesson and the player can show the current lesson's pack.
"""
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.models import (
    Course,
    CourseInstructor,
    CourseResource,
    Enrollment,
    Lesson,
    Role,
    User,
)


class CourseResourceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = self.user('admin', 'super_admin')
        self.owner = self.user('owner', 'instructor', verification_status='verified')
        self.coach = self.user('coach', 'instructor', verification_status='verified')
        self.stranger = self.user('stranger', 'instructor', verification_status='verified')
        self.student = self.user('student', 'student')

        self.course = Course.objects.create(
            title='Flutter Foundations',
            instructor=self.owner,
            course_type='skill',
            is_published=True,
        )
        CourseInstructor.objects.create(course=self.course, instructor=self.owner, role='lead')
        CourseInstructor.objects.create(course=self.course, instructor=self.coach, role='coach', order=1)
        self.lesson = Lesson.objects.create(course=self.course, title='Widgets', content_type='video', order=0)
        self.client.force_authenticate(self.student)

    # ── helpers ───────────────────────────────────────────────────────────────

    def user(self, name, role, **kwargs):
        return User.objects.create_user(
            email=f'{name}@example.com', name=name, role=Role.objects.get(name=role), **kwargs
        )

    def url(self, suffix='', course=None):
        return f'/api/v1/courses/{(course or self.course).pk}/{suffix}'

    def enroll(self, status='active', user=None):
        return Enrollment.objects.update_or_create(
            student=user or self.student, course=self.course, defaults={'status': status}
        )[0]

    def resource(self, **kwargs):
        return CourseResource.objects.create(
            course=kwargs.pop('course', self.course),
            title=kwargs.pop('title', 'Starter project'),
            file_format=kwargs.pop('file_format', 'zip'),
            file_url=kwargs.pop('file_url', 'https://example.com/starter.zip'),
            **kwargs,
        )

    def post(self, payload):
        return self.client.post(self.url('resources/'), payload, format='json')

    # ── reading ───────────────────────────────────────────────────────────────

    def test_read_requires_enrollment(self):
        """A file is course material, not a public conversation."""
        self.resource()
        for state in [None, 'pending_payment', 'cancelled']:
            Enrollment.objects.filter(course=self.course).delete()
            if state:
                self.enroll(state)
            response = self.client.get(self.url('resources/'))
            self.assertEqual(response.status_code, 403, state)
            self.assertEqual(response.data['code'], 'NOT_ENROLLED')
        for state in ['active', 'completed']:
            Enrollment.objects.filter(course=self.course).delete()
            self.enroll(state)
            self.assertEqual(self.client.get(self.url('resources/')).status_code, 200)

    def test_staff_read_without_enrollment(self):
        self.resource()
        for user in [self.admin, self.owner, self.coach]:
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(self.url('resources/')).status_code, 200, user.name)

    def test_unpublished_course_hidden_from_students(self):
        self.resource()
        self.enroll()
        Course.objects.filter(pk=self.course.pk).update(is_published=False)
        self.assertEqual(self.client.get(self.url('resources/')).status_code, 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(self.url('resources/')).status_code, 200)

    # ── writing ───────────────────────────────────────────────────────────────

    def test_owner_roster_and_admin_may_attach(self):
        payload = {'title': 'Workbook', 'file_format': 'xlsx', 'file_url': 'https://example.com/w.xlsx', 'lesson': self.lesson.pk}
        for user in [self.admin, self.owner, self.coach]:
            self.client.force_authenticate(user)
            response = self.post(payload)
            self.assertEqual(response.status_code, 201, (user.name, response.data))
            self.assertEqual(response.data['lesson'], self.lesson.pk)
            self.assertEqual(response.data['lesson_title'], 'Widgets')
            self.assertEqual(response.data['course'], self.course.pk)

    def test_enrolled_student_may_not_attach(self):
        self.enroll()
        response = self.post({'title': 'Mine', 'file_format': 'pdf', 'file_url': 'https://example.com/x.pdf'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['code'], 'NOT_COURSE_OWNER')

    def test_unrelated_instructor_may_not_attach(self):
        self.client.force_authenticate(self.stranger)
        response = self.post({'title': 'Mine', 'file_format': 'pdf', 'file_url': 'https://example.com/x.pdf'})
        self.assertEqual(response.status_code, 403)

    def test_lesson_from_another_course_is_refused(self):
        other = Course.objects.create(title='Other', instructor=self.owner, course_type='skill', is_published=True)
        foreign = Lesson.objects.create(course=other, title='Theirs', content_type='video')
        self.client.force_authenticate(self.owner)
        response = self.post({'title': 'Wrong', 'file_format': 'pdf', 'file_url': 'https://example.com/x.pdf', 'lesson': foreign.pk})
        self.assertEqual(response.status_code, 400)
        self.assertIn('lesson', response.data)

    def test_patch_and_delete_are_owner_scoped(self):
        resource = self.resource()
        other = Course.objects.create(title='Other', instructor=self.owner, course_type='skill', is_published=True)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.patch(self.url(f'resources/{resource.pk}/'), {'title': 'Renamed'}, format='json').status_code, 200)
        # A resource id from one course is invisible under another course's URL.
        self.assertEqual(self.client.patch(self.url(f'resources/{resource.pk}/', other), {'title': 'Nope'}, format='json').status_code, 404)
        self.assertEqual(self.client.delete(self.url(f'resources/{resource.pk}/', other)).status_code, 404)
        self.assertEqual(self.client.delete(self.url(f'resources/{resource.pk}/')).status_code, 204)
        self.assertFalse(CourseResource.objects.filter(pk=resource.pk).exists())

    # ── per-lesson ────────────────────────────────────────────────────────────

    def test_filter_by_lesson(self):
        second = Lesson.objects.create(course=self.course, title='State', content_type='video', order=1)
        self.resource(title='Lesson file', lesson=self.lesson)
        self.resource(title='Other file', lesson=second)
        self.resource(title='Course-wide file')
        self.enroll()
        self.client.force_authenticate(self.student)

        everything = self.client.get(self.url('resources/')).data
        self.assertEqual(len(everything), 3)
        only = self.client.get(self.url('resources/'), {'lesson': self.lesson.pk}).data
        self.assertEqual([row['title'] for row in only], ['Lesson file'])
        self.assertEqual(self.client.get(self.url('resources/'), {'lesson': 999999}).data, [])

    def test_lesson_delete_takes_its_resources(self):
        self.resource(lesson=self.lesson)
        self.lesson.delete()
        self.assertEqual(CourseResource.objects.count(), 0)

    def test_detail_counts_resources_on_a_skill_course(self):
        """The detail page's `N support files` row reads this count."""
        self.resource(lesson=self.lesson)
        self.client.force_authenticate(self.owner)
        detail = self.client.get(self.url()).data
        self.assertEqual(detail['resources_count'], 1)

    # ── upload ────────────────────────────────────────────────────────────────

    def test_upload_kind_resource_accepts_a_document(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        with override_settings(MEDIA_ROOT=media):
            self.client.force_authenticate(self.owner)
            upload = SimpleUploadedFile('starter.zip', b'PK\x03\x04payload', content_type='application/zip')
            response = self.client.post(self.url('assets/'), {'file': upload, 'kind': 'resource'}, format='multipart')
            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(response.data['kind'], 'resource')
            self.assertIn('course-assets/resource/', response.data['path'])
            self.assertTrue(response.data['url'].startswith('http'))

    def test_upload_kind_resource_refuses_a_video(self):
        self.client.force_authenticate(self.owner)
        upload = SimpleUploadedFile('clip.mp4', b'\x00\x00\x00\x18ftypmp42', content_type='video/mp4')
        response = self.client.post(self.url('assets/'), {'file': upload, 'kind': 'resource'}, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertIn('file', response.data)

    def test_upload_kind_is_whitelisted(self):
        self.client.force_authenticate(self.owner)
        upload = SimpleUploadedFile('a.pdf', b'%PDF-1.4', content_type='application/pdf')
        response = self.client.post(self.url('assets/'), {'file': upload, 'kind': 'everything'}, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertIn('kind', response.data)

    def test_upload_by_enrolled_student_is_refused(self):
        self.enroll()
        upload = SimpleUploadedFile('a.pdf', b'%PDF-1.4', content_type='application/pdf')
        response = self.client.post(self.url('assets/'), {'file': upload, 'kind': 'resource'}, format='multipart')
        self.assertEqual(response.status_code, 403)

    # ── batch upload ──────────────────────────────────────────────────────────
    #
    # One pick of worksheets is one request. Before this, attaching five files
    # from the lesson sheet was five uploads in a row, and a 20-lesson course
    # meant 21 round-trips.

    def _media(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        return media

    def _pdf(self, name='a.pdf'):
        return SimpleUploadedFile(name, b'%PDF-1.4', content_type='application/pdf')

    def test_upload_batch_stores_every_file_in_one_request(self):
        with override_settings(MEDIA_ROOT=self._media()):
            self.client.force_authenticate(self.owner)
            files = [
                self._pdf('worksheet.pdf'),
                SimpleUploadedFile(
                    'template.docx',
                    b'PK\x03\x04doc',
                    content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                ),
            ]
            response = self.client.post(
                self.url('assets/'), {'files': files, 'kind': 'resource'}, format='multipart'
            )

            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual([asset['index'] for asset in response.data['assets']], [0, 1])
            self.assertEqual(
                [asset['name'] for asset in response.data['assets']],
                ['worksheet.pdf', 'template.docx'],
            )
            self.assertEqual(response.data['rejected'], [])
            for asset in response.data['assets']:
                self.assertIn('course-assets/resource/', asset['path'])
                self.assertTrue(asset['url'].startswith('http'))

    def test_upload_batch_keeps_the_good_files_and_names_the_bad_one(self):
        """One refusal must not discard the rest of the pick."""
        with override_settings(MEDIA_ROOT=self._media()):
            self.client.force_authenticate(self.owner)
            files = [
                self._pdf('good.pdf'),
                SimpleUploadedFile('clip.mp4', b'\x00\x00\x00\x18ftypmp42', content_type='video/mp4'),
                self._pdf('also-good.pdf'),
            ]
            response = self.client.post(
                self.url('assets/'), {'files': files, 'kind': 'resource'}, format='multipart'
            )

            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual([asset['index'] for asset in response.data['assets']], [0, 2])
            self.assertEqual(len(response.data['rejected']), 1)
            rejected = response.data['rejected'][0]
            # The index is what lets the client map results back onto the pick
            # order without matching filenames.
            self.assertEqual(rejected['index'], 1)
            self.assertEqual(rejected['name'], 'clip.mp4')
            self.assertIn('video/mp4', rejected['error'])

    def test_upload_batch_is_capped(self):
        self.client.force_authenticate(self.owner)
        files = [self._pdf(f'{index}.pdf') for index in range(11)]
        response = self.client.post(
            self.url('assets/'), {'files': files, 'kind': 'resource'}, format='multipart'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('files', response.data)

    def test_upload_with_no_file_at_all_is_still_a_400(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(self.url('assets/'), {'kind': 'resource'}, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertIn('file', response.data)

    # ── a draft's files, which is what the builder reads ──────────────────────

    def test_manager_reads_a_drafts_resources(self):
        """The builder lists what it already attached, before publishing."""
        self.resource()
        Course.objects.filter(pk=self.course.pk).update(is_published=False)
        for user in [self.owner, self.coach, self.admin]:
            self.client.force_authenticate(user)
            response = self.client.get(self.url('resources/'))
            self.assertEqual(response.status_code, 200, user.name)
            self.assertEqual(len(response.data), 1)

    def test_manager_attaches_a_course_wide_file_to_a_draft(self):
        Course.objects.filter(pk=self.course.pk).update(is_published=False)
        self.client.force_authenticate(self.owner)
        response = self.post({
            'title': 'Workbook',
            'file_format': 'xlsx',
            'file_url': 'https://example.com/w.xlsx',
        })
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(response.data['lesson'])
        self.assertEqual(CourseResource.objects.filter(lesson__isnull=True).count(), 1)

    def test_a_draft_stays_shut_to_everyone_else(self):
        self.resource()
        Course.objects.filter(pk=self.course.pk).update(is_published=False)
        self.enroll()
        self.assertEqual(self.client.get(self.url('resources/')).status_code, 403)
        self.client.force_authenticate(self.stranger)
        self.assertEqual(self.client.get(self.url('resources/')).status_code, 403)
