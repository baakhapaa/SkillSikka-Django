"""Course-specific access rules and stable action errors."""
from rest_framework.exceptions import APIException


class CourseAPIError(APIException):
    def __init__(self, code, detail, status_code=400):
        self.status_code = status_code
        super().__init__({'code': code, 'detail': detail})


def is_course_manager(user, course):
    return user.is_authenticated and (user.is_superuser or user.role.name == 'super_admin' or course.instructor_id == user.pk)


def academic_eligible(user, course):
    if not (user.is_authenticated and user.is_active and user.role.name == 'student' and course.is_published):
        return False
    grade_id = getattr(getattr(user, 'student_profile', None), 'grade_id', None)
    return course.grade_id is None or grade_id == course.grade_id


def require_course_access(user, course, *, managers=True):
    """Return skill enrollment, or None for academic access/management."""
    from .models import Enrollment
    if managers and is_course_manager(user, course):
        return None
    if not course.is_published:
        raise CourseAPIError('COURSE_NOT_PUBLISHED', 'This course is not published.', 403)
    if course.course_type == 'academic':
        if not academic_eligible(user, course):
            raise CourseAPIError('ACADEMIC_NOT_ELIGIBLE', 'This course is not available for your grade.', 403)
        return None
    enrollment = Enrollment.objects.filter(student=user, course=course, status__in=['active', 'completed']).first()
    if enrollment is None:
        raise CourseAPIError('NOT_ENROLLED', 'You must be enrolled in this course to access it.', 403)
    return enrollment
