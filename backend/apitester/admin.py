from django.contrib import admin

from .models import ImportedRequest, TestCase, TestRun

admin.site.register(ImportedRequest)
admin.site.register(TestRun)
admin.site.register(TestCase)
