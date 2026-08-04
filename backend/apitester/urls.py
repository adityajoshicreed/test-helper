from django.urls import path

from . import views

urlpatterns = [
    path('import-curl/', views.ImportCurlView.as_view(), name='import-curl'),
    path('imported-requests/', views.ImportedRequestListView.as_view(), name='imported-request-list'),
    path('imported-requests/<int:pk>/', views.ImportedRequestDetailView.as_view(), name='imported-request-detail'),
    path('imported-requests/<int:pk>/test-runs/', views.CreateTestRunView.as_view(), name='create-test-run'),
    path('test-runs/', views.TestRunListView.as_view(), name='test-run-list'),
    path('test-runs/<int:pk>/', views.TestRunDetailView.as_view(), name='test-run-detail'),
    path('test-runs/<int:pk>/stop/', views.StopTestRunView.as_view(), name='stop-test-run'),
]
