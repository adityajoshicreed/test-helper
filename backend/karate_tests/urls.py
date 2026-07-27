from django.urls import path

from . import views

urlpatterns = [
    path('jobs/', views.KarateTestCaseJobListCreateView.as_view(), name='karate-job-list-create'),
    path('jobs/<int:pk>/', views.KarateTestCaseJobDetailView.as_view(), name='karate-job-detail'),
]
