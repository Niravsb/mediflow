from django.urls import path
from . import views

urlpatterns = [
    # Auth
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('signup/doctor/', views.signup_doctor, name='signup_doctor'),
    path('signup/patient/', views.signup_patient, name='signup_patient'),

    # Dashboards
    path('', views.dashboard, name='dashboard'),
    path('dashboard/doctor/', views.doctor_dashboard, name='doctor_dashboard'),
    path('dashboard/patient/', views.patient_dashboard, name='patient_dashboard'),

    # Slots
    path('slots/', views.slot_list, name='slot_list'),
    path('slots/create/', views.slot_create, name='slot_create'),
    path('slots/<int:pk>/delete/', views.slot_delete, name='slot_delete'),

    # Booking
    path('book/<int:pk>/', views.book_slot, name='book_slot'),
    path('cancel/<int:pk>/', views.cancel_appointment, name='cancel_appointment'),

    # Google Calendar OAuth
    path('calendar/connect/',    views.google_calendar_connect,    name='google_calendar_connect'),
    path('calendar/callback/',   views.google_calendar_callback,   name='google_calendar_callback'),
    path('calendar/disconnect/', views.google_calendar_disconnect, name='google_calendar_disconnect'),
]