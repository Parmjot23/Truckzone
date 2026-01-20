# api/transport_views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q, Sum, Count
from accounts.models import (
    TransportProfile, TransportCustomer, TransportVehicle, 
    TransportDriver, TransportTrip, TransportInvoice,
    Customer, GroupedInvoice
)
from accounts.utils import get_customer_user_ids
from .transport_serializers import (
    TransportProfileSerializer, TransportCustomerSerializer,
    TransportVehicleSerializer, TransportDriverSerializer,
    TransportTripSerializer, TransportInvoiceSerializer,
    EnhancedCustomerSerializer, EnhancedGroupedInvoiceSerializer
)

class TransportProfileViewSet(viewsets.ModelViewSet):
    serializer_class = TransportProfileSerializer
    
    def get_queryset(self):
        return TransportProfile.objects.filter(user=self.request.user)

class TransportCustomerViewSet(viewsets.ModelViewSet):
    serializer_class = TransportCustomerSerializer
    
    def get_queryset(self):
        customer_user_ids = get_customer_user_ids(self.request.user)
        return TransportCustomer.objects.filter(customer__user__in=customer_user_ids)

class TransportVehicleViewSet(viewsets.ModelViewSet):
    serializer_class = TransportVehicleSerializer
    
    def get_queryset(self):
        return TransportVehicle.objects.filter(user=self.request.user)
    
    @action(detail=False, methods=['get'])
    def active_vehicles(self, request):
        """Get only active vehicles"""
        vehicles = self.get_queryset().filter(status='active')
        serializer = self.get_serializer(vehicles, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def maintenance_due(self, request):
        """Get vehicles due for maintenance"""
        from datetime import date, timedelta
        next_week = date.today() + timedelta(days=7)
        vehicles = self.get_queryset().filter(
            next_maintenance__lte=next_week,
            status='active'
        )
        serializer = self.get_serializer(vehicles, many=True)
        return Response(serializer.data)

class TransportDriverViewSet(viewsets.ModelViewSet):
    serializer_class = TransportDriverSerializer
    
    def get_queryset(self):
        return TransportDriver.objects.filter(user=self.request.user)
    
    @action(detail=False, methods=['get'])
    def active_drivers(self, request):
        """Get only active drivers"""
        drivers = self.get_queryset().filter(employment_status='active')
        serializer = self.get_serializer(drivers, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def expiring_licenses(self, request):
        """Get drivers with expiring licenses"""
        from datetime import date, timedelta
        next_month = date.today() + timedelta(days=30)
        drivers = self.get_queryset().filter(
            license_expiry__lte=next_month,
            employment_status='active'
        )
        serializer = self.get_serializer(drivers, many=True)
        return Response(serializer.data)

class TransportTripViewSet(viewsets.ModelViewSet):
    serializer_class = TransportTripSerializer
    
    def get_queryset(self):
        return TransportTrip.objects.filter(user=self.request.user).select_related(
            'customer', 'driver', 'vehicle'
        )
    
    @action(detail=False, methods=['get'])
    def active_trips(self, request):
        """Get trips that are currently active (not delivered/completed/cancelled)"""
        active_statuses = ['dispatched', 'en_route_pickup', 'at_pickup', 'loaded', 'en_route_delivery', 'at_delivery']
        trips = self.get_queryset().filter(status__in=active_statuses)
        serializer = self.get_serializer(trips, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def delivered_trips(self, request):
        """Get delivered trips ready for invoicing"""
        trips = self.get_queryset().filter(status='delivered')
        serializer = self.get_serializer(trips, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def trip_summary(self, request):
        """Get trip summary statistics"""
        queryset = self.get_queryset()
        
        summary = {
            'total_trips': queryset.count(),
            'active_trips': queryset.filter(status__in=['dispatched', 'en_route_pickup', 'at_pickup', 'loaded', 'en_route_delivery', 'at_delivery']).count(),
            'delivered_trips': queryset.filter(status='delivered').count(),
            'completed_trips': queryset.filter(status='completed').count(),
            'total_revenue': queryset.aggregate(
                total=Sum('total_rate')
            )['total'] or 0,
            'total_miles': queryset.aggregate(
                total=Sum('total_miles')
            )['total'] or 0,
        }
        
        return Response(summary)
    
    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        """Update trip status with validation"""
        trip = self.get_object()
        new_status = request.data.get('status')
        
        if new_status not in dict(TransportTrip._meta.get_field('status').choices):
            return Response(
                {'error': 'Invalid status'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        trip.status = new_status
        
        # Auto-set actual times based on status
        if new_status == 'loaded' and not trip.actual_pickup:
            from django.utils import timezone
            trip.actual_pickup = timezone.now()
        elif new_status == 'delivered' and not trip.actual_delivery:
            from django.utils import timezone
            trip.actual_delivery = timezone.now()
        
        trip.save()
        serializer = self.get_serializer(trip)
        return Response(serializer.data)

class TransportInvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = TransportInvoiceSerializer
    
    def get_queryset(self):
        return TransportInvoice.objects.filter(
            grouped_invoice__user=self.request.user
        ).select_related('grouped_invoice')

# Enhanced versions of existing ViewSets
class EnhancedCustomerViewSet(viewsets.ModelViewSet):
    serializer_class = EnhancedCustomerSerializer
    
    def get_queryset(self):
        customer_user_ids = get_customer_user_ids(self.request.user)
        return Customer.objects.filter(user__in=customer_user_ids).prefetch_related('transport_data')

class EnhancedInvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = EnhancedGroupedInvoiceSerializer
    
    def get_queryset(self):
        return GroupedInvoice.objects.filter(user=self.request.user).prefetch_related('transport_data')
    
    @action(detail=False, methods=['post'])
    def create_from_trips(self, request):
        """Create invoice from selected trips"""
        trip_ids = request.data.get('trip_ids', [])
        customer_id = request.data.get('customer_id')
        
        if not trip_ids or not customer_id:
            return Response(
                {'error': 'trip_ids and customer_id are required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            from django.db import transaction
            from datetime import date
            
            with transaction.atomic():
                # Create grouped invoice
                customer_user_ids = get_customer_user_ids(request.user)
                customer = Customer.objects.get(id=customer_id, user__in=customer_user_ids)
                
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
                transport_invoice.save()  # This will calculate totals
                
                # Update grouped invoice total
                grouped_invoice.recalculate_total_amount()
                
                serializer = self.get_serializer(grouped_invoice)
                return Response(serializer.data, status=status.HTTP_201_CREATED)
                
        except Customer.DoesNotExist:
            return Response(
                {'error': 'Customer not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_400_BAD_REQUEST
            )
