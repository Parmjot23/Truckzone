# api/transport_serializers.py
from rest_framework import serializers
from rest_framework.fields import HiddenField, CurrentUserDefault
from accounts.models import (
    TransportProfile, TransportCustomer, TransportVehicle, 
    TransportDriver, TransportTrip, TransportInvoice,
    Customer, GroupedInvoice
)

class TransportProfileSerializer(serializers.ModelSerializer):
    user = HiddenField(default=CurrentUserDefault())
    
    class Meta:
        model = TransportProfile
        fields = '__all__'

class TransportCustomerSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_email = serializers.CharField(source='customer.email', read_only=True)
    
    class Meta:
        model = TransportCustomer
        fields = '__all__'

class TransportVehicleSerializer(serializers.ModelSerializer):
    user = HiddenField(default=CurrentUserDefault())
    
    class Meta:
        model = TransportVehicle
        fields = '__all__'

class TransportDriverSerializer(serializers.ModelSerializer):
    user = HiddenField(default=CurrentUserDefault())
    full_name = serializers.CharField(read_only=True)
    
    class Meta:
        model = TransportDriver
        fields = '__all__'

class TransportTripSerializer(serializers.ModelSerializer):
    user = HiddenField(default=CurrentUserDefault())
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    driver_name = serializers.CharField(source='driver.full_name', read_only=True)
    vehicle_info = serializers.CharField(source='vehicle.__str__', read_only=True)
    total_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    
    class Meta:
        model = TransportTrip
        fields = '__all__'

class TransportInvoiceSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source='grouped_invoice.invoice_number', read_only=True)
    customer_name = serializers.CharField(source='grouped_invoice.customer.name', read_only=True)
    invoice_date = serializers.DateField(source='grouped_invoice.date', read_only=True)
    
    class Meta:
        model = TransportInvoice
        fields = '__all__'

# Enhanced versions of existing serializers with transport data
class EnhancedCustomerSerializer(serializers.ModelSerializer):
    user = HiddenField(default=CurrentUserDefault())
    transport_data = TransportCustomerSerializer(read_only=True, allow_null=True)
    
    class Meta:
        model = Customer
        fields = '__all__'

class EnhancedGroupedInvoiceSerializer(serializers.ModelSerializer):
    user = HiddenField(default=CurrentUserDefault())
    transport_data = TransportInvoiceSerializer(read_only=True, allow_null=True)
    
    class Meta:
        model = GroupedInvoice
        fields = '__all__'