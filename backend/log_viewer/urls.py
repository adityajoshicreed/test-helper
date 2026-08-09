from django.urls import path

from . import views

urlpatterns = [
    path('jobs/', views.LogViewJobListCreateView.as_view(), name='log-view-job-list-create'),
    path('jobs/<int:pk>/', views.LogViewJobDetailView.as_view(), name='log-view-job-detail'),
    path('jobs/<int:pk>/entries/', views.LogEntryListView.as_view(), name='log-view-job-entries'),
]
