from django.urls import path

from . import views

urlpatterns = [
    path('suites/', views.ManualTestSuiteListCreateView.as_view()),
    path('suites/<int:pk>/', views.ManualTestSuiteDetailView.as_view()),
    path('suites/<int:pk>/cases/', views.ManualTestCaseCreateView.as_view()),
    path('suites/<int:pk>/export/', views.ExportManualTestSuiteExcelView.as_view()),
    path('cases/<int:pk>/steps/', views.ManualTestStepCreateView.as_view()),
]
