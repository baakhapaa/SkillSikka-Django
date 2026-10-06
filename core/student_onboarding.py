"""Student onboarding state; callers save state within a user-row transaction."""
from .models import StudentProfile

MINIMUM_LEARNING_INTERESTS = 3


def update_student_onboarding(user, profile):
    if profile.onboarding_flow_version == StudentProfile.INTERESTS_ONBOARDING:
        interests_completed = profile.learning_interests.count() >= MINIMUM_LEARNING_INTERESTS
        user.onboarding_completed = profile.profile_completed and interests_completed
        # Registration completes step 1; profile data covers steps 2/3.
        # Step 4 remains the final step, with the completed flag distinguishing done.
        user.onboarding_step = 4 if profile.profile_completed else 2
    elif profile.profile_completed:
        # Legacy profile completion never requires interests or changes the step.
        user.onboarding_completed = True
