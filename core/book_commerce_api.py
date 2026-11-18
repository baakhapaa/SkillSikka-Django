"""User-scoped catalogue annotations and book commerce endpoints."""
from django.db import transaction
from django.db.models import Avg, Count, Exists, F, FloatField, IntegerField, OuterRef, Prefetch, Q, Subquery
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import EmailVerifiedJWTAuthentication
from .book_reader import active_book_entitlements, is_book_manager
from .book_reader import book_has_usable_content
from .course_pagination import CoursePagination
from .models import BookChapter, BookChapterCompletion, BookEntitlement, BookOrder, BookReadingProgress, BookReview, EBook, SavedBook


class CatalogueFilters(serializers.Serializer):
    search = serializers.CharField(required=False, allow_blank=True, max_length=200)
    category = serializers.CharField(required=False, max_length=100)
    subject = serializers.IntegerField(required=False, min_value=1, max_value=9223372036854775807)
    grade = serializers.IntegerField(required=False, min_value=1, max_value=9223372036854775807)
    difficulty = serializers.ChoiceField(choices=['beginner', 'intermediate', 'advanced'], required=False)
    pricing = serializers.ChoiceField(choices=['free', 'paid'], required=False)
    min_rating = serializers.DecimalField(max_digits=3, decimal_places=2, min_value=1, max_value=5, required=False)
    min_price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, required=False)
    max_price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, required=False)
    ordering = serializers.ChoiceField(choices=['latest', 'popular', 'highest_rated'], default='latest')


def catalogue_filter(queryset, params):
    filters = CatalogueFilters(data=params)
    filters.is_valid(raise_exception=True)
    values = filters.validated_data
    for field, lookup in {
        'category': 'category__iexact', 'subject': 'subject_id', 'grade': 'grade_id',
        'difficulty': 'difficulty', 'min_rating': 'average_rating__gte',
        'min_price': 'price__gte', 'max_price': 'price__lte',
    }.items():
        if field in values:
            queryset = queryset.filter(**{lookup: values[field]})
    if values.get('min_price', 0) > values.get('max_price', float('inf')):
        raise ValidationError({'max_price': 'Must be at least min_price.'})
    if values.get('search'):
        query = values['search']
        queryset = queryset.filter(Q(title__icontains=query) | Q(author__icontains=query))
    if values.get('pricing') == 'free':
        queryset = queryset.filter(price=0)
    elif values.get('pricing') == 'paid':
        queryset = queryset.filter(price__gt=0)
    ordering = {'latest': (), 'popular': ('-purchase_count', '-review_count'),
                'highest_rated': ('-average_rating', '-review_count')}
    return queryset.order_by(*ordering[values['ordering']], '-created_at', '-pk')


def book_summary(queryset, user, *, with_review=False):
    reviews = BookReview.objects.filter(book_id=OuterRef('pk'), is_hidden=False).order_by().values('book_id')
    purchases = BookOrder.objects.filter(book_id=OuterRef('pk'), status='paid', paid_at__isnull=False).order_by().values('book_id')
    usable_chapters = BookChapter.objects.filter(book_id=OuterRef('pk'), content__regex=r'\S')
    chapters = BookReadingProgress.objects.filter(user=user).prefetch_related(Prefetch(
        'completions', queryset=BookChapterCompletion.objects.select_related('chapter').order_by('chapter__chapter_number'),
    ))
    queryset = queryset.select_related('subject', 'grade', 'uploaded_by').annotate(
        is_saved=Exists(SavedBook.objects.filter(user=user, book_id=OuterRef('pk'))),
        has_entitlement=Exists(active_book_entitlements(user).filter(book_id=OuterRef('pk'))),
        has_acquisition=Exists(BookEntitlement.objects.filter(user=user, book_id=OuterRef('pk'))),
        is_purchased=Exists(active_book_entitlements(user).filter(book_id=OuterRef('pk'), source='purchase')),
        average_rating=Coalesce(Subquery(reviews.annotate(value=Avg('rating')).values('value'), output_field=FloatField()), 0.0),
        review_count=Coalesce(Subquery(reviews.annotate(value=Count('pk')).values('value'), output_field=IntegerField()), 0),
        purchase_count=Coalesce(Subquery(purchases.annotate(value=Count('pk')).values('value'), output_field=IntegerField()), 0),
        chapter_total=Count('chapters', distinct=True),
        has_usable_chapters=Exists(usable_chapters),
    ).prefetch_related(Prefetch('reading_progress', queryset=chapters, to_attr='viewer_progress'))
    if with_review:
        queryset = queryset.prefetch_related(Prefetch('reviews', queryset=BookReview.objects.filter(user=user), to_attr='viewer_review'))
    return queryset


def book_progress(book):
    progress = next(iter(book.viewer_progress), None)
    completed = [row.chapter_id for row in progress.completions.all() if row.chapter.book_id == book.pk] if progress else []
    return {
        'last_chapter_id': progress.last_chapter_id if progress else None,
        'position': progress.position if progress else {},
        'completed_chapter_ids': completed,
        'total_chapters': book.chapter_total,
        'completed_chapters': len(completed),
        'overall_percentage': round(100 * len(completed) / book.chapter_total, 2) if book.chapter_total else 0,
        'last_read_at': progress.last_read_at.isoformat() if progress else None,
    }


def book_available(book):
    return book_has_usable_content(
        book, has_usable_chapters=getattr(book, 'has_usable_chapters', None),
    )


def commerce_metadata(book, user):
    access = is_book_manager(user, book) or book.has_entitlement
    if access:
        progress = book_progress(book)
        if book_available(book):
            action = 'continue_reading' if progress['last_read_at'] and progress['overall_percentage'] < 100 else 'read_now'
        else:
            action = 'unavailable'
    elif book.is_published and book.price == 0 and not book.has_acquisition:
        progress = None
        action = 'get_free' if book_available(book) else 'unavailable'
    else:
        progress = None
        action = 'unavailable'
    data = {
        'average_rating': round(book.average_rating, 2), 'review_count': book.review_count,
        'is_saved': book.is_saved, 'is_purchased': book.is_purchased,
        'has_reading_access': access, 'reading_progress': progress,
        'can_purchase': False, 'can_review': book.has_entitlement, 'available_action': action,
    }
    if hasattr(book, 'viewer_review'):
        review = next(iter(book.viewer_review), None)
        data['current_user_review'] = BookReviewSerializer(review).data if review else None
    return data


class BookReviewSerializer(serializers.ModelSerializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)

    class Meta:
        model = BookReview
        fields = ['id', 'rating', 'review', 'is_hidden', 'created_at', 'updated_at']
        read_only_fields = ['id', 'is_hidden', 'created_at', 'updated_at']


class BookOrderSerializer(serializers.ModelSerializer):
    book = serializers.IntegerField(source='book_id')
    book_title = serializers.CharField(source='book.title')

    class Meta:
        model = BookOrder
        fields = ['id', 'reference', 'book', 'book_title', 'original_price', 'amount', 'currency', 'status', 'created_at', 'paid_at']


class PrivateBookAPI:
    authentication_classes = [EmailVerifiedJWTAuthentication]
    permission_classes = [IsAuthenticated]
    pagination_class = CoursePagination

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'private, no-store'
        return response


class SaveBookView(PrivateBookAPI, APIView):
    def post(self, request, book_id):
        book = get_object_or_404(EBook, pk=book_id, is_published=True)
        SavedBook.objects.get_or_create(user=request.user, book=book)
        return Response({'is_saved': True})

    def delete(self, request, book_id):
        SavedBook.objects.filter(user=request.user, book_id=book_id).delete()
        return Response(status=204)


class BookCollectionView(PrivateBookAPI, generics.ListAPIView):
    def get_serializer_class(self):
        from .serializers import EBookSerializer
        return EBookSerializer


class SavedBooksView(BookCollectionView):
    def get_queryset(self):
        user = self.request.user
        return book_summary(EBook.objects.filter(is_published=True, saves__user=user), user).order_by(
            '-saves__created_at', '-pk',
        )


class BookReviewsView(PrivateBookAPI, generics.ListCreateAPIView):
    serializer_class = BookReviewSerializer

    def get_queryset(self):
        book = get_object_or_404(EBook, pk=self.kwargs['book_id'], is_published=True)
        return book.reviews.filter(is_hidden=False).order_by('-created_at', '-pk')

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        book = get_object_or_404(EBook.objects.select_for_update(), pk=self.kwargs['book_id'], is_published=True)
        if not active_book_entitlements(request.user).filter(book=book).exists():
            raise PermissionDenied('Acquire this book before reviewing it.')
        if book.reviews.filter(user=request.user).exists():
            return Response({'detail': 'You already reviewed this book.'}, status=409)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(user=request.user, book=book)
        return Response(serializer.data, status=201)


class BookReviewDetailView(PrivateBookAPI, generics.GenericAPIView):
    serializer_class = BookReviewSerializer
    lookup_url_kwarg = 'review_id'

    def get_queryset(self):
        return BookReview.objects.filter(book_id=self.kwargs['book_id'], user=self.request.user)

    @transaction.atomic
    def patch(self, request, *args, **kwargs):
        book = get_object_or_404(EBook.objects.select_for_update(), pk=kwargs['book_id'], is_published=True)
        review = get_object_or_404(self.get_queryset().select_for_update(), pk=kwargs['review_id'])
        if not active_book_entitlements(request.user).filter(book=book).exists():
            raise PermissionDenied('Active access is required to edit a review.')
        serializer = self.get_serializer(review, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, *args, **kwargs):
        self.get_object().delete()
        return Response(status=204)


class BuyBookView(PrivateBookAPI, APIView):
    def post(self, request, book_id):
        book = get_object_or_404(EBook, pk=book_id, is_published=True)
        if book.price is None or book.price <= 0 or not book_available(book):
            return Response({'code': 'BOOK_UNAVAILABLE', 'detail': 'This book is unavailable for paid checkout.'}, status=409)
        return Response({'code': 'BOOK_CHECKOUT_DISABLED', 'detail': 'Paid book checkout is currently disabled.'}, status=503)


class GetFreeBookView(PrivateBookAPI, APIView):
    @transaction.atomic
    def post(self, request, book_id):
        book = get_object_or_404(EBook.objects.select_for_update(), pk=book_id, is_published=True)
        if book.price != 0 or not book_has_usable_content(book):
            return Response({'code': 'BOOK_UNAVAILABLE', 'detail': 'This book is unavailable for free acquisition.'}, status=409)
        entitlement, created = BookEntitlement.objects.get_or_create(
            user=request.user, book=book, source=BookEntitlement.Source.FREE,
        )
        if not created and not active_book_entitlements(request.user).filter(pk=entitlement.pk).exists():
            return Response({'code': 'BOOK_ACCESS_REVOKED', 'detail': 'Access to this book has been revoked.'}, status=409)
        return Response({'book': book.pk, 'source': entitlement.source, 'granted_at': entitlement.granted_at,
                         'has_reading_access': True}, status=201 if created else 200)


class MyBooksView(BookCollectionView):
    def get_queryset(self):
        user = self.request.user
        queryset = book_summary(EBook.objects.filter(pk__in=active_book_entitlements(user).values('book_id')), user)
        progress = BookReadingProgress.objects.filter(user=user, book_id=OuterRef('pk'))
        completed = BookChapterCompletion.objects.filter(
            progress__user=user, progress__book_id=OuterRef('pk'), chapter__book_id=OuterRef('pk'),
        ).order_by().values('progress__book_id').annotate(value=Count('pk')).values('value')
        queryset = queryset.annotate(
            acquired_at=Subquery(active_book_entitlements(user).filter(book_id=OuterRef('pk')).order_by('granted_at', 'pk').values('granted_at')),
            started=Exists(progress),
            completion_total=Coalesce(Subquery(completed, output_field=IntegerField()), 0),
        )
        complete = Q(chapter_total__gt=0, completion_total=F('chapter_total'))
        status = self.request.query_params.get('status', 'all')
        if status == 'completed':
            queryset = queryset.filter(complete)
        elif status == 'in_progress':
            queryset = queryset.filter(started=True).exclude(complete)
        elif status == 'not_started':
            queryset = queryset.filter(started=False)
        elif status != 'all':
            raise ValidationError({'status': 'Choose all, completed, in_progress, or not_started.'})
        return queryset.order_by('-acquired_at', '-pk')


class BookOrderQuery(PrivateBookAPI):
    serializer_class = BookOrderSerializer

    def get_queryset(self):
        return BookOrder.objects.filter(user=self.request.user).select_related('book').order_by('-created_at', '-pk')


class BookOrdersView(BookOrderQuery, generics.ListAPIView):
    pass


class BookOrderDetailView(BookOrderQuery, generics.RetrieveAPIView):
    pass
