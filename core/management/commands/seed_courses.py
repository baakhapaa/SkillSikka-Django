"""Development fixtures. Stable titles identify catalogue records across reruns."""
from decimal import Decimal
from importlib import import_module

from django.core.management.base import BaseCommand, CommandError
from django.apps import apps
from django.db import connection, transaction
from django.utils import timezone

from core.models import Course, CourseReview, Enrollment, Grade, LearningInterest, Lesson, LessonProgress, Subject, User, Quiz, Question, QuestionOption


class Command(BaseCommand):
    help = 'Seed a repeatable development course catalogue without creating credentials or payments.'

    @transaction.atomic
    def handle(self, *args, **options):
        # An existing instructor owns demo content; never invent a credentialed account.
        teacher = User.objects.filter(role__name='instructor').order_by('pk').first()
        if teacher is None:
            teacher = User.objects.filter(is_superuser=True).order_by('pk').first()
        if teacher is None:
            raise CommandError('No instructor or superuser exists. Create an authorized owner before seeding courses; no accounts were created.')
        import_module('core.migrations.0044_seed_course_categories').seed_categories(apps, type('Schema', (), {'connection': connection})())
        courses = []
        academic = [
            (6, 'Mathematics', 'Fractions in Everyday Life'),
            (7, 'Science', 'Explore Forces and Motion'),
            (8, 'Mathematics', 'Algebra Foundations'),
            (9, 'Science', 'Matter and Chemical Reactions'),
            (10, 'Mathematics', 'Geometry and Trigonometry'),
            (10, 'English', 'Reading and Writing with Confidence'),
        ]
        for number, subject_name, title in academic:
            grade, _ = Grade.objects.get_or_create(name=f'Grade {number}')
            subject, _ = Subject.objects.get_or_create(name=subject_name)
            course, _ = Course.objects.get_or_create(title=f'Grade {number}: {title}', instructor=teacher,
                defaults={'course_type': 'academic', 'subject': subject, 'grade': grade,
                    'description': f'Build Grade {number} {subject_name.lower()} skills through guided examples, practice and real-world applications.',
                    'is_published': True})
            courses.append(course)
        for category, title in [('Coding', 'Python: Build Your First Project'), ('Drawing', 'Drawing from Observation'),
                                ('Public Speaking', 'Speak with Confidence'), ('Music', 'Rhythm and Melody Foundations')]:
            interest = LearningInterest.objects.filter(name__iexact=category).first()
            if interest is None:
                interest, _ = LearningInterest.objects.get_or_create(slug=category.lower().replace(' ', '-'), defaults={'name': category})
            paid = category == 'Coding'
            course, _ = Course.objects.get_or_create(title=title, instructor=teacher, defaults={
                'course_type': 'skill', 'skill_category': interest, 'description': f'Learn {category.lower()} with practical activities and a final creative project.',
                'is_published': True, 'is_paid': paid, 'price': Decimal('1299.00') if paid else None})
            courses.append(course)
        for title, published in [('Creative Practice: Coming Soon', True), ('Draft: Advanced Creative Workshop', False)]:
            Course.objects.get_or_create(title=title, instructor=teacher, defaults={'course_type': 'skill',
                'description': 'A forthcoming workshop for curious learners.', 'is_published': published})
        for course in courses:
            Course.objects.filter(pk=course.pk, learning_outcomes=[]).update(learning_outcomes=[
                f'Explain the key ideas in {course.title}.', 'Apply the concepts in a guided practical activity.',
                'Check your understanding and reflect on your progress.'])
            Course.objects.filter(pk=course.pk, requirements=[]).update(requirements=[
                'A notebook and a willingness to practice.',
                f'Familiarity with the preceding grade curriculum.' if course.course_type == 'academic' else 'No prior experience required.'])
            for index in range(1, 10):
                section = ['Foundations', 'Guided Practice', 'Apply Your Skills'][(index - 1) // 3]
                kind = ['video', 'pdf', 'text'][(index - 1) % 3]
                Lesson.objects.get_or_create(course=course, title=f'{section}: Activity {(index - 1) % 3 + 1}', defaults={
                    'section': section, 'order': index, 'content_type': kind, 'duration_seconds': 180 + index * 45,
                    'is_preview': index == 1, 'content_text': f'Practice {course.title}. Work through the example, explain your reasoning, and try a similar problem.' if kind == 'text' else '',
                    'content_url': '' if kind == 'text' else ('https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf' if kind == 'pdf' else 'https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4')})
        checks = [
            ('What is one half plus one quarter?', 'Three quarters', 'One sixth'),
            ('What can change the speed of an object?', 'A force', 'Its colour'),
            ('If x + 3 = 7, what is x?', '4', '10'),
            ('Which observation can indicate a chemical reaction?', 'A new substance forms', 'Only the container changes'),
            ('In a right triangle, which side is opposite the right angle?', 'The hypotenuse', 'The shortest side'),
            ('What makes a paragraph easier to follow?', 'A clear main idea with supporting details', 'Unrelated sentences'),
            ('Which Python keyword defines a function?', 'def', 'function'),
            ('What helps you draw proportions accurately?', 'Comparing relative lengths', 'Ignoring the subject'),
            ('What helps an audience follow your speech?', 'A clear structure and purposeful pauses', 'Speaking as fast as possible'),
            ('What does a steady beat provide?', 'A regular pulse for the music', 'The words of the song'),
        ]
        for course, (prompt, correct, distractor) in zip(courses, checks):
            quiz, _ = Quiz.objects.get_or_create(course=course, title=f'{course.title}: Knowledge Check', defaults={
                'description': 'Review a core concept before continuing your practice.', 'max_attempts': 3,
                'pass_percentage': 60, 'is_published': True})
            question, _ = Question.objects.get_or_create(quiz=quiz, text=prompt, defaults={'marks': 1, 'order': 1})
            QuestionOption.objects.get_or_create(question=question, text=correct, defaults={'is_correct': True})
            QuestionOption.objects.get_or_create(question=question, text=distractor, defaults={'is_correct': False})
        # Reviews use existing students only. No passwords, invented payments or verified access.
        reviewers = list(User.objects.filter(role__name='student').order_by('pk')[:5])
        for index, student in enumerate(reviewers, 1):
            CourseReview.objects.get_or_create(course=courses[6], student=student,
                defaults={'rating': index, 'review': ['Needs more examples.', 'Helpful introduction.', 'Good guided practice.', 'Clear and engaging.', 'Excellent project-based learning!'][index - 1]})
        if len(reviewers) < 5:
            self.stdout.write(f'Skipped {5 - len(reviewers)} review fixtures: fewer than five existing students.')
        student = User.objects.filter(email__iexact='student@skillsikka.com', role__name='student').first()
        fixture_enrollments = fixture_progress = 0
        if student:
            for course, status, limit in [(courses[7], 'completed', 9), (courses[8], 'active', 3), (courses[6], 'pending_payment', 0)]:
                enrollment, created = Enrollment.objects.get_or_create(student=student, course=course,
                    defaults={'status': status, 'completed_at': timezone.now() if status == 'completed' else None})
                fixture_enrollments += int(created)
                if enrollment.status in ['active', 'completed']:
                    for lesson in course.lessons.order_by('order')[:limit]:
                        _, created = LessonProgress.objects.get_or_create(student=student, lesson=lesson,
                            defaults={'enrollment': enrollment, 'is_completed': True, 'completed_at': timezone.now()})
                        fixture_progress += int(created)
        else:
            self.stdout.write('Skipped demo enrollment/progress: student@skillsikka.com does not exist as a student.')
        self.stdout.write(f'Catalogue totals: courses={Course.objects.count()}, subjects={Subject.objects.count()}, lessons={Lesson.objects.count()}, learning_interests={LearningInterest.objects.count()}, reviews={CourseReview.objects.count()}, enrollments={Enrollment.objects.count()}, progress={LessonProgress.objects.count()}.')
        self.stdout.write(f'Created demo enrollments={fixture_enrollments}, progress={fixture_progress}. No payment records created; pending_payment grants no access.')
        self.stdout.write(f'Assessment totals: quizzes={Quiz.objects.count()}, questions={Question.objects.count()}, options={QuestionOption.objects.count()}.')
