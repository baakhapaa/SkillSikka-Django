from django.contrib import admin

from .models import Permission, Role, RolePermission, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
	list_display = ('email', 'name', 'role', 'verification_status', 'is_active', 'created_at')
	list_filter = ('role', 'verification_status', 'is_active')
	search_fields = ('email', 'name')


admin.site.register(Role)
admin.site.register(Permission)
admin.site.register(RolePermission)
