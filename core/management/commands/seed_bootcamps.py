"""Deterministic development fixtures. example.com resource URLs are placeholders, not production media."""
from datetime import date
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from core.models import (Course, BootcampProfile, CourseInstructor, Lesson, BootcampResource,
    BootcampDiscussion, DiscussionLike, Enrollment, LessonProgress, User)


class Command(BaseCommand):
    help = 'Seed two bootcamps using existing verified instructors; creates no accounts or payments.'

    @transaction.atomic
    def handle(self, *args, **options):
        teachers = list(User.objects.filter(role__name='instructor', is_active=True,
            verification_status='verified').order_by('pk')[:8])
        if not teachers:
            raise CommandError('No active verified instructor exists. No accounts or bootcamps were created.')
        if len(teachers) < 8:
            self.stdout.write(f'Sundarbazar roster shortfall: {8 - len(teachers)}; using {len(teachers)} existing verified instructors.')
        students = list(User.objects.filter(role__name='student', is_active=True).order_by('pk')[:10])
        authors = students + teachers
        if len(students) < 10:
            self.stdout.write(f'Only {len(students)} existing students available; discussions also use existing instructors. No accounts created.')
        courses = []
        for venue, days, start, end, state, lesson_count, resource_count, discussion_count in [
            ('Sundarbazar', 4, date(2026, 9, 21), date(2026, 9, 24), 'completed', 20, 14, 10),
            ('Palungtar', 7, date(2026, 11, 16), date(2026, 11, 22), 'upcoming', 14, 8, 4),
        ]:
            # Venue and dates form the fixture identity, not the shared course title.
            profile = BootcampProfile.objects.filter(venue_name=venue, starts_on=start,
                course__course_type='bootcamp', course__title='ICT & AI Bootcamp').select_related('course').first()
            if profile:
                course = profile.course
            else:
                course = Course.objects.create(title='ICT & AI Bootcamp', course_type='bootcamp', instructor=teachers[0])
            course.instructor = teachers[0]
            course.description = f'A practical {days}-day ICT and AI workshop in {venue}: digital skills, responsible AI and collaborative projects.'
            course.is_paid, course.price, course.is_published = False, None, True
            course.subject = course.grade = None
            course.learning_outcomes = ['Use digital tools safely.', 'Evaluate AI-generated information.', 'Build and present a practical project.']
            course.requirements = ['Bring a laptop where available.', 'No prior programming experience required.']
            course.save()
            BootcampProfile.objects.update_or_create(course=course, defaults={
                'venue_name': venue, 'days': days, 'starts_on': start, 'ends_on': end, 'status': state,
                'episode_no': 1 if days == 4 else 2, 'short_description': f'Hands-on ICT and responsible AI learning in {venue}.',
                'hero_video_url': 'https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4',
                'quality_label': 'HD'})
            roster = teachers if days == 4 else teachers[:3]
            CourseInstructor.objects.filter(course=course).exclude(instructor__in=roster).delete()
            for index, teacher in enumerate(roster):
                CourseInstructor.objects.update_or_create(course=course, instructor=teacher, defaults={
                    'role': 'lead' if index == 0 else ('coach' if index < 4 else 'guest'), 'order': index})
            topics = [
                ('Digital Foundations', ['Demo', 'Device and file management', 'Internet research', 'Cyber safety', 'Collaborative documents']),
                ('Productivity and Data', ['Document design', 'Spreadsheet formulas', 'Charts and data stories', 'Presentation design', 'Team productivity challenge']),
                ('Responsible AI', ['How AI learns', 'Prompt writing', 'Checking AI answers', 'Privacy and bias', 'Creative AI workshop']),
                ('Build and Share', ['Project planning', 'Prototype a solution', 'Test with peers', 'Prepare a pitch', 'Project showcase']),
            ]
            lessons = []
            for index in range(lesson_count):
                if days == 4:
                    section, titles = topics[index // 5]
                    title, day = titles[index % 5], index // 5 + 1
                else:
                    section = ['Digital Foundations', 'Online Safety', 'Productivity', 'Data Skills', 'Responsible AI', 'Creative Prototyping', 'Project Showcase'][index // 2]
                    title = 'Demo' if index == 0 else f'{section}: {"Guided practice" if index % 2 == 0 else "Hands-on challenge"}'
                    day = index // 2 + 1
                lesson, _ = Lesson.objects.update_or_create(course=course, order=index + 1, defaults={
                    'title': title, 'section': section, 'day_number': day, 'duration_seconds': 300 + index * 30,
                    'content_type': 'video', 'content_url': 'https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4',
                    'is_preview': index == 0})
                lessons.append(lesson)
            formats = ['pdf', 'doc', 'xls', 'figma', 'svg', 'zip', 'docx', 'xlsx', 'link', 'other']
            for index in range(resource_count):
                fmt = formats[index % len(formats)]
                BootcampResource.objects.update_or_create(course=course, order=index + 1, defaults={
                    'section': ['Workshop Guides', 'Practice Files', 'Project Toolkit'][index % 3],
                    'title': f'{["Digital safety checklist", "AI prompt workbook", "Project planning template", "Data practice sheet", "Design starter kit"][index % 5]} {index + 1}',
                    'file_format': fmt, 'file_url': f'https://example.com/bootcamp-demo/{venue.lower()}/resource-{index + 1}.{fmt}',
                    'file_size_bytes': None})
            prompts = ['What did you learn today?', 'Share your favourite keyboard shortcut.', 'How can we check an AI answer?',
                'Which spreadsheet formula helped you?', 'Share a safe research tip.', 'What should our project solve?',
                'How can we protect personal data?', 'What makes a useful prompt?', 'Share feedback on the team activity.', 'What will you practice next?']
            threads = []
            for index in range(discussion_count):
                thread, _ = BootcampDiscussion.objects.get_or_create(course=course, parent=None, body=prompts[index],
                    defaults={'author': authors[index % len(authors)]})
                threads.append(thread)
            for index in range(2):
                BootcampDiscussion.objects.get_or_create(course=course, parent=threads[index], body='I will try this in the next practice session.',
                    defaults={'author': teachers[index % len(teachers)]})
            DiscussionLike.objects.get_or_create(discussion=threads[0], user=teachers[0])
            courses.append(course)
            if venue == 'Sundarbazar':
                student = User.objects.filter(email__iexact='student@skillsikka.com', role__name='student').first()
                if student:
                    enrollment, _ = Enrollment.objects.update_or_create(student=student, course=course, defaults={'status': 'active'})
                    # This free-course fixture has exactly the first two completed lessons.
                    LessonProgress.objects.filter(student=student, lesson__course=course).exclude(lesson__in=lessons[:2]).delete()
                    for lesson in lessons[:2]:
                        LessonProgress.objects.update_or_create(student=student, lesson=lesson, defaults={
                            'enrollment': enrollment, 'is_completed': True, 'completed_at': timezone.now()})
                else:
                    self.stdout.write('student@skillsikka.com missing: enrollment/progress fixtures skipped.')
        self.stdout.write('Demo resource URLs use example.com placeholders; video is a public CC0 sample, not bootcamp footage.')
        for model, label, filters in [
            (Course, 'courses', {'pk__in': [c.pk for c in courses]}),
            (BootcampProfile, 'profiles', {'course__in': courses}), (CourseInstructor, 'roster', {'course__in': courses}),
            (Lesson, 'lessons', {'course__in': courses}), (BootcampResource, 'resources', {'course__in': courses}),
            (BootcampDiscussion, 'top-level discussions', {'course__in': courses, 'parent': None}),
            (BootcampDiscussion, 'replies', {'course__in': courses, 'parent__isnull': False}),
            (DiscussionLike, 'likes', {'discussion__course__in': courses}), (Enrollment, 'enrollments', {'course__in': courses}),
            (LessonProgress, 'progress', {'lesson__course__in': courses}),
        ]:
            self.stdout.write(f'{label}: {model.objects.filter(**filters).count()}')
