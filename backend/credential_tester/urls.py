from django.urls import path

from . import views

urlpatterns = [
    path('parse-curl/', views.ParseCurlPreviewView.as_view()),
    path('runs/', views.CredentialRunListCreateView.as_view()),
    path('runs/<int:pk>/', views.CredentialRunDetailView.as_view()),
    path('runs/<int:pk>/resume/', views.ResumeCredentialRunView.as_view()),
]
