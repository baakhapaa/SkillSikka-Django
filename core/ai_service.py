import json
import time

from django.conf import settings
from google import genai
from google.genai import types
from google.genai.errors import ServerError

from .ai_schemas import (
    ChallengeActivity,
    CrosswordActivity,
    LearningRecommendations,
    PracticeQuestionsActivity,
)


class GeminiService:
    """
    Service for communicating with the Gemini API.

    Supports:
    - FR-AI-01: Student AI questions
    - FR-AI-02: Explanation, hints and guided assistance
    - FR-AI-03: AI-assisted educational activity generation
    - FR-AI-05: Course, lesson and educational video recommendations
    """

    MODEL_NAME = 'gemini-3.6-flash'

    # =========================
    # FR-AI-02 Assistance Modes
    # =========================

    ASSISTANCE_EXPLAIN = 'explain'
    ASSISTANCE_HINT = 'hint'
    ASSISTANCE_GUIDE = 'guide'

    ASSISTANCE_MODES = {
        ASSISTANCE_EXPLAIN,
        ASSISTANCE_HINT,
        ASSISTANCE_GUIDE,
    }

    # =========================
    # FR-AI-03 Activity Types
    # =========================

    ACTIVITY_PRACTICE_QUESTIONS = 'practice_questions'
    ACTIVITY_CROSSWORD = 'crossword'
    ACTIVITY_CHALLENGE = 'challenge'

    ACTIVITY_TYPES = {
        ACTIVITY_PRACTICE_QUESTIONS,
        ACTIVITY_CROSSWORD,
        ACTIVITY_CHALLENGE,
    }

    ACTIVITY_SCHEMAS = {
        ACTIVITY_PRACTICE_QUESTIONS: PracticeQuestionsActivity,
        ACTIVITY_CROSSWORD: CrosswordActivity,
        ACTIVITY_CHALLENGE: ChallengeActivity,
    }

    @classmethod
    def _get_client(cls):
        """
        Create and return the Gemini client.
        """

        api_key = settings.GEMINI_API_KEY

        if not api_key:
            raise ValueError(
                'Gemini API key is not configured.'
            )

        return genai.Client(
            api_key=api_key
        )

    @classmethod
    def _generate_response(cls, prompt):
        """
        Generate a normal text response from Gemini.

        Temporary Gemini server errors are retried
        automatically.
        """

        client = cls._get_client()

        max_attempts = 3

        for attempt in range(max_attempts):
            try:
                response = client.models.generate_content(
                    model=cls.MODEL_NAME,
                    contents=prompt
                )

                answer = getattr(
                    response,
                    'text',
                    None
                )

                if not answer:
                    raise RuntimeError(
                        'The AI assistant did not return a response.'
                    )

                return answer.strip()

            except ServerError:
                if attempt == max_attempts - 1:
                    raise

                time.sleep(2 ** attempt)

        raise RuntimeError(
            'The AI assistant did not return a response.'
        )

    @classmethod
    def _generate_structured_response(
        cls,
        prompt,
        response_schema
    ):
        """
        Generate structured JSON from Gemini using
        the supplied Pydantic response schema.
        """

        client = cls._get_client()

        max_attempts = 3

        for attempt in range(max_attempts):
            try:
                response = client.models.generate_content(
                    model=cls.MODEL_NAME,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type='application/json',
                        response_schema=response_schema,
                    ),
                )

                parsed = getattr(
                    response,
                    'parsed',
                    None
                )

                if parsed is not None:
                    if hasattr(parsed, 'model_dump'):
                        return parsed.model_dump()

                    if isinstance(parsed, dict):
                        return parsed

                response_text = getattr(
                    response,
                    'text',
                    None
                )

                if not response_text:
                    raise RuntimeError(
                        'The AI assistant did not return '
                        'structured data.'
                    )

                return json.loads(response_text)

            except ServerError:
                if attempt == max_attempts - 1:
                    raise

                time.sleep(2 ** attempt)

        raise RuntimeError(
            'The AI assistant did not return structured data.'
        )

    # =========================
    # FR-AI-01
    # =========================

    @classmethod
    def ask_student_question(
        cls,
        question,
        learning_context=None
    ):
        """
        Allow students to ask the AI assistant questions.
        """

        question = (question or '').strip()

        if not question:
            raise ValueError(
                'Question is required.'
            )

        prompt_parts = [
            (
                'You are SkillSikka AI, an educational learning '
                'assistant for students.'
            ),
            (
                'Your purpose is to help students understand '
                'educational concepts clearly and accurately.'
            ),
            (
                'Use simple, age-appropriate language. '
                'Do not pretend to know information that you '
                'are uncertain about.'
            ),
        ]

        if learning_context:
            prompt_parts.extend([
                '',
                'Available learning context:',
                str(learning_context).strip(),
            ])

        prompt_parts.extend([
            '',
            'Student question:',
            question,
            '',
            'Provide a clear and helpful educational response.',
        ])

        prompt = '\n'.join(prompt_parts)

        return cls._generate_response(prompt)

    # =========================
    # FR-AI-02
    # =========================

    @classmethod
    def get_guided_assistance(
        cls,
        question,
        assistance_mode,
        learning_context=None
    ):
        """
        Provide explanations, hints, or guided assistance.
        """

        question = (question or '').strip()

        assistance_mode = (
            assistance_mode or ''
        ).strip().lower()

        if not question:
            raise ValueError(
                'Question is required.'
            )

        if assistance_mode not in cls.ASSISTANCE_MODES:
            raise ValueError(
                'Invalid assistance mode. '
                'Use explain, hint, or guide.'
            )

        prompt_parts = [
            (
                'You are SkillSikka AI, an educational learning '
                'assistant for students.'
            ),
            (
                'Your goal is to help the student learn and '
                'understand rather than simply complete work '
                'for them.'
            ),
            (
                'Use clear, simple, age-appropriate language.'
            ),
        ]

        if learning_context:
            prompt_parts.extend([
                '',
                'Available learning context:',
                str(learning_context).strip(),
                '',
                (
                    'Use the learning context when it is relevant '
                    'to the student question.'
                ),
            ])

        prompt_parts.extend([
            '',
            'Student question:',
            question,
            '',
        ])

        if assistance_mode == cls.ASSISTANCE_EXPLAIN:
            prompt_parts.extend([
                'Assistance mode: EXPLANATION',
                (
                    'Explain the concept clearly in a way that '
                    'helps the student understand it.'
                ),
                (
                    'Break difficult ideas into simpler parts '
                    'and use an example when useful.'
                ),
            ])

        elif assistance_mode == cls.ASSISTANCE_HINT:
            prompt_parts.extend([
                'Assistance mode: HINT',
                (
                    'Give the student a useful hint that moves '
                    'them toward the solution.'
                ),
                (
                    'Do not immediately provide the complete '
                    'final answer when the student can reasonably '
                    'work it out themselves.'
                ),
                (
                    'Encourage the student to think about '
                    'the next step.'
                ),
            ])

        elif assistance_mode == cls.ASSISTANCE_GUIDE:
            prompt_parts.extend([
                'Assistance mode: GUIDED ASSISTANCE',
                (
                    'Guide the student through the problem or '
                    'concept step by step.'
                ),
                (
                    'Explain the reasoning behind each important '
                    'step instead of only giving a final answer.'
                ),
                (
                    'Keep the guidance focused and educational.'
                ),
            ])

        prompt = '\n'.join(prompt_parts)

        return cls._generate_response(prompt)

    # =========================
    # FR-AI-03
    # =========================

    @classmethod
    def generate_educational_activity(
        cls,
        activity_type,
        topic,
        learning_context=None,
        difficulty='medium',
        question_count=5
    ):
        """
        Generate selected educational activities.

        Supported types:
        - practice_questions
        - crossword
        - challenge
        """

        activity_type = (
            activity_type or ''
        ).strip().lower()

        topic = (
            topic or ''
        ).strip()

        difficulty = (
            difficulty or 'medium'
        ).strip().lower()

        if activity_type not in cls.ACTIVITY_TYPES:
            raise ValueError(
                'Invalid activity type. Use practice_questions, '
                'crossword, or challenge.'
            )

        if not topic:
            raise ValueError(
                'Topic is required.'
            )

        allowed_difficulties = {
            'easy',
            'medium',
            'hard',
        }

        if difficulty not in allowed_difficulties:
            raise ValueError(
                'Difficulty must be easy, medium, or hard.'
            )

        try:
            question_count = int(question_count)
        except (TypeError, ValueError):
            raise ValueError(
                'Question count must be a number.'
            )

        if question_count < 1 or question_count > 10:
            raise ValueError(
                'Question count must be between 1 and 10.'
            )

        prompt_parts = [
            (
                'You are SkillSikka AI, an educational content '
                'generation assistant.'
            ),
            (
                'Generate accurate, student-friendly educational '
                'content suitable for learning purposes.'
            ),
            (
                'The content must be directly related to the '
                'provided topic.'
            ),
            '',
            f'Activity type: {activity_type}',
            f'Topic: {topic}',
            f'Difficulty: {difficulty}',
        ]

        if learning_context:
            prompt_parts.extend([
                '',
                'Available learning context:',
                str(learning_context).strip(),
                (
                    'Use this context to make the activity more '
                    'relevant to the learner.'
                ),
            ])

        if activity_type == cls.ACTIVITY_PRACTICE_QUESTIONS:
            prompt_parts.extend([
                '',
                f'Generate exactly {question_count} practice questions.',
                (
                    'Each question must contain exactly four '
                    'answer options.'
                ),
                (
                    'The correct_answer must exactly match one '
                    'of the provided options.'
                ),
                (
                    'Provide a short educational explanation '
                    'for every correct answer.'
                ),
                (
                    'Set activity_type exactly to '
                    '"practice_questions".'
                ),
            ])

        elif activity_type == cls.ACTIVITY_CROSSWORD:
            prompt_parts.extend([
                '',
                f'Generate exactly {question_count} crossword clues.',
                (
                    'Each answer should preferably be a single '
                    'word related to the topic.'
                ),
                (
                    'Make each clue educational and clear.'
                ),
                (
                    'Set activity_type exactly to "crossword".'
                ),
            ])

        elif activity_type == cls.ACTIVITY_CHALLENGE:
            prompt_parts.extend([
                '',
                (
                    'Generate one educational challenge that '
                    'requires the learner to apply the topic.'
                ),
                (
                    'Provide clear instructions and a meaningful '
                    'expected outcome.'
                ),
                (
                    f'Set the difficulty to "{difficulty}".'
                ),
                (
                    'Set activity_type exactly to "challenge".'
                ),
            ])

        prompt = '\n'.join(prompt_parts)

        response_schema = cls.ACTIVITY_SCHEMAS[
            activity_type
        ]

        return cls._generate_structured_response(
            prompt=prompt,
            response_schema=response_schema
        )

    # =========================
    # FR-AI-05
    # =========================

    @classmethod
    def recommend_learning_content(
        cls,
        learning_goal,
        courses=None,
        lessons=None,
        videos=None,
        learning_context=None
    ):
        """
        Recommend relevant SkillSikka courses, lessons and
        educational videos.

        Gemini is only allowed to recommend content supplied
        by the SkillSikka database.
        """

        learning_goal = (
            learning_goal or ''
        ).strip()

        if not learning_goal:
            raise ValueError(
                'Learning goal is required.'
            )

        courses = courses or []
        lessons = lessons or []
        videos = videos or []

        if not courses and not lessons and not videos:
            return {
                'courses': [],
                'lessons': [],
                'videos': [],
            }

        course_data = []

        for course in courses:
            course_data.append({
                'id': course.id,
                'title': course.title,
                'description': course.description or '',
                'course_type': course.course_type or '',
                'subject': (
                    str(course.subject)
                    if course.subject
                    else ''
                ),
                'grade': (
                    str(course.grade)
                    if course.grade
                    else ''
                ),
            })

        lesson_data = []

        for lesson in lessons:
            lesson_data.append({
                'id': lesson.id,
                'course_id': lesson.course_id,
                'course_title': (
                    lesson.course.title
                    if lesson.course
                    else ''
                ),
                'title': lesson.title,
                'topic': lesson.topic or '',
                'content_type': lesson.content_type or '',
            })

        video_data = []

        for video in videos:
            video_data.append({
                'id': video.id,
                'title': video.title,
            })

        prompt_parts = [
            (
                'You are SkillSikka AI, an educational recommendation '
                'assistant.'
            ),
            (
                'Recommend the most relevant learning content for '
                'the student based on their learning goal and context.'
            ),
            '',
            'IMPORTANT RULES:',
            (
                '1. You may ONLY recommend courses, lessons, and videos '
                'listed in the AVAILABLE SKILLSIKKA CONTENT below.'
            ),
            (
                '2. Never invent a course, lesson, video, or ID.'
            ),
            (
                '3. Every returned ID must exactly match an ID from '
                'the corresponding supplied content list.'
            ),
            (
                '4. If there is no relevant content in a category, '
                'return an empty list for that category.'
            ),
            (
                '5. Recommend only genuinely relevant educational '
                'content.'
            ),
            (
                '6. Give a short, student-friendly reason for every '
                'recommendation.'
            ),
            (
                '7. Return no more than 5 recommendations in each '
                'category.'
            ),
            '',
            f'Student learning goal: {learning_goal}',
        ]

        if learning_context:
            prompt_parts.extend([
                '',
                'Student learning context:',
                str(learning_context).strip(),
            ])

        prompt_parts.extend([
            '',
            'AVAILABLE SKILLSIKKA COURSES:',
            json.dumps(
                course_data,
                ensure_ascii=False
            ),
            '',
            'AVAILABLE SKILLSIKKA LESSONS:',
            json.dumps(
                lesson_data,
                ensure_ascii=False
            ),
            '',
            'AVAILABLE SKILLSIKKA EDUCATIONAL VIDEOS:',
            json.dumps(
                video_data,
                ensure_ascii=False
            ),
            '',
            (
                'Select the best matching content from these lists only.'
            ),
        ])

        prompt = '\n'.join(prompt_parts)

        recommendations = cls._generate_structured_response(
            prompt=prompt,
            response_schema=LearningRecommendations
        )

        # Security/integrity validation:
        # Gemini must never be able to return IDs that were not
        # supplied by our database.

        valid_course_ids = {
            item['id']
            for item in course_data
        }

        valid_lesson_ids = {
            item['id']
            for item in lesson_data
        }

        valid_video_ids = {
            item['id']
            for item in video_data
        }

        recommendations['courses'] = [
            item
            for item in recommendations.get('courses', [])
            if item.get('id') in valid_course_ids
        ][:5]

        recommendations['lessons'] = [
            item
            for item in recommendations.get('lessons', [])
            if item.get('id') in valid_lesson_ids
        ][:5]

        recommendations['videos'] = [
            item
            for item in recommendations.get('videos', [])
            if item.get('id') in valid_video_ids
        ][:5]

        return recommendations