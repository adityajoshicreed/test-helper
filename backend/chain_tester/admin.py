from django.contrib import admin

from .models import ApiChain, ChainRun, ChainStep, ChainStepResult, ChainTestCase

admin.site.register(ApiChain)
admin.site.register(ChainStep)
admin.site.register(ChainRun)
admin.site.register(ChainStepResult)
admin.site.register(ChainTestCase)
