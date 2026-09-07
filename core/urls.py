from django.urls import path

from .views import dashboard, login_view, logout_view, manage_geography


urlpatterns = [
	path('', dashboard, name='dashboard'),
	path('login', login_view, name='login'),
	path('logout', logout_view, name='logout'),
	path('admin/geography', manage_geography, name='manage_geography'),
]
