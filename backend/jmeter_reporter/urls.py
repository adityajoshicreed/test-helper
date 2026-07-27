from django.urls import path

from . import views

urlpatterns = [
    path('jobs/', views.JmeterReportJobListCreateView.as_view(), name='jmeter-job-list-create'),
    path('jobs/<int:pk>/', views.JmeterReportJobDetailView.as_view(), name='jmeter-job-detail'),
    path('jobs/<int:pk>/report/', views.JmeterReportFileView.as_view(), name='jmeter-job-report-index'),
    path('jobs/<int:pk>/report/<path:subpath>', views.JmeterReportFileView.as_view(), name='jmeter-job-report-file'),
]
