from django.urls import path

from . import views

urlpatterns = [
    path('chains/', views.ApiChainListCreateView.as_view(), name='chain-list-create'),
    path('chains/<int:pk>/', views.ApiChainDetailView.as_view(), name='chain-detail'),
    path('chains/<int:pk>/steps/', views.ChainStepCreateView.as_view(), name='chain-step-create'),
    path('chains/<int:pk>/runs/', views.CreateChainRunView.as_view(), name='chain-run-create'),
    path('runs/', views.ChainRunListView.as_view(), name='chain-run-list'),
    path('runs/<int:pk>/', views.ChainRunDetailView.as_view(), name='chain-run-detail'),
]
