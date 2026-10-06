from django.db import transaction
from rest_framework import serializers

from .models import LearningInterest, User
from .student_onboarding import MINIMUM_LEARNING_INTERESTS, update_student_onboarding


class LearningInterestSerializer(serializers.ModelSerializer):
    class Meta:
        model = LearningInterest
        fields = ['id', 'name', 'slug', 'description', 'display_order']


class SelectedLearningInterestSerializer(LearningInterestSerializer):
    class Meta(LearningInterestSerializer.Meta):
        fields = LearningInterestSerializer.Meta.fields + ['is_active']


def selected_interests_payload(user, profile):
    selected = SelectedLearningInterestSerializer(profile.learning_interests.all(), many=True).data
    return {
        'learning_interests': selected,
        'selected_count': len(selected),
        'minimum_required': MINIMUM_LEARNING_INTERESTS,
        'interests_completed': len(selected) >= MINIMUM_LEARNING_INTERESTS,
        'profile_completed': profile.profile_completed,
        'onboarding_completed': user.onboarding_completed,
        'onboarding_step': user.onboarding_step,
        'onboarding_flow_version': profile.onboarding_flow_version,
    }


class StudentLearningInterestsSerializer(serializers.Serializer):
    interest_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=MINIMUM_LEARNING_INTERESTS,
    )

    def validate(self, attrs):
        unexpected = set(self.initial_data) - {'interest_ids'}
        if unexpected:
            raise serializers.ValidationError({name: ['This field is not allowed.'] for name in sorted(unexpected)})
        ids = attrs['interest_ids']
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError({'interest_ids': ['Interest IDs must be distinct.']})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        # Profile completion takes the same lock to avoid conflicting stage updates.
        user = User.objects.select_for_update().get(pk=self.context['request'].user.pk)
        profile = user.student_profile
        ids = validated_data['interest_ids']
        interests = list(LearningInterest.objects.select_for_update().filter(pk__in=ids))
        if len(interests) != len(ids):
            raise serializers.ValidationError({'interest_ids': ['One or more interest IDs do not exist.']})
        existing_ids = set(profile.learning_interests.values_list('id', flat=True))
        if any(not interest.is_active and interest.pk not in existing_ids for interest in interests):
            raise serializers.ValidationError({'interest_ids': ['Inactive interests cannot be newly selected.']})
        profile.learning_interests.set(interests)
        update_student_onboarding(user, profile)
        user.save(update_fields=['onboarding_completed', 'onboarding_step', 'updated_at'])
        self.context['request'].user.refresh_from_db()
        return user
