from typing import List

from pydantic import BaseModel, Field


class PracticeQuestion(BaseModel):

    question: str = Field(
        description='The educational practice question.'
    )

    options: List[str] = Field(
        description='Four possible answer options.'
    )

    correct_answer: str = Field(
        description='The correct answer.'
    )

    explanation: str = Field(
        description='Short explanation of why the answer is correct.'
    )


class PracticeQuestionsActivity(BaseModel):

    activity_type: str = Field(
        description='Must be practice_questions.'
    )

    title: str

    instructions: str

    questions: List[PracticeQuestion]


class CrosswordClue(BaseModel):

    answer: str = Field(
        description='Single word answer for the crossword.'
    )

    clue: str = Field(
        description='Educational clue for the answer.'
    )


class CrosswordActivity(BaseModel):

    activity_type: str = Field(
        description='Must be crossword.'
    )

    title: str

    instructions: str

    clues: List[CrosswordClue]


class ChallengeActivity(BaseModel):

    activity_type: str = Field(
        description='Must be challenge.'
    )

    title: str

    description: str

    instructions: List[str]

    expected_outcome: str

    difficulty: str


# ==========================================
# FR-AI-05 Recommendation Schemas
# ==========================================


class RecommendedCourse(BaseModel):

    id: int = Field(
        description='ID of the recommended course.'
    )

    reason: str = Field(
        description='Short educational reason for recommending the course.'
    )


class RecommendedLesson(BaseModel):

    id: int = Field(
        description='ID of the recommended lesson.'
    )

    reason: str = Field(
        description='Short educational reason for recommending the lesson.'
    )


class RecommendedVideo(BaseModel):

    id: int = Field(
        description='ID of the recommended educational Short/video.'
    )

    reason: str = Field(
        description='Short educational reason for recommending the video.'
    )


class LearningRecommendations(BaseModel):

    courses: List[RecommendedCourse] = Field(
        description='Recommended courses selected only from the supplied courses.'
    )

    lessons: List[RecommendedLesson] = Field(
        description='Recommended lessons selected only from the supplied lessons.'
    )

    videos: List[RecommendedVideo] = Field(
        description='Recommended videos selected only from the supplied videos.'
    )