from django.contrib import admin

from .models import ManualTestCase, ManualTestStep, ManualTestSuite

admin.site.register(ManualTestSuite)
admin.site.register(ManualTestCase)
admin.site.register(ManualTestStep)
