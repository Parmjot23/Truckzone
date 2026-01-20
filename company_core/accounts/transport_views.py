# accounts/transport_views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import date, timedelta
from .models import (
    TransportProfile, TransportCustomer, TransportVehicle, 
    TransportDriver, TransportTrip, TransportInvoice,
    Customer, GroupedInvoice
)
from .utils import get_customer_user_ids

@login_required
def transport_dashboard(request):
    """Main transport dashboard with key metrics and recent activity"""
    
    # Check if user has transport profile
    try:
        transport_profile = TransportProfile.objects.get(user=request.user)
    except TransportProfile.DoesNotExist:
        # Redirect to setup if no transport profile
        return redirect('accounts:transport_setup')
    
    # Key metrics
    total_vehicles = TransportVehicle.objects.filter(user=request.user).count()
    active_vehicles = TransportVehicle.objects.filter(user=request.user, status='active').count()
    total_drivers = TransportDriver.objects.filter(user=request.user).count()
    active_drivers = TransportDriver.objects.filter(user=request.user, employment_status='active').count()
    
    # Trip statistics
    active_trips = TransportTrip.objects.filter(
        user=request.user,
        status__in=['dispatched', 'en_route_pickup', 'at_pickup', 'loaded', 'en_route_delivery', 'at_delivery']
    ).count()
    
    delivered_trips = TransportTrip.objects.filter(
        user=request.user,
        status='delivered'
    ).count()
    
    # Revenue this month
    first_day_of_month = date.today().replace(day=1)
    monthly_revenue = TransportTrip.objects.filter(
        user=request.user,
        status='completed',
        created_at__gte=first_day_of_month
    ).aggregate(total=Sum('total_rate'))['total'] or 0
    
    # Recent trips
    recent_trips = TransportTrip.objects.filter(user=request.user).select_related(
        'customer', 'driver', 'vehicle'
    ).order_by('-created_at')[:10]
    
    # Alerts
    alerts = []
    
    # License expiry alerts
    next_month = date.today() + timedelta(days=30)
    expiring_licenses = TransportDriver.objects.filter(
        user=request.user,
        license_expiry__lte=next_month,
        employment_status='active'
    ).count()
    if expiring_licenses > 0:
        alerts.append({
            'type': 'warning',
            'message': f'{expiring_licenses} driver license(s) expiring within 30 days'
        })
    
    # Maintenance due alerts
    next_week = date.today() + timedelta(days=7)
    maintenance_due = TransportVehicle.objects.filter(
        user=request.user,
        next_maintenance__lte=next_week,
        status='active'
    ).count()
    if maintenance_due > 0:
        alerts.append({
            'type': 'warning',
            'message': f'{maintenance_due} vehicle(s) due for maintenance within 7 days'
        })
    
    context = {
        'transport_profile': transport_profile,
        'metrics': {
            'total_vehicles': total_vehicles,
            'active_vehicles': active_vehicles,
            'total_drivers': total_drivers,
            'active_drivers': active_drivers,
            'active_trips': active_trips,
            'delivered_trips': delivered_trips,
            'monthly_revenue': monthly_revenue,
        },
        'recent_trips': recent_trips,
        'alerts': alerts,
    }
    
    return render(request, 'accounts/transport/dashboard.html', context)

@login_required
def transport_setup(request):
    """Setup transport profile for new users"""
    if request.method == 'POST':
        # Create transport profile
        company_name = request.POST.get('company_name')
        dot_number = request.POST.get('dot_number')
        mc_number = request.POST.get('mc_number')
        
        if company_name:
            TransportProfile.objects.create(
                user=request.user,
                company_name=company_name,
                dot_number=dot_number,
                mc_number=mc_number,
            )
            messages.success(request, 'Transport profile created successfully!')
            return redirect('accounts:transport_dashboard')
        else:
            messages.error(request, 'Company name is required.')
    
    return render(request, 'accounts/transport/setup.html')

@login_required
def transport_trips(request):
    """List all trips with filtering options"""
    trips = TransportTrip.objects.filter(user=request.user).select_related(
        'customer', 'driver', 'vehicle'
    ).order_by('-created_at')
    
    # Filtering
    status_filter = request.GET.get('status')
    if status_filter:
        trips = trips.filter(status=status_filter)
    
    customer_filter = request.GET.get('customer')
    if customer_filter:
        trips = trips.filter(customer_id=customer_filter)
    
    # Get filter options
    customer_user_ids = get_customer_user_ids(request.user)
    customers = Customer.objects.filter(user__in=customer_user_ids)
    statuses = TransportTrip._meta.get_field('status').choices
    
    context = {
        'trips': trips,
        'customers': customers,
        'statuses': statuses,
        'current_status': status_filter,
        'current_customer': customer_filter,
    }
    
    return render(request, 'accounts/transport/trips.html', context)

@login_required
def transport_vehicles(request):
    """List all vehicles"""
    vehicles = TransportVehicle.objects.filter(user=request.user).order_by('unit_number')
    
    context = {
        'vehicles': vehicles,
    }
    
    return render(request, 'accounts/transport/vehicles.html', context)

@login_required
def transport_drivers(request):
    """List all drivers"""
    drivers = TransportDriver.objects.filter(user=request.user).order_by('last_name', 'first_name')
    
    context = {
        'drivers': drivers,
    }
    
    return render(request, 'accounts/transport/drivers.html', context)

@login_required
def transport_invoices(request):
    """List transport invoices"""
    transport_invoices = TransportInvoice.objects.filter(
        grouped_invoice__user=request.user
    ).select_related('grouped_invoice').order_by('-created_at')
    
    context = {
        'transport_invoices': transport_invoices,
    }
    
    return render(request, 'accounts/transport/invoices.html', context)

@login_required
def create_invoice_from_trips(request):
    """Create invoice from delivered trips"""
    if request.method == 'POST':
        trip_ids = request.POST.getlist('trip_ids')
        customer_id = request.POST.get('customer_id')
        
        if trip_ids and customer_id:
            try:
                from django.db import transaction
                
                with transaction.atomic():
                    # Create grouped invoice
                    customer_user_ids = get_customer_user_ids(request.user)
                    customer = get_object_or_404(Customer, id=customer_id, user__in=customer_user_ids)
                    
                    grouped_invoice = GroupedInvoice.objects.create(
                        user=request.user,
                        customer=customer,
                        date=date.today(),
                        bill_to=customer.name,
                        bill_to_address=customer.address or '',
                        bill_to_email=customer.email or ''
                    )
                    
                    # Create transport invoice
                    transport_invoice = TransportInvoice.objects.create(
                        grouped_invoice=grouped_invoice,
                        billing_type='consolidated'
                    )
                    
                    # Add trips to invoice
                    trips = TransportTrip.objects.filter(
                        id__in=trip_ids, 
                        user=request.user,
                        status='delivered'
                    )
                    transport_invoice.trips.set(trips)
                    transport_invoice.save()
                    
                    # Update trip status to completed
                    trips.update(status='completed')
                    
                    # Update grouped invoice total
                    grouped_invoice.recalculate_total_amount()
                    
                    messages.success(request, f'Invoice {grouped_invoice.invoice_number} created successfully!')
                    return redirect('accounts:transport_invoices')
                    
            except Exception as e:
                messages.error(request, f'Error creating invoice: {str(e)}')
        else:
            messages.error(request, 'Please select trips and customer.')
    
    # Get delivered trips for invoice creation
    delivered_trips = TransportTrip.objects.filter(
        user=request.user,
        status='delivered'
    ).select_related('customer', 'driver', 'vehicle')
    
    customer_user_ids = get_customer_user_ids(request.user)
    customers = Customer.objects.filter(user__in=customer_user_ids)
    
    context = {
        'delivered_trips': delivered_trips,
        'customers': customers,
    }
    
    return render(request, 'accounts/transport/create_invoice.html', context)
