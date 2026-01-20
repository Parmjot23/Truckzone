# api/urls.py
from django.urls import path, include
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.routers import DefaultRouter
from .views import (
    CustomerViewSet,
    InvoiceViewSet,
    PaymentViewSet,
    NoteViewSet,
)
from .views import (
    mobile_auth_login,
    mobile_auth_logout,
    mobile_jobs,
    mobile_job_detail,
    mobile_job_set_status,
    mobile_job_timer,
    mobile_job_upload_attachment,
    mobile_job_signature,
    mobile_job_add_part,
    mobile_job_remove_part,
    mobile_parts_search,
    mobile_mechanic_summary,
    mobile_activity_history,
    mobile_job_update_details,
    mobile_customer_vehicles_list,
    mobile_customer_vehicle_create,
    mobile_vehicle_overview,
    mobile_vehicle_create_workorder,
    mobile_vehicle_history,
    mobile_pm_inspection_submit,
    mobile_pm_inspection_detail,
)
from .transport_views import (
    TransportProfileViewSet,
    TransportCustomerViewSet,
    TransportVehicleViewSet,
    TransportDriverViewSet,
    TransportTripViewSet,
    TransportInvoiceViewSet,
    EnhancedCustomerViewSet,
    EnhancedInvoiceViewSet
)

# Standard router for basic endpoints
router = DefaultRouter()
router.register(r'customers', CustomerViewSet)
router.register(r'invoices', InvoiceViewSet)
router.register(r'payments', PaymentViewSet)
router.register(r'notes', NoteViewSet)

# Transport-specific endpoints
router.register(r'transport/profile', TransportProfileViewSet, basename='transport-profile')
router.register(r'transport/customers', TransportCustomerViewSet, basename='transport-customers')
router.register(r'transport/vehicles', TransportVehicleViewSet, basename='transport-vehicles')
router.register(r'transport/drivers', TransportDriverViewSet, basename='transport-drivers')
router.register(r'transport/trips', TransportTripViewSet, basename='transport-trips')
router.register(r'transport/invoices', TransportInvoiceViewSet, basename='transport-invoices')

# Enhanced endpoints with transport data
router.register(r'enhanced/customers', EnhancedCustomerViewSet, basename='enhanced-customers')
router.register(r'enhanced/invoices', EnhancedInvoiceViewSet, basename='enhanced-invoices')

urlpatterns = [
    # Built-in DRF token login (optional)
    path('auth/login-token/', obtain_auth_token, name='api_token_auth'),

    # Mobile mechanics app endpoints
    path('auth/login/', mobile_auth_login, name='mobile_auth_login'),
    path('auth/logout/', mobile_auth_logout, name='mobile_auth_logout'),
    path('jobs/', mobile_jobs, name='mobile_jobs'),
    path('jobs/<int:pk>/', mobile_job_detail, name='mobile_job_detail'),
    path('jobs/<int:pk>/status/', mobile_job_set_status, name='mobile_job_set_status'),
    path('jobs/<int:pk>/timer/', mobile_job_timer, name='mobile_job_timer'),
    path('jobs/<int:pk>/attachments/', mobile_job_upload_attachment, name='mobile_job_upload_attachment'),
    path('jobs/<int:pk>/signature/', mobile_job_signature, name='mobile_job_signature'),
    path('jobs/<int:pk>/details/', mobile_job_update_details, name='mobile_job_update_details'),
    path('jobs/<int:pk>/parts/', mobile_job_add_part, name='mobile_job_add_part'),
    path('jobs/<int:pk>/parts/remove/', mobile_job_remove_part, name='mobile_job_remove_part'),
    path('jobs/<int:pk>/pm-inspection/', mobile_pm_inspection_detail, name='mobile_pm_inspection_detail'),
    path('jobs/<int:pk>/pm-inspection/submit/', mobile_pm_inspection_submit, name='mobile_pm_inspection_submit'),
    path('parts/', mobile_parts_search, name='mobile_parts_search'),
    path('mechanic/summary/', mobile_mechanic_summary, name='mobile_mechanic_summary'),
    path('mechanic/activity-history/', mobile_activity_history, name='mobile_activity_history'),
    path('mechanic/vehicles/', mobile_vehicle_overview, name='mobile_vehicle_overview'),
    path('mechanic/vehicles/<int:pk>/create-workorder/', mobile_vehicle_create_workorder, name='mobile_vehicle_create_workorder'),
    path('mechanic/vehicles/<int:vehicle_id>/history/', mobile_vehicle_history, name='mobile_vehicle_history'),
    path('customers/<int:customer_id>/vehicles/', mobile_customer_vehicles_list, name='mobile_customer_vehicles_list'),
    path('customers/<int:customer_id>/vehicles/create/', mobile_customer_vehicle_create, name='mobile_customer_vehicle_create'),

    # Include router URLs
    path('', include(router.urls)),
]
