from rest_framework import generics
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import LearningInterest
from .learning_interest_serializers import (
    LearningInterestSerializer, StudentLearningInterestsSerializer, selected_interests_payload,
)


class IsStudent(BasePermission):
    message = 'Only students can manage their learning interests.'

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role.name == 'student'


class LearningInterestListAPIView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LearningInterestSerializer
    queryset = LearningInterest.objects.filter(is_active=True).order_by('display_order', 'id')


class MyLearningInterestsAPIView(APIView):
    permission_classes = [IsAuthenticated, IsStudent]
    serializer_class = StudentLearningInterestsSerializer

    def get(self, request):
        return Response(selected_interests_payload(request.user, request.user.student_profile))

    def put(self, request):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(selected_interests_payload(user, user.student_profile))
