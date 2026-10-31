"""The two ICT & AI bootcamps, with the content the app used to hardcode.

**Why this command exists.** Until 2026-10-31 the bootcamp screen was a mock: its
20 lessons, their durations, the 14-file resource pack and the Q&A thread were
constants inside `lib/features/bootcamp/presentation/bootcamp_page.dart`. The
screen now reads `GET /courses/{id}/`, so without this seed it renders an empty
camp — the design's content has to live in the database instead of in Dart.

**The course is admin-only in the product**, and this command does not change
that: `require_bootcamp_admin` still refuses every non-admin write, the app's
builder has no bootcamp type, and the dashboard is the only place a human
creates one. A management command is a fixture loader for a development
database, not a product path — it creates no accounts and no payments.

**Re-runnable.** Identity is `(venue, starts_on)`, never the title: both camps
share the brand and differ by venue and run, and keying on the title would
duplicate them the first time someone renamed one.
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import (
    BootcampProfile,
    Course,
    CourseDiscussion,
    CourseInstructor,
    CourseResource,
    DiscussionLike,
    Enrollment,
    Lesson,
    LessonProgress,
    User,
)

# The design's curriculum, retitled for ICT & AI but keeping its shape: four
# sections of five, and the design's own durations in order (22:10 … 21:40).
# `day_number` is assigned by the run length, not stored here — the same 20
# lessons fill a 4-day camp five-a-day and a 7-day camp three-a-day.
CURRICULUM = [
    ('Digital Foundations', 'Welcome and bootcamp orientation', '22:10'),
    ('Digital Foundations', 'Devices, files and cloud storage', '18:45'),
    ('Digital Foundations', 'Researching safely on the open web', '18:45'),
    ('Digital Foundations', 'Cyber safety and account hygiene', '24:30'),
    ('Digital Foundations', 'Collaborative documents and shared folders', '19:15'),
    ('Productivity and Data', 'Designing documents that read clearly', '16:50'),
    ('Productivity and Data', 'Spreadsheet formulas that do the work', '27:20'),
    ('Productivity and Data', 'Turning numbers into charts and stories', '21:05'),
    ('Productivity and Data', 'Presentation design for a live audience', '32:40'),
    ('Productivity and Data', 'Team productivity challenge', '28:15'),
    ('Responsible AI', 'How machine learning actually learns', '25:30'),
    ('Responsible AI', 'Writing prompts that get usable answers', '20:10'),
    ('Responsible AI', 'Fact-checking AI output', '23:55'),
    ('Responsible AI', 'Privacy, bias and the limits of a model', '17:20'),
    ('Responsible AI', 'Creative AI workshop: images and audio', '34:10'),
    ('Build and Share', 'Planning a small project', '22:45'),
    ('Build and Share', 'Prototyping a solution', '26:30'),
    ('Build and Share', 'Testing with peers', '19:50'),
    ('Build and Share', 'Preparing the pitch', '15:25'),
    ('Build and Share', 'Project showcase and certificates', '21:40'),
]

# The Resources tab exactly as the design had it — same three sections, same
# fourteen files, same formats.
RESOURCES = [
    ('Section 1: Course Materials', 'Product Strategy Grid Template', 'pdf'),
    ('Section 1: Course Materials', 'Design Thinking Workbook', 'pdf'),
    ('Section 1: Course Materials', 'Stakeholder Interview Guide', 'doc'),
    ('Section 1: Course Materials', 'Competitive Analysis Framework', 'xls'),
    ('Section 1: Course Materials', 'User Survey Templates', 'pdf'),
    ('Section 2: Design Tools & Assets', 'Wireframing Kit', 'figma'),
    ('Section 2: Design Tools & Assets', 'Component Library', 'figma'),
    ('Section 2: Design Tools & Assets', 'Icon Pack', 'svg'),
    ('Section 2: Design Tools & Assets', 'Stock Photo Collection', 'zip'),
    ('Section 2: Design Tools & Assets', 'Color Palette Guide', 'pdf'),
    ('Section 3: Additional Reading', 'UX Research Best Practices', 'pdf'),
    ('Section 3: Additional Reading', 'Mobile Design Guidelines', 'pdf'),
    ('Section 3: Additional Reading', 'Accessibility Checklist', 'pdf'),
    ('Section 3: Additional Reading', 'Design System Documentation', 'pdf'),
]

THREADS = [
    'What did you learn today?',
    'Share your favourite keyboard shortcut.',
    'How can we check an AI answer?',
    'Which spreadsheet formula helped you?',
    'Share a safe research tip.',
    'What should our project solve?',
    'How can we protect personal data?',
    'What makes a useful prompt?',
    'Share feedback on the team activity.',
    'What will you practice next?',
]

# A public CC0 clip stands in for camp footage; the design's hero video was a
# bundled asset, and the server has no file of its own to point at.
HERO_VIDEO = 'https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4'

CAMPS = [
    {
        'venue': 'Sundarbazar',
        'days': 4,
        'starts_on': date(2026, 10, 19),
        'ends_on': date(2026, 10, 22),
        'status': 'completed',
        'episode_no': 2,
        'roster_size': 8,
    },
    {
        'venue': 'Palungtar',
        'days': 7,
        'starts_on': date(2026, 11, 16),
        'ends_on': date(2026, 11, 22),
        'status': 'upcoming',
        'episode_no': 3,
        'roster_size': 3,
    },
]

DESCRIPTION = (
    'Master the foundations of digital skills, responsible AI and collaborative '
    'project work. Learn to check what a model tells you, build something small '
    'and real, and present it to an audience.'
)
SHORT_DESCRIPTION = (
    'A hands-on camp in digital skills, data and responsible AI.'
)


def clock_to_seconds(value):
    """`22:10` → 1330. The design authored durations as mm:ss."""
    minutes, seconds = (int(part) for part in value.split(':'))
    return minutes * 60 + seconds


class Command(BaseCommand):
    help = (
        'Seed the 4-day and 7-day ICT & AI bootcamps with the design\'s '
        'curriculum and resource pack. Creates no accounts or payments.'
    )

    @transaction.atomic
    def handle(self, *args, **options):
        teachers = list(
            User.objects.filter(
                role__name='instructor', is_active=True, verification_status='verified'
            ).order_by('pk')
        )
        if not teachers:
            raise CommandError(
                'No active verified instructor exists. No accounts or bootcamps were created.'
            )

        courses = []
        for camp in CAMPS:
            course = self.upsert_course(camp, teachers)
            self.upsert_profile(course, camp)
            self.upsert_roster(course, camp, teachers)
            lessons = self.upsert_lessons(course, camp)
            self.upsert_resources(course, camp)
            self.upsert_threads(course, teachers)
            courses.append(course)
            if camp['venue'] == 'Sundarbazar':
                self.attach_demo_student(course, lessons)

        self.stdout.write(
            'Resource URLs are example.com placeholders and the video is a public '
            'CC0 sample, not camp footage.'
        )
        for model, label, filters in [
            (Course, 'courses', {'pk__in': [c.pk for c in courses]}),
            (BootcampProfile, 'profiles', {'course__in': courses}),
            (CourseInstructor, 'roster', {'course__in': courses}),
            (Lesson, 'lessons', {'course__in': courses}),
            (CourseResource, 'resources', {'course__in': courses}),
            (CourseDiscussion, 'top-level discussions', {'course__in': courses, 'parent': None}),
            (CourseDiscussion, 'replies', {'course__in': courses, 'parent__isnull': False}),
            (DiscussionLike, 'likes', {'discussion__course__in': courses}),
            (Enrollment, 'enrollments', {'course__in': courses}),
            (LessonProgress, 'progress', {'lesson__course__in': courses}),
        ]:
            self.stdout.write(f'{label}: {model.objects.filter(**filters).count()}')

    # ── pieces ───────────────────────────────────────────────────────────────

    def upsert_course(self, camp, teachers):
        profile = (
            BootcampProfile.objects.filter(
                venue_name=camp['venue'],
                starts_on=camp['starts_on'],
                course__course_type='bootcamp',
            )
            .select_related('course')
            .first()
        )
        if profile:
            course = profile.course
        else:
            course = Course.objects.create(
                title=f"ICT & AI BOOTCAMP at {camp['venue']}",
                course_type='bootcamp',
                instructor=teachers[0],
            )
        course.title = f"ICT & AI BOOTCAMP at {camp['venue']}"
        course.instructor = teachers[0]
        course.description = DESCRIPTION
        course.learning_outcomes = [
            'Use digital tools safely and confidently.',
            'Evaluate AI-generated information instead of trusting it.',
            'Build and present a small practical project.',
        ]
        course.requirements = [
            'Bring a laptop where one is available.',
            'No prior programming experience required.',
        ]
        course.is_paid, course.price, course.is_published = False, None, True
        course.subject = course.grade = None
        course.level = 'beginner'
        course.language = 'English'
        course.save()
        return course

    def upsert_profile(self, course, camp):
        BootcampProfile.objects.update_or_create(
            course=course,
            defaults={
                'venue_name': camp['venue'],
                'days': camp['days'],
                'starts_on': camp['starts_on'],
                'ends_on': camp['ends_on'],
                'status': camp['status'],
                'episode_no': camp['episode_no'],
                'short_description': SHORT_DESCRIPTION,
                'hero_video_url': HERO_VIDEO,
                # No poster: the app falls back to its bundled camp artwork, and
                # inventing an image URL would 404 on every device.
                'hero_poster_url': '',
                'quality_label': 'HD',
            },
        )

    def upsert_roster(self, course, camp, teachers):
        roster = teachers[: camp['roster_size']]
        if len(roster) < camp['roster_size']:
            # The design lists eight names; they are not accounts, and this
            # command does not create any. Say so rather than silently shipping
            # a one-person roster.
            self.stdout.write(
                f"{camp['venue']} roster: {len(roster)} of {camp['roster_size']} "
                'verified instructors available; no accounts were created.'
            )
        CourseInstructor.objects.filter(course=course).exclude(instructor__in=roster).delete()
        for index, teacher in enumerate(roster):
            CourseInstructor.objects.update_or_create(
                course=course,
                instructor=teacher,
                defaults={
                    'role': 'lead' if index == 0 else ('coach' if index < 4 else 'guest'),
                    'order': index,
                },
            )

    def upsert_lessons(self, course, camp):
        """Spread the same curriculum over the run.

        `index * days // 20 + 1` gives five lessons a day over four days and
        3/3/3/3/3/3/2 over seven, so both camps cover every day without a
        second curriculum to keep in sync.
        """
        lessons = []
        for index, (section, title, duration) in enumerate(CURRICULUM):
            day = index * camp['days'] // len(CURRICULUM) + 1
            lesson, _ = Lesson.objects.update_or_create(
                course=course,
                order=index + 1,
                defaults={
                    'title': title,
                    'section': section,
                    'day_number': day,
                    'duration_seconds': clock_to_seconds(duration),
                    'content_type': 'video',
                    'content_url': HERO_VIDEO,
                    'content_text': '',
                    'is_preview': index == 0,
                },
            )
            lessons.append(lesson)
        # A previous run with a longer curriculum would otherwise leave rows on
        # days the camp no longer has.
        Lesson.objects.filter(course=course, order__gt=len(CURRICULUM)).delete()
        return lessons

    def upsert_resources(self, course, camp):
        for index, (section, title, fmt) in enumerate(RESOURCES):
            CourseResource.objects.update_or_create(
                course=course,
                order=index + 1,
                defaults={
                    'section': section,
                    'title': title,
                    'file_format': fmt,
                    'file_url': (
                        'https://example.com/bootcamp-demo/'
                        f"{camp['venue'].lower()}/{index + 1}-"
                        f"{title.lower().replace(' ', '-').replace('&', 'and')}.{fmt}"
                    ),
                    'file_size_bytes': None,
                    'lesson': None,
                },
            )
        CourseResource.objects.filter(course=course, order__gt=len(RESOURCES)).delete()

    def upsert_threads(self, course, teachers):
        threads = []
        for body in THREADS:
            thread, _ = CourseDiscussion.objects.get_or_create(
                course=course,
                parent=None,
                body=body,
                defaults={'author': teachers[0]},
            )
            threads.append(thread)
        for index, thread in enumerate(threads[:2]):
            CourseDiscussion.objects.get_or_create(
                course=course,
                parent=thread,
                body='I will try this in the next practice session.',
                defaults={'author': teachers[index % len(teachers)]},
            )
        # The design shows like counts in the tens; those came from the mock, not
        # from rows, and faking them would need a crowd of accounts. One real
        # like is the honest version.
        DiscussionLike.objects.get_or_create(discussion=threads[0], user=teachers[0])

    def attach_demo_student(self, course, lessons):
        student = User.objects.filter(
            email__iexact='student@skillsikka.com', role__name='student'
        ).first()
        if student is None:
            self.stdout.write(
                'student@skillsikka.com missing: enrollment/progress fixtures skipped.'
            )
            return
        enrollment, _ = Enrollment.objects.update_or_create(
            student=student, course=course, defaults={'status': 'active'}
        )
        LessonProgress.objects.filter(student=student, lesson__course=course).exclude(
            lesson__in=lessons[:2]
        ).delete()
        for lesson in lessons[:2]:
            LessonProgress.objects.update_or_create(
                student=student,
                lesson=lesson,
                defaults={
                    'enrollment': enrollment,
                    'is_completed': True,
                    'completed_at': timezone.now(),
                },
            )
