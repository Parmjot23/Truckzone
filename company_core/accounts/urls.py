from django.urls import path, include
from . import views, invoice_utils
from django.views.generic.base import RedirectView
from django.contrib.auth.views import LogoutView
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy
from .legal_views import privacy_policy_view, terms_and_conditions_view, cookies_policy_view
from . import (
    signup_process,
    receipt_views,
    view_public_home,
    view_invoices,
    paid_invoice_views,
    view_payments,
    store_views,
    supplier_views,
    public_ai,
    customer_ai,
    clover_views,
)
from . import payroll_views
from . import forms as public_forms

from . import noteview
from . import viewapi
from .views_inventory import (
    inventory_view,
    inventory_hub,
    inventory_transactions_view,
    inventory_products_view,
    inventory_stock_orders_view,
    inventory_suppliers_view,
    inventory_categories_view,
    inventory_category_groups_view,
    inventory_attributes_view,
    inventory_brands_view,
    inventory_models_view,
    inventory_vins_view,
    inventory_locations_view,
    add_transaction,
    edit_transaction,
    delete_transaction,
    get_transaction_form,
    add_supplier,
    edit_supplier,
    delete_supplier,
    bulk_delete_suppliers,
    save_supplier_inline,
    delete_inventory_supplier,
    add_product,
    save_product_inline,
    update_inventory_margin,
    apply_margin_to_products,
    edit_product,
    update_product_attributes,
    delete_product,
    delete_inventory_product,
    bulk_delete_products,
    bulk_update_products,
    export_products_template,
    export_suppliers_template,
    export_categories_template,
    export_category_groups_template,
    export_brands_template,
    export_models_template,
    export_vins_template,
    export_locations_template,
    import_products_from_excel,
    import_suppliers_from_excel,
    import_categories_from_excel,
    import_category_groups_from_excel,
    import_brands_from_excel,
    import_models_from_excel,
    import_vins_from_excel,
    import_locations_from_excel,
    add_category,
    edit_category,
    delete_category,
    bulk_delete_categories,
    save_category_inline,
    delete_inventory_category,
    save_category_group_inline,
    delete_category_group,
    save_attribute_inline,
    delete_attribute,
    save_brand_inline,
    delete_brand,
    save_model_inline,
    delete_model,
    save_vin_inline,
    delete_vin,
    get_supplier_form,
    get_product_form,
    get_attribute_fields,
    get_category_form,
    product_qr_pdf,
    qr_stock_in,
    search_inventory,
    filter_options,
    inventory_analytics,
    add_location,
    edit_location,
    delete_location,
    bulk_delete_locations,
    get_location_form,
)

from .views import (
    signup, payment, signup_thankyou, activate, activation_complete, GroupedInvoiceListView, GroupedInvoiceDetailView, GroupedInvoiceCreateView, GroupedInvoiceUpdateView, GroupedInvoiceDeleteView,
    MechExpenseListView, MechExpenseDetailView, MechExpenseCreateView, MechExpenseUpdateView, MechExpenseDeleteView,
    manage_models, send_invoice_email, success_page, edit_profile, profile_view, edit_dailylog,
    AppointmentListView, AppointmentDetailView,
    ContactMessageListView, ContactMessageDetailView,
)
from . import view_workorder

app_name = 'accounts'


urlpatterns = [
    path('complete-profile/', views.profile_completion_view, name='profile_completion'),
    path('privacy-policy/', privacy_policy_view, name='privacy_policy'),
    path('cookies_policy/', cookies_policy_view, name='cookies_policy'),
    path('terms-and-conditions/', terms_and_conditions_view, name='terms_and_conditions'),
        path('password_change/', auth_views.PasswordChangeView.as_view(
        template_name='accounts/password_change.html',
        success_url=reverse_lazy('accounts:password_change_done')
    ), name='password_change'),
    path('password_change/done/', auth_views.PasswordChangeDoneView.as_view(
        template_name='accounts/password_change_done.html'
    ), name='password_change_done'),
    path('generate-payment-link/<int:invoice_id>/', views.generate_payment_link_view, name='generate_payment_link'),
    path('connect-stripe/', views.connect_stripe_account, name='connect_stripe'),
    path('payment-successful/', views.payment_success, name='payment_success'),
    path('clover/connect/', clover_views.clover_connect, name='clover_connect'),
    path('clover/callback/', clover_views.clover_callback, name='clover_callback'),
    path('clover/disconnect/', clover_views.clover_disconnect, name='clover_disconnect'),
    path('clover/webhook/', clover_views.clover_webhook, name='clover_webhook'),

    path('payment/', views.payment, name='payment'),
    path('choose_plan/', views.choose_plan, name='choose_plan'),

    path('cancel/', views.payment_cancel, name='payment_cancel'),
    path('check-payment-status/<int:invoice_id>/', views.check_payment_status, name='check_payment_status'),
    path('error/', views.error_page, name='error_page'),
    path('payment-already-made/', views.payment_already_made, name='payment_already_made'),
    path('account-setup-complete/', views.account_setup_complete, name='account_setup_complete'),
    path('reauth/', views.reauth, name='reauth'),
    path('subscription-cancelled/', views.subscription_cancelled, name='subscription_cancelled'),
    path('customize-invoice/', views.customize_invoice, name='customize_invoice'),
    path('qr-code-style/', views.qr_code_style, name='qr_code_style'),
    path('profile/edit/', edit_profile, name='edit_profile'),
    path('profile/', profile_view, name='profile_view'),
    path('payroll/settings/', payroll_views.payroll_settings_view, name='payroll_settings'),
    path('payroll/employees/', payroll_views.employee_list, name='employee_list'),
    path('payroll/employees/new/', payroll_views.employee_create, name='employee_create'),
    path('payroll/employees/<int:employee_id>/', payroll_views.employee_detail, name='employee_detail'),
    path('payroll/employees/<int:employee_id>/edit/', payroll_views.employee_update, name='employee_update'),
    path('payroll/employees/<int:employee_id>/delete/', payroll_views.employee_delete, name='employee_delete'),
    path('payroll/shift-templates/', payroll_views.shift_template_list, name='shift_template_list'),
    path('payroll/shift-templates/new/', payroll_views.shift_template_create, name='shift_template_create'),
    path('payroll/shift-templates/<int:template_id>/edit/', payroll_views.shift_template_update, name='shift_template_update'),
    path('payroll/shift-templates/<int:template_id>/delete/', payroll_views.shift_template_delete, name='shift_template_delete'),
    path('payroll/timesheets/', payroll_views.timesheet_list, name='timesheet_list'),
    path('payroll/timesheets/weekly/', payroll_views.timesheet_weekly_grid, name='timesheet_weekly_grid'),
    path('payroll/timesheets/new/', payroll_views.timesheet_create, name='timesheet_create'),
    path('payroll/timesheets/<int:timesheet_id>/', payroll_views.timesheet_detail, name='timesheet_detail'),
    path('payroll/timesheets/employee/', payroll_views.timesheet_employee_redirect, name='timesheet_employee_redirect'),
    path('payroll/timesheets/bulk/', payroll_views.timesheet_bulk_entry, name='timesheet_bulk_entry'),
    path('payroll/timesheets/export/', payroll_views.timesheet_export, name='timesheet_export'),
    path('payroll/timesheets/import/', payroll_views.timesheet_import, name='timesheet_import'),
    path('payroll/timesheets/<int:timesheet_id>/delete/', payroll_views.timesheet_delete, name='timesheet_delete'),
    path('payroll/runs/', payroll_views.payroll_run_list, name='payroll_run_list'),
    path('payroll/runs/new/', payroll_views.payroll_run_create, name='payroll_run_create'),
    path('payroll/runs/<int:run_id>/', payroll_views.payroll_run_detail, name='payroll_run_detail'),
    path('payroll/runs/<int:run_id>/edit/', payroll_views.payroll_run_update, name='payroll_run_update'),
    path('payroll/runs/<int:run_id>/delete/', payroll_views.payroll_run_delete, name='payroll_run_delete'),
    path('payroll/runs/<int:run_id>/paystubs/download/', payroll_views.payroll_run_paystubs_download, name='payroll_run_paystubs_download'),
    path('payroll/runs/<int:run_id>/paystubs/send/', payroll_views.payroll_run_paystubs_send, name='payroll_run_paystubs_send'),
    path('payroll/runs/<int:run_id>/paystubs/export/', payroll_views.payroll_run_paystubs_export, name='payroll_run_paystubs_export'),
    path('payroll/runs/<int:run_id>/paystubs/import/', payroll_views.payroll_run_paystubs_import, name='payroll_run_paystubs_import'),
    path('', views.public_home, name='public_home'),  # Public home page URL
    path('about/', views.public_about, name='public_about'),  # About page URL
    path('services/', views.public_services, name='public_services'),  # Services page URL
    path('contact/', views.public_contact, name='public_contact'),  # Contact page URL
    path('faq/', views.public_faq, name='public_faq'),
    # Public transport feature endpoints
    path('booking/', views.public_booking, name='public_booking'),
    path('booking/slots/', views.booking_slots, name='booking_slots'),
    # Service detail pages
    path('services/engine/', views.service_engine, name='service_engine'),
    path('services/transmission/', views.service_transmission, name='service_transmission'),
    path('services/brakes/', views.service_brakes, name='service_brakes'),
    path('services/electrical/', views.service_electrical, name='service_electrical'),
    path('services/maintenance/', views.service_maintenance, name='service_maintenance'),
    path('services/dot/', views.service_dot, name='service_dot'),
    path('services/dpf/', views.service_dpf, name='service_dpf'),
    path('services/tires/', views.service_tires, name='service_tires'),
    path('services/road-service/', views.service_road_service, name='service_road_service'),
    path('emergency/', views.public_emergency, name='public_emergency'),
    path('contact-form/', views.public_contact_form, name='public_contact_form'),
    path('api/public/ai-chat/', public_ai.public_ai_chat, name='public_ai_chat'),
    path('store/api/ai-chat/', customer_ai.customer_ai_chat, name='customer_ai_chat'),
    path('pm-inspection/', views.pm_inspection_download, name='pm_inspection_download'),
    path('pm-inspection/blank/pdf/', view_workorder.download_blank_pm_inspection_pdf, name='pm_inspection_blank_pdf'),
    # Storefront URLs
    path(
        'store/login/',
        RedirectView.as_view(pattern_name='accounts:login', permanent=False),
        name='customer_login',
    ),
    path('store/signup/', views.customer_signup, name='customer_signup'),
    path('store/signup/pending/', views.customer_signup_pending, name='customer_signup_pending'),
    path('store/location/', store_views.set_storefront_location, name='storefront_location_set'),
    path('store/weather/', store_views.storefront_weather, name='storefront_weather'),
    path('store/', store_views.product_list, name='store_product_list'),
    path('store/search/', store_views.store_search, name='store_search'),
    path('store/search/suggestions/', store_views.store_search_suggestions, name='store_search_suggestions'),
    path('store/quick-order/', store_views.quick_order, name='store_quick_order'),
    path('store/quick-order/suggestions/', store_views.quick_order_suggestions, name='store_quick_order_suggestions'),
    path('store/favorites/', store_views.favorites_view, name='store_favorites'),
    path('store/favorites/toggle/<int:product_id>/', store_views.toggle_favorite, name='store_favorite_toggle'),
    path('store/group/<int:group_id>/', store_views.store_group_detail, name='store_group_detail'),
    path('store/category/<int:category_id>/', store_views.store_category_detail, name='store_category_detail'),
    path('store/product/<int:pk>/', store_views.product_detail, name='store_product_detail'),
    path('store/add/<int:product_id>/', store_views.add_to_cart, name='store_add_to_cart'),
    path('store/kit/<int:kit_id>/add/', store_views.add_kit_to_cart, name='store_add_kit_to_cart'),
    path('store/cart/', store_views.cart_view, name='store_cart'),
    path('store/update/<int:product_id>/', store_views.update_cart, name='store_update_cart'),
    path('store/checkout/', store_views.checkout, name='store_checkout'),
    path('store/flyer/', store_views.storefront_flyer, name='storefront_flyer'),
    path('store/flyer/pdf/', store_views.storefront_flyer_pdf, name='storefront_flyer_pdf'),
    path('account/store/', store_views.customer_dashboard, name='customer_dashboard'),
    path(
        'store/account/',
        RedirectView.as_view(pattern_name='accounts:customer_dashboard', permanent=True),
    ),
    path('store/profile/', store_views.customer_profile, name='customer_profile'),
    path('store/orders/', store_views.customer_orders, name='customer_orders'),
    path('store/invoices/', store_views.customer_invoice_list, name='customer_invoice_list'),
    path('store/returns/', store_views.customer_returns, name='customer_returns'),
    path('store/invoices/<int:invoice_id>/download/', store_views.customer_invoice_download, name='customer_invoice_download'),
    path('store/invoices/<int:invoice_id>/print/', store_views.customer_invoice_print, name='customer_invoice_print'),
    path('store/invoices/statements/', store_views.customer_invoice_statements, name='customer_invoice_statements'),
    path('store/workorders/', store_views.customer_workorder_list, name='customer_workorder_list'),
    path('store/workorders/<int:workorder_id>/download/', store_views.customer_workorder_download, name='customer_workorder_download'),
    path('store/vehicles/', store_views.customer_vehicle_overview, name='customer_vehicle_overview'),
    path('store/vehicles/<int:vehicle_id>/', store_views.customer_vehicle_detail, name='customer_vehicle_detail'),
    path('store/vehicles/<int:vehicle_id>/inline/', store_views.customer_vehicle_inline_update, name='customer_vehicle_inline_update'),
    path('store/vehicles/<int:vehicle_id>/maintenance/add/', store_views.customer_vehicle_add_maintenance, name='customer_vehicle_add_maintenance'),
    path('store/maintenance/<int:task_id>/status/', store_views.customer_vehicle_update_status, name='customer_vehicle_update_status'),
    path('store/maintenance/<int:task_id>/complete/', store_views.customer_vehicle_complete_maintenance, name='customer_vehicle_complete_maintenance'),
    path('store/maintenance/', store_views.customer_maintenance_list, name='customer_maintenance_list'),
    path('store/settlements/', store_views.customer_settlement_summary, name='customer_settlement_summary'),
    path('store/complete/<str:invoice_number>/', store_views.order_complete, name='store_order_complete'),
    path('store/hub/', store_views.store_hub, name='store_hub'),
    path('store/manage/', store_views.manage_storefront, name='store_manage'),
    path('store/hero/', store_views.manage_storefront_hero, name='store_hero'),
    path('store/suggestions/', store_views.manage_storefront_suggestions, name='store_suggestions'),
    path('store/core-policy/', store_views.storefront_core_policy_download, name='store_core_policy_download'),
    path('dashboard/', views.home, name='home'),  # Authenticated home page URL
    path('dashboard/parts-store/feed/', views.parts_store_dashboard_feed, name='parts_store_dashboard_feed'),
    path('dashboard/parts-store/returns/lookup/', views.parts_store_return_lookup, name='parts_store_return_lookup'),
    path('dashboard/parts-store/returns/create/', views.parts_store_return_create, name='parts_store_return_create'),
    path('dashboard/parts-store/orders/<int:invoice_id>/status/', views.update_online_order_status, name='parts_store_order_status'),
    path('dashboard/parts-store/orders/<int:invoice_id>/cancel/', views.cancel_online_order, name='parts_store_order_cancel'),
    # Analytics lives at /analytics. Keep /dashboard/analytics as a backwards-compatible redirect.
    path('analytics/', views.analytics_overview, name='analytics'),
    path('accountant/', views.accountant_hub, name='accountant_hub'),
    path('accountant-portal/', views.accountant_portal_dashboard, name='accountant_portal_dashboard'),
    path('accountant-portal/login/', views.AccountantPortalLoginView.as_view(), name='accountant_portal_login'),
    path('accountant-portal/payroll-deductions/', views.accountant_portal_payroll_deductions, name='accountant_portal_payroll_deductions'),
    path('accountant-portal/payroll-deductions/<int:employee_id>/', views.accountant_portal_payroll_deductions_employee, name='accountant_portal_payroll_deductions_employee'),
    path('accountant-portal/download/', views.accountant_portal_download_report, name='accountant_portal_download_report'),
    path(
        'dashboard/analytics/',
        RedirectView.as_view(pattern_name='accounts:analytics', permanent=False),
        name='analytics_overview',
    ),
    path('dashboard/activity/', views.activity_log_list, name='activity_log_list'),
    path('admin-approvals/<int:profile_id>/approve/', views.approve_admin_profile, name='approve_admin_profile'),
    path('login/', views.CustomLoginView.as_view(), name='login'),  # Login URL
    path('signup/', views.signup_options, name='signup_options'),
    path('signup/admin/', views.admin_signup, name='admin_signup'),
    path(
        'mechanic/login/',
        RedirectView.as_view(pattern_name='accounts:login', permanent=False),
        name='mechanic_portal_login',
    ),
    path('mechanic/dashboard/', view_workorder.mechanic_portal_dashboard, name='mechanic_portal_dashboard'),
    path('mechanic/maintenance/<int:task_id>/create-workorder/', view_workorder.mechanic_quick_vehicle_workorder, name='mechanic_quick_vehicle_workorder'),
    path('mechanic/maintenance/<int:task_id>/join-workorder/', view_workorder.mechanic_join_workorder, name='mechanic_join_workorder'),
    path('mechanic/jobs/', view_workorder.mechanic_jobs, name='mechanic_jobs'),
    path('mechanic/products/', view_workorder.mechanic_products, name='mechanic_products'),
    path('mechanic/products/<int:pk>/update/', view_workorder.mechanic_product_update, name='mechanic_product_update'),
    path('mechanic/timesheets/', view_workorder.mechanic_timesheet_list, name='mechanic_timesheet_list'),
    path('mechanic/timesheets/current/', view_workorder.mechanic_timesheet_current, name='mechanic_timesheet_current'),
    path('mechanic/timesheets/<int:timesheet_id>/', view_workorder.mechanic_timesheet_detail, name='mechanic_timesheet_detail'),
    path('mechanic/paystubs/', view_workorder.mechanic_paystub_list, name='mechanic_paystub_list'),
    path('mechanic/paystubs/<int:paystub_id>/', view_workorder.mechanic_paystub_detail, name='mechanic_paystub_detail'),
    path('mechanic/paystubs/<int:paystub_id>/download/', view_workorder.mechanic_paystub_download, name='mechanic_paystub_download'),
    path('mechanic/signup/', view_workorder.mechanic_signup, name='mechanic_portal_signup'),
    path('mechanic/signup-code/', view_workorder.generate_mechanic_signup_code, name='generate_mechanic_signup_code'),
    path(
        'supplier/login/',
        RedirectView.as_view(pattern_name='accounts:login', permanent=False),
        name='supplier_login',
    ),
    path('supplier/dashboard/', supplier_views.supplier_dashboard, name='supplier_dashboard'),
    path('supplier/receipts/', supplier_views.supplier_receipts, name='supplier_receipts'),
    path('supplier/receipts/<int:receipt_id>/', supplier_views.supplier_receipt_detail, name='supplier_receipt_detail'),

    # Note-related paths
    path('notes/add/', noteview.add_note, name='notes_add'),
    path('notes/edit/<int:note_id>/', noteview.edit_note, name='notes_edit'),
    path('notes/delete/<int:note_id>/', noteview.delete_note, name='notes_delete'),
    path('notes/pin/<int:note_id>/', noteview.pin_note, name='notes_pin'),
    path('notes/expand/', noteview.expand_notes, name='notes_expand'),
    path('live_search/', noteview.live_search, name='live_search'),
    path('notes/sort/', noteview.notes_sort, name='notes_sort'),

    path('upload-receipt/', receipt_views.upload_receipt, name='upload_receipt'),

    path('maintenance/', views.maintenance_center, name='maintenance_center'),
    path('maintenance/send/', views.send_maintenance_reminders, name='maintenance_send'),

    path('communications/hub/', views.CommunicationHubView.as_view(), name='communication_hub'),
    path('communications/flyers/', views.flyer_campaigns, name='flyer_campaigns'),
    # Authenticated backend for public forms
    path('appointments/', AppointmentListView.as_view(), name='appointments_list'),
    path('appointments/<int:pk>/', AppointmentDetailView.as_view(), name='appointments_detail'),
    path('contacts/', ContactMessageListView.as_view(), name='contacts_list'),
    path('contacts/<int:pk>/', ContactMessageDetailView.as_view(), name='contacts_detail'),

    path('pending_invoices/', views.PendingInvoiceListView.as_view(), name='pending_invoice_list'),
    path('pending_invoices/mark_paid/<int:pk>/', views.MarkInvoicePaidView.as_view(), name='mark_invoice_paid'),
    path('groupedinvoice/<int:pk>/mark_unpaid/', views.MarkInvoiceUnpaidView.as_view(), name='mark_invoice_unpaid'),
    path('session/ping/', views.session_ping, name='session_ping'),
    path('logout/', LogoutView.as_view(next_page='accounts:login'), name='logout'),
    path('add-records/', views.add_records, name='add_records'),
    path('add-dailylog/', views.add_dailylog, name='add_dailylog'),

        # WorkOrder URLs
    path('workorders/', view_workorder.workorder_list, name='workorder_list'),
    path('workorders/add/', view_workorder.add_workorder, name='add_workorder'),
    path('workorders/<int:pk>/', view_workorder.workorder_detail, name='workorder_detail'),
    path('workorders/<int:pk>/quick-update/', view_workorder.workorder_quick_update, name='workorder_quick_update'),
    path('workorders/<int:pk>/recreate-invoice/', view_workorder.workorder_recreate_invoice, name='workorder_recreate_invoice'),
    path(
        'workorders/<int:pk>/assignments/<int:assignment_id>/reopen/',
        view_workorder.workorder_assignment_request_rework,
        name='workorder_assignment_reopen'
    ),
    path('workorders/<int:pk>/download/', view_workorder.download_workorder_pdf, name='workorder_download'),
    path('workorders/<int:pk>/pm-sheet/download/', view_workorder.download_pm_inspection_pdf, name='workorder_pm_download'),
    path('workorders/<int:pk>/edit/', view_workorder.workorder_update, name='workorder_update'),
    path('workorders/<int:pk>/delete/', view_workorder.workorder_delete, name='workorder_delete'),
    path('workorders/vehicle-history/', view_workorder.vehicle_history_summary, name='vehicle_history_summary'),
    path('workorders/vehicle-maintenance/', view_workorder.vehicle_maintenance_summary, name='vehicle_maintenance_summary'),

    # Comment out or remove any email-resend route
    # path('workorders/<int:pk>/resend_emails/', view_workorder.resend_assignment_emails, name='resend_assignment_emails'),

    # Mechanic assignment link using token
    path('workorders/fill/<str:assignment_token>/', view_workorder.mechanic_fill_workorder, name='mechanic_fill_workorder'),
    path(
        'workorders/fill/<str:assignment_token>/pm-checklist/',
        view_workorder.mechanic_pm_checklist,
        name='mechanic_pm_checklist'
    ),
    path(
        'workorders/fill/<str:assignment_token>/pm-checklist/save/',
        view_workorder.mechanic_pm_checklist_submit,
        name='mechanic_pm_checklist_submit'
    ),
    path(
        'workorders/fill/<str:assignment_token>/pm-checklist/pdf/',
        view_workorder.mechanic_pm_checklist_pdf,
        name='mechanic_pm_checklist_pdf'
    ),

    path(
        'mechanic/success/',
        view_workorder.mechanic_workorder_success,
        name='mechanic_workorder_success'
    ),

    # Mechanic views
    path('mechanics/', view_workorder.mechanic_list, name='mechanic_list'),
    path('mechanics/add/', view_workorder.mechanic_create, name='mechanic_create'),
    path('mechanics/<int:pk>/', view_workorder.mechanic_detail, name='mechanic_detail'),
    path('mechanics/<int:pk>/edit/', view_workorder.mechanic_update, name='mechanic_update'),
    path('mechanics/<int:pk>/delete/', view_workorder.mechanic_delete, name='mechanic_delete'),
    path('mechanics/<int:pk>/register/', view_workorder.mechanic_register, name='mechanic_register'),


    path('add_estimate/', views.add_estimate, name='add_estimate'),
    path('estimate-list/', views.GroupedEstimateListView.as_view(), name='estimate_list'),
    path('estimate/<int:pk>/', views.GroupedEstimateDetailView.as_view(), name='estimate_detail'),
    path('estimate/<int:pk>/edit/', views.edit_estimate, name='estimate_edit'),
    path('estimate/<int:pk>/delete/', views.GroupedEstimateDeleteView.as_view(), name='estimate_delete'),
    path('convert_estimate/<int:estimate_id>/', views.convert_estimate_to_invoice, name='convert_estimate_to_invoice'),

    path("stripe/webhook/", views.stripe_webhook, name="stripe_webhook"),

    # Optionally, if you still need a combined daily log view:
    path('check-username/', views.check_username, name='check_username'),
    path('contact-support/', views.contact_support, name='contact_support'),
    path('password-reset/', views.password_reset_request, name='password_reset'),
    path('password-reset-done/', views.password_reset_done, name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', views.password_reset_confirm, name='password_reset_confirm'),
    path('password-reset-complete/', views.password_reset_complete, name='password_reset_complete'),
    path('update-invoice-status/', views.update_invoice_status, name='update_invoice_status'),
    path('tables/', views.tables, name='tables'),
    path('download_report/', views.download_report, name='download_report'),
    path('income-details/', views.income_details_by_date, name='income_details_by_date'),
    path('expense-details/', views.expense_details_by_date, name='expense_details_by_date'),


    path('manage-models/', manage_models, name='manage_models'),
    path('grouped-invoices/', GroupedInvoiceListView.as_view(), name='groupedinvoice_list'),
    path('grouped-invoices/add/', GroupedInvoiceCreateView.as_view(), name='groupedinvoice_add'),
    path('grouped-invoices/<int:pk>/', GroupedInvoiceDetailView.as_view(), name='groupedinvoice_detail'),
    path('grouped-invoices/<int:pk>/edit/', edit_dailylog, name='groupedinvoice_edit'),
    path('grouped-invoices/<int:pk>/delete/', GroupedInvoiceDeleteView.as_view(), name='groupedinvoice_delete'),
    path('dashboard/quick-invoice/', views.quick_invoice_create, name='quick_invoice_create'),

    path('mech-expenses/', MechExpenseListView.as_view(), name='mechexpense_list'),
    path('mech-expenses/mark-paid/', views.mark_mech_expenses_paid, name='mechexpense_mark_paid'),
    path('mech-expenses/<int:pk>/toggle-status/', views.toggle_mech_expense_status, name='mechexpense_toggle_status'),
    path('mech-expenses/add/', MechExpenseCreateView.as_view(), name='mechexpense_add'),
    path('mech-expenses/<int:pk>/', MechExpenseDetailView.as_view(), name='mechexpense_detail'),
    path('mech-expenses/<int:pk>/edit/', MechExpenseUpdateView.as_view(), name='mechexpense_edit'),
    path('mech-expenses/<int:pk>/delete/', MechExpenseDeleteView.as_view(), name='mechexpense_delete'),
    path('customer-credits/', views.CustomerCreditListView.as_view(), name='customer_credit_list'),
    path('customer-credits/invoices/', views.customer_credit_invoices, name='customer_credit_invoices'),
    path('customer-credits/add/', views.CustomerCreditCreateView.as_view(), name='customer_credit_add'),
    path('customer-credits/<int:pk>/', views.CustomerCreditDetailView.as_view(), name='customer_credit_detail'),
    path('customer-credits/<int:pk>/pdf/', views.customer_credit_pdf, name='customer_credit_pdf'),
    path('customer-credits/<int:pk>/print/', views.customer_credit_print, name='customer_credit_print'),
    path('customer-credits/<int:pk>/email/', views.customer_credit_email, name='customer_credit_email'),
    path('customer-credits/<int:pk>/edit/', views.CustomerCreditUpdateView.as_view(), name='customer_credit_edit'),
    path('customer-credits/<int:pk>/delete/', views.CustomerCreditDeleteView.as_view(), name='customer_credit_delete'),
    path('supplier-credits/', views.SupplierCreditListView.as_view(), name='supplier_credit_list'),
    path('supplier-credits/receipts/', views.supplier_credit_receipts, name='supplier_credit_receipts'),
    path('supplier-credits/add/', views.SupplierCreditCreateView.as_view(), name='supplier_credit_add'),
    path('supplier-credits/<int:pk>/', views.SupplierCreditDetailView.as_view(), name='supplier_credit_detail'),
    path('supplier-credits/<int:pk>/edit/', views.SupplierCreditUpdateView.as_view(), name='supplier_credit_edit'),
    path('supplier-credits/<int:pk>/delete/', views.SupplierCreditDeleteView.as_view(), name='supplier_credit_delete'),
    path('supplier-cheques/', views.supplier_cheque_list, name='supplier_cheque_list'),
    path('supplier-cheques/expenses/', views.supplier_cheque_expenses, name='supplier_cheque_expenses'),
    path('supplier-cheques/add/', views.supplier_cheque_create, name='supplier_cheque_add'),
    path('supplier-cheques/<int:pk>/', views.supplier_cheque_detail, name='supplier_cheque_detail'),
    path('supplier-cheques/<int:pk>/pdf/', views.supplier_cheque_pdf, name='supplier_cheque_pdf'),
    path('bank-accounts/add/', views.bank_account_create, name='bank_account_add'),
    path('suppliers/', views.vendor_list, name='supplier_list'),
    path('suppliers/make-payment/', views.supplier_make_payment, name='supplier_make_payment'),
    path('suppliers/<path:supplier_name>/entries/', views.vendor_entries, name='supplier_entries'),
    path('suppliers/<path:supplier_name>/', views.vendor_detail, name='supplier_detail'),
    path('suppliers/<path:supplier_name>/delete/', views.vendor_delete, name='supplier_delete'),
    path('vendors/', views.vendor_list, name='vendor_list'),
    path('vendors/<path:vendor_name>/', views.vendor_detail, name='vendor_detail'),
    path('vendors/<path:vendor_name>/delete/', views.vendor_delete, name='vendor_delete'),

    path('categories/', views.category_list, name='category_list'),
    path('categories/<int:pk>/delete/', views.delete_user_category, name='delete_user_category'),
    path('services/ajax/create/', views.create_service_description, name='create_service_description'),
    path('services/manage/', views.service_list, name='service_list'),
    path('services/inline/save/', views.save_service_inline, name='service_inline_save'),
    path(
        'services/job-name/<int:pk>/rename/',
        views.rename_service_job_name,
        name='rename_service_job_name',
    ),
    path('services/export/', views.export_services_template, name='services_export_template'),
    path('services/import/', views.import_services_from_excel, name='services_import'),
    path('services/delete/', views.bulk_delete_services, name='bulk_delete_services'),
    path('services/<int:pk>/delete/', views.delete_service, name='delete_service'),

    path('customers/', views.customer_list, name='customer_list'),
    path('customers/merge/', views.merge_customers, name='merge_customers'),
    path('customer/<int:customer_id>/<str:invoice_type>/', views.customer_detail, name='customer_detail'),
    path('customer/edit/<int:customer_id>/', views.customer_edit, name='customer_edit'),
    path('delete-customer/<int:customer_id>/', views.delete_customer, name='delete_customer'),

    path('customers/overdue/', views.customer_overdue_list, name='customer_overdue_list'),
    path('customers/portal-credentials/', views.create_customer_portal_credentials, name='customer_portal_credentials'),
    path('customers/send-signup/', views.send_customer_signup_invite, name='send_customer_signup'),
    path('customers/approvals/', views.customer_approvals, name='customer_approvals'),
    path('customers/approvals/<int:customer_id>/approve/', views.approve_customer_signup, name='approve_customer_signup'),

    path('add_customer/', views.add_customer, name='add_customer'),

    path('send-invoice-email/', send_invoice_email, name='send_invoice_email'),
    path('invoice/track/<str:token>/', view_invoices.track_invoice_email_open, name='invoice_email_open'),
    path('success/', success_page, name='success_page'),




    path('generate-invoices/', views.generate_invoices_detail, name='generate_invoices'),
    path('track-expenses/', views.track_expenses_detail, name='track_expenses'),
    path('manage-inventory/', views.manage_inventory_detail, name='manage_inventory'),
    path('search-purchases/', views.search_purchases_detail, name='search_purchases'),
    path('income-expense-table/', views.income_expense_table_detail, name='income_expense_table'),
    path('process-payments/', views.process_payments_detail, name='process_payments'),

    # path('signup/', views.signup, name='signup'),
    path('signup-thankyou/', signup_thankyou, name='signup_thankyou'),
    path('activate/<uidb64>/<token>/', activate, name='activate'),
    path('activation_complete/', views.activation_complete, name='activation_complete'),
    path('activation_invalid/', views.activation_invalid, name='activation_invalid'),
    path('activation_required/', views.activation_require, name='activation_required'),
    path('resend-activation/', views.resend_activation_email, name='resend_activation'),
    path('account-settings/', views.account_settings, name='account_settings'),
    path('account-settings/connected-business/', views.connected_business_update, name='connected_business_update'),
    path('account-settings/connected-business/add/', views.connected_business_add_member, name='connected_business_add'),
    path('account-settings/connected-business/remove/<int:member_id>/', views.connected_business_remove_member, name='connected_business_remove'),
    path('account-settings/connected-business/copy-inventory/', views.connected_business_copy_inventory, name='connected_business_copy_inventory'),
    path('account-settings/invoice-sequence/', views.update_invoice_sequence, name='update_invoice_sequence'),
    path('display-preferences/', views.display_preferences, name='display_preferences'),
    path('banking/settings/', views.banking_settings, name='banking_settings'),
    path('banking/transactions/', views.banking_transactions, name='banking_transactions'),
    path('banking/disconnect/', views.banking_disconnect, name='banking_disconnect'),
    path('quickbooks/settings/', views.quickbooks_settings, name='quickbooks_settings'),
    path('quickbooks/disconnect/', views.quickbooks_disconnect, name='quickbooks_disconnect'),
    path('quickbooks/sync/', views.quickbooks_sync_action, name='quickbooks_sync'),
    path('disconnect-stripe/', views.disconnect_stripe_account, name='disconnect_stripe'),
    path('change-card/', views.change_card, name='change_card'),
    path('cancel-subscription/', views.cancel_subscription, name='cancel_subscription'),
    path('subscription-details/', views.subscription_details, name='subscription_details'),
    path('invoices/add_payment/', views.AddPaymentView.as_view(), name='add_payment'),
    path('invoices/payment_history/', views.payment_history, name='payment_history'),
    path('invoices/<int:pk>/payment_history/manage/', views.invoice_payment_history_manage, name='invoice_payment_history_manage'),
    path('invoices/payments/<int:pk>/delete/', views.InvoicePaymentDeleteView.as_view(), name='invoice_payment_delete'),
    path('invoices/payments/<int:pk>/update/', views.InvoicePaymentUpdateView.as_view(), name='invoice_payment_update'),
    path('invoices/overdue/', views.OverdueInvoiceListView.as_view(), name='overdue_invoice_list'),
    path('customers/<int:customer_id>/invoices/download/', invoice_utils.download_invoice_pdf, name='download_invoice_pdf'),
    path('customers/<int:customer_id>/invoices/print/', invoice_utils.print_invoice_pdf, name='print_invoice_pdf'),
    path('customers/<int:customer_id>/invoices/send/', invoice_utils.send_invoice_statement, name='send_invoice_statement'),

    path('customers/<int:customer_id>/overdue/reminder/', invoice_utils.trigger_overdue_reminder, name='trigger_overdue_reminder'),
    path('customers/<int:customer_id>/overdue/followup/', views.update_overdue_followup, name='update_overdue_followup'),
    path('customers/<int:customer_id>/payments/record/', views.record_customer_payment, name='record_customer_payment'),

    path('add_customer/', views.add_customer, name='add_customer'),
    path('get_customer_details/', views.get_customer_details, name='get_customer_details'),

    path('invoice/<int:pk>/print/', views.print_invoice, name='print_invoice'),
    path('invoice/<int:pk>/download/', views.download_invoice, name='download_invoice'),
    path('invoice/<int:pk>/email/', views.email_invoice, name='email_invoice'),
    path('invoice/<int:pk>/', views.GroupedInvoiceDetailView.as_view(), name='invoice_detail'),




    path('complete-profile/', views.profile_completion_view, name='profile_completion'),

    path('api/login/', viewapi.api_login, name='api_login'),
    path('api/dashboard/', viewapi.api_dashboard, name='api_dashboard'),


    path('inventory/', inventory_view, name='inventory_view'),
    path('inventory/hub/', inventory_hub, name='inventory_hub'),
    path('inventory/transactions/', inventory_transactions_view, name='inventory_transactions'),
    path('inventory/products/', inventory_products_view, name='inventory_products'),
    path('inventory/stock-orders/', inventory_stock_orders_view, name='inventory_stock_orders'),
    path('inventory/suppliers/', inventory_suppliers_view, name='inventory_suppliers'),
    path('inventory/categories/', inventory_categories_view, name='inventory_categories'),
    path('inventory/category-groups/', inventory_category_groups_view, name='inventory_category_groups'),
    path('inventory/attributes/', inventory_attributes_view, name='inventory_attributes'),
    path('inventory/brands/', inventory_brands_view, name='inventory_brands'),
    path('inventory/models/', inventory_models_view, name='inventory_models'),
    path('inventory/vins/', inventory_vins_view, name='inventory_vins'),
    path('inventory/locations/', inventory_locations_view, name='inventory_locations'),
    path('inventory/search/', search_inventory, name='inventory_search'),
    path('inventory/filter-options/', filter_options, name='inventory_filter_options'),

    # Transaction CRUD + "get" form
    path('inventory/add_transaction/', add_transaction, name='add_transaction'),
    path('inventory/edit_transaction/', edit_transaction, name='edit_transaction'),
    path('inventory/delete_transaction/', delete_transaction, name='delete_transaction'),
    path('inventory/get_transaction_form/', get_transaction_form, name='get_transaction_form'),

    # Supplier CRUD + "get" form
    path('inventory/add_supplier/', add_supplier, name='add_supplier'),
    path('inventory/suppliers/inline/save/', save_supplier_inline, name='inventory_supplier_inline_save'),
    path('inventory/edit_supplier/', edit_supplier, name='edit_supplier'),
    path('inventory/delete_supplier/', delete_supplier, name='delete_supplier'),
    path('inventory/suppliers/delete/<int:pk>/', delete_inventory_supplier, name='inventory_supplier_delete'),
    path('inventory/get_supplier_form/', get_supplier_form, name='get_supplier_form'),
    path('inventory/suppliers/template/', export_suppliers_template, name='inventory_suppliers_template'),
    path('inventory/suppliers/import/', import_suppliers_from_excel, name='inventory_suppliers_import'),
    path('inventory/suppliers/bulk-delete/', bulk_delete_suppliers, name='inventory_suppliers_bulk_delete'),

    # Product CRUD + "get" form
    path('inventory/add_product/', add_product, name='add_product'),
    path('inventory/products/inline/save/', save_product_inline, name='inventory_product_inline_save'),
    path('inventory/edit_product/', edit_product, name='edit_product'),
    path('inventory/products/attributes/update/', update_product_attributes, name='inventory_product_attributes_update'),
    path('inventory/delete_product/', delete_product, name='delete_product'),
    path('inventory/products/delete/<int:pk>/', delete_inventory_product, name='inventory_product_delete'),
    path('inventory/get_product_form/', get_product_form, name='get_product_form'),
    path('inventory/get_attribute_fields/', get_attribute_fields, name='get_attribute_fields'),
    path('inventory/products/quick-create/', views.quick_create_inventory_product, name='quick_create_inventory_product'),
    path('inventory/products/template/', export_products_template, name='inventory_products_template'),
    path('inventory/products/import/', import_products_from_excel, name='inventory_products_import'),
    path('inventory/products/bulk-delete/', bulk_delete_products, name='inventory_products_bulk_delete'),
    path('inventory/products/bulk-update/', bulk_update_products, name='inventory_products_bulk_update'),
    path('inventory/products/update-margin/', update_inventory_margin, name='inventory_update_margin'),
    path('inventory/products/apply-margin/', apply_margin_to_products, name='inventory_apply_margin'),

    # QR code PDF and stock-in
    path('inventory/product/<int:product_id>/qr/', product_qr_pdf, name='product_qr_pdf'),
    path('inventory/stock_in/<int:product_id>/', qr_stock_in, name='qr_stock_in'),
    path('inventory/analytics/', inventory_analytics, name='inventory_analytics'),

    # Category CRUD + "get" form
    path('inventory/add_category/', add_category, name='add_category'),
    path('inventory/categories/inline/save/', save_category_inline, name='inventory_category_inline_save'),
    path('inventory/edit_category/', edit_category, name='edit_category'),
    path('inventory/delete_category/', delete_category, name='delete_category'),
    path('inventory/categories/delete/<int:pk>/', delete_inventory_category, name='inventory_category_delete'),
    path('inventory/get_category_form/', get_category_form, name='get_category_form'),
    path('inventory/categories/template/', export_categories_template, name='inventory_categories_template'),
    path('inventory/categories/import/', import_categories_from_excel, name='inventory_categories_import'),
    path('inventory/categories/bulk-delete/', bulk_delete_categories, name='inventory_categories_bulk_delete'),

    # Category group CRUD
    path('inventory/category-groups/template/', export_category_groups_template, name='inventory_category_groups_template'),
    path('inventory/category-groups/import/', import_category_groups_from_excel, name='inventory_category_groups_import'),
    path('inventory/category-groups/inline/save/', save_category_group_inline, name='inventory_category_group_inline_save'),
    path('inventory/category-groups/delete/<int:pk>/', delete_category_group, name='inventory_category_group_delete'),

    # Attribute CRUD
    path('inventory/attributes/inline/save/', save_attribute_inline, name='inventory_attribute_inline_save'),
    path('inventory/attributes/delete/<int:pk>/', delete_attribute, name='inventory_attribute_delete'),

    # Brand CRUD
    path('inventory/brands/template/', export_brands_template, name='inventory_brands_template'),
    path('inventory/brands/import/', import_brands_from_excel, name='inventory_brands_import'),
    path('inventory/brands/inline/save/', save_brand_inline, name='inventory_brand_inline_save'),
    path('inventory/brands/delete/<int:pk>/', delete_brand, name='inventory_brand_delete'),

    # Model CRUD
    path('inventory/models/template/', export_models_template, name='inventory_models_template'),
    path('inventory/models/import/', import_models_from_excel, name='inventory_models_import'),
    path('inventory/models/inline/save/', save_model_inline, name='inventory_model_inline_save'),
    path('inventory/models/delete/<int:pk>/', delete_model, name='inventory_model_delete'),

    # VIN CRUD
    path('inventory/vins/template/', export_vins_template, name='inventory_vins_template'),
    path('inventory/vins/import/', import_vins_from_excel, name='inventory_vins_import'),
    path('inventory/vins/inline/save/', save_vin_inline, name='inventory_vin_inline_save'),
    path('inventory/vins/delete/<int:pk>/', delete_vin, name='inventory_vin_delete'),

    # Location CRUD + "get" form
    path('inventory/add_location/', add_location, name='add_location'),
    path('inventory/edit_location/', edit_location, name='edit_location'),
    path('inventory/delete_location/', delete_location, name='delete_location'),
    path('inventory/get_location_form/', get_location_form, name='get_location_form'),
    path('inventory/locations/template/', export_locations_template, name='inventory_locations_template'),
    path('inventory/locations/import/', import_locations_from_excel, name='inventory_locations_import'),
    path('inventory/locations/bulk-delete/', bulk_delete_locations, name='inventory_locations_bulk_delete'),



    path('work-orders/', view_public_home.work_order, name='work_order'),
    path('inventory-info/', view_public_home.inventory, name='inventory_info'),
    path('statements/', view_public_home.statements, name='statements'),
    path('customer-management/', view_public_home.customer_management, name='customer_management'),
    path('invoices/generation/', view_public_home.invoice_generation, name='invoice_generation'),
    path('invoices/', view_public_home.invoice_list, name='invoice_list'),
    path('invoices/<int:invoice_id>/', view_public_home.invoice_detail, name='invoice_detail'),
    path('expenses/', view_public_home.expense_tracking, name='expense_tracking'),
    path('payments/', view_public_home.payment_processing, name='payment_processing'),

    path('groupedinvoice/<int:pk>/pdf/', view_invoices.generate_grouped_invoice_pdf, name='generate_grouped_invoice_pdf'),
    path('groupedinvoice/<int:pk>/print/', view_invoices.print_grouped_invoice_pdf, name='print_grouped_invoice_pdf'),
    path('groupedinvoice/<int:pk>/send-email/', view_invoices.send_grouped_invoice_email, name='send_grouped_invoice_email'),

    path('estimate/<int:pk>/pdf/', view_invoices.generate_estimate_pdf, name='generate_estimate_pdf'),
    path('estimate/<int:pk>/print/', view_invoices.print_estimate_pdf, name='print_estimate_pdf'),
    path('estimate/<int:pk>/send-email/', view_invoices.send_estimate_email, name='send_estimate_email'),

    path('groupedinvoice/<int:pk>/pdf/paid/',  paid_invoice_views.generate_paid_invoice_pdf,  name='generate_paid_invoice_pdf'),
    path('groupedinvoice/<int:pk>/print/paid/', paid_invoice_views.print_paid_invoice_pdf,     name='print_paid_invoice_pdf'),
    path('groupedinvoice/<int:pk>/send-email/paid/', paid_invoice_views.send_paid_invoice_email_view, name='send_paid_invoice_email'),

    path(
        "terminal/token/",
        view_payments.create_connection_token,
        name="create_connection_token",
    ),
    path(
        "terminal/payment-intent/<int:invoice_id>/",
        view_payments.create_terminal_payment_intent,
        name="create_terminal_payment_intent",
    ),
    path(
      "terminal/cancel-intent/<int:invoice_id>/",
      view_payments.cancel_terminal_payment_intent,
      name="cancel_terminal_payment_intent"
    ),
    path("terminal/register-reader/", view_payments.register_reader, name="register_reader"),
    path('customers/<int:customer_id>/vehicles/', views.customer_vehicle_list, name='customer_vehicle_list'),

    # --- NEW URL FOR A SPECIFIC VEHICLE'S JOB HISTORY ---
    path('vehicles/<int:vehicle_id>/history/', views.vehicle_job_history_list, name='vehicle_job_history_list'),
    path('vehicles/<int:vehicle_id>/', views.vehicle_detail_dashboard, name='vehicle_detail_dashboard'),
    path('vehicles/<int:vehicle_id>/maintenance/add/', views.vehicle_add_maintenance, name='vehicle_add_maintenance'),
    path('vehicles/maintenance/<int:task_id>/status/', views.vehicle_update_maintenance_status, name='vehicle_update_maintenance_status'),
    path('vehicles/maintenance/<int:task_id>/complete/', views.vehicle_complete_maintenance, name='vehicle_complete_maintenance'),
    path('vehicles/<int:vehicle_id>/quick-workorder/', views.vehicle_quick_workorder, name='vehicle_quick_workorder'),

    path('dashboard/vehicles/', views.vehicle_management, name='vehicle_management'),
    path('dashboard/vehicles/template/', views.export_vehicles_template, name='vehicle_management_template'),
    path('dashboard/vehicles/import/', views.import_vehicles_from_excel, name='vehicle_management_import'),
    path('vehicles/<int:vehicle_id>/maintenance/template/', views.export_vehicle_maintenance_template, name='vehicle_maintenance_template'),
    path('vehicles/<int:vehicle_id>/maintenance/import/', views.import_vehicle_maintenance_from_excel, name='vehicle_maintenance_import'),
    path('ajax/customer/<int:customer_id>/edit/', views.edit_customer_ajax, name='edit_customer_ajax'),

    # --- UPDATED URLS FOR VEHICLE EDIT/DELETE ---
    path('vehicles/<int:vehicle_id>/edit/', views.edit_vehicle, name='edit_vehicle'),
    path('vehicles/<int:vehicle_id>/delete/', views.delete_vehicle, name='delete_vehicle'),
    path(
        "api/customer/<int:pk>/vehicles/",
        views.customer_vehicles,          # ← view in step 2
        name="customer_vehicles",
    ),
    path(
        "api/vehicle/add/",
        views.add_vehicle,                # ← optional “add vehicle” endpoint
        name="add_vehicle",
    ),
    path('notifications/load/', views.product_low_stock_notifications, name='load_notifications'), # Changed name for clarity

    # Transport Management URLs
    path('transport/', include('accounts.transport_urls')),

    ]
