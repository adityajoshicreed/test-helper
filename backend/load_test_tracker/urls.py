from django.urls import path

from . import views

urlpatterns = [
    path('plans/', views.LoadTestPlanListCreateView.as_view()),
    path('plans/<int:pk>/', views.LoadTestPlanDetailView.as_view()),
    path('plans/<int:pk>/tests/', views.PlannedLoadTestCreateView.as_view()),
    path('tests/<int:pk>/record/', views.RecordLoadTestResultView.as_view()),
]
