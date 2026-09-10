from django.urls import path

from . import views

urlpatterns = [
    path('jobs/', views.KarateAiTestCaseJobListCreateView.as_view(), name='karate-ai-job-list-create'),
    path('jobs/<int:pk>/', views.KarateAiTestCaseJobDetailView.as_view(), name='karate-ai-job-detail'),
]
