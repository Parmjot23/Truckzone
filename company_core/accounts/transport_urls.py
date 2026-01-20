# accounts/transport_urls.py
from django.urls import path
from . import transport_views

app_name = 'transport'

urlpatterns = [
    path('dashboard/', transport_views.transport_dashboard, name='dashboard'),
    path('setup/', transport_views.transport_setup, name='setup'),
    path('trips/', transport_views.transport_trips, name='trips'),
    path('vehicles/', transport_views.transport_vehicles, name='vehicles'),
    path('drivers/', transport_views.transport_drivers, name='drivers'),
    path('invoices/', transport_views.transport_invoices, name='invoices'),
    path('create-invoice/', transport_views.create_invoice_from_trips, name='create_invoice'),
]