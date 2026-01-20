# accounts/transport_models.py
from django.db import models
from django.contrib.auth.models import User
from decimal import Decimal

# Transport-specific models for smart-invoices

class TransportProfile(models.Model):
    """Profile for transport companies using smart-invoices"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='transport_profile')
    company_name = models.CharField(max_length=200)
    dot_number = models.CharField(max_length=50, blank=True, null=True, help_text="DOT Number")
    mc_number = models.CharField(max_length=50, blank=True, null=True, help_text="MC Number")
    scac_code = models.CharField(max_length=10, blank=True, null=True, help_text="SCAC Code")
    operating_authority = models.CharField(max_length=100, blank=True, null=True)
    insurance_company = models.CharField(max_length=200, blank=True, null=True)
    insurance_policy = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.company_name} - {self.user.username}"

class TransportCustomer(models.Model):
    """Enhanced customer model for transport operations"""
    # Link to original customer
    customer = models.OneToOneField('Customer', on_delete=models.CASCADE, related_name='transport_data')
    
    # Transport-specific fields
    customer_type = models.CharField(max_length=20, choices=[
        ('shipper', 'Shipper'),
        ('consignee', 'Consignee'),
        ('broker', 'Broker'),
        ('both', 'Shipper/Consignee')
    ], default='shipper')
    
    # Additional contact information
    dispatch_phone = models.CharField(max_length=20, blank=True, null=True)
    dispatch_email = models.EmailField(blank=True, null=True)
    billing_contact = models.CharField(max_length=100, blank=True, null=True)
    
    # Business details
    duns_number = models.CharField(max_length=20, blank=True, null=True)
    freight_class = models.CharField(max_length=10, blank=True, null=True)
    special_instructions = models.TextField(blank=True, null=True)
    
    # Payment terms
    payment_terms_days = models.IntegerField(default=30)
    credit_limit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Transport: {self.customer.name}"

class TransportVehicle(models.Model):
    """Vehicle information for transport operations"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transport_vehicles')
    
    # Vehicle identification
    unit_number = models.CharField(max_length=50)
    vin = models.CharField(max_length=17, blank=True, null=True, help_text="Vehicle Identification Number")
    make = models.CharField(max_length=50)
    model = models.CharField(max_length=50)
    year = models.IntegerField()
    
    # Vehicle specifications
    vehicle_type = models.CharField(max_length=30, choices=[
        ('truck', 'Truck'),
        ('trailer', 'Trailer'),
        ('van', 'Van'),
        ('flatbed', 'Flatbed'),
        ('tanker', 'Tanker'),
        ('refrigerated', 'Refrigerated'),
    ])
    
    # Capacity and specifications
    max_weight = models.DecimalField(max_digits=10, decimal_places=2, help_text="Maximum weight in lbs")
    max_length = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True, help_text="Length in feet")
    max_width = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True, help_text="Width in feet")
    max_height = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True, help_text="Height in feet")
    
    # Registration and insurance
    license_plate = models.CharField(max_length=20, blank=True, null=True)
    registration_state = models.CharField(max_length=2, blank=True, null=True)
    insurance_policy = models.CharField(max_length=100, blank=True, null=True)
    
    # Status
    status = models.CharField(max_length=20, choices=[
        ('active', 'Active'),
        ('maintenance', 'In Maintenance'),
        ('out_of_service', 'Out of Service'),
        ('retired', 'Retired')
    ], default='active')
    
    # Tracking
    current_location = models.CharField(max_length=200, blank=True, null=True)
    last_maintenance = models.DateField(blank=True, null=True)
    next_maintenance = models.DateField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['user', 'unit_number']
    
    def __str__(self):
        return f"{self.unit_number} - {self.make} {self.model}"

class TransportDriver(models.Model):
    """Driver information for transport operations"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transport_drivers')
    
    # Basic information
    employee_id = models.CharField(max_length=50, blank=True, null=True)
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField()
    
    # License information
    license_number = models.CharField(max_length=50)
    license_state = models.CharField(max_length=2)
    license_class = models.CharField(max_length=10, default='CDL-A')
    license_expiry = models.DateField()
    
    # Employment details
    hire_date = models.DateField()
    employment_status = models.CharField(max_length=20, choices=[
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('terminated', 'Terminated'),
        ('on_leave', 'On Leave')
    ], default='active')
    
    # Pay information
    pay_type = models.CharField(max_length=20, choices=[
        ('per_mile', 'Per Mile'),
        ('percentage', 'Percentage'),
        ('hourly', 'Hourly'),
        ('salary', 'Salary'),
        ('per_load', 'Per Load')
    ], default='per_mile')
    pay_rate = models.DecimalField(max_digits=8, decimal_places=4, help_text="Rate based on pay type")
    
    # Medical and certifications
    medical_expiry = models.DateField(blank=True, null=True)
    drug_test_date = models.DateField(blank=True, null=True)
    background_check_date = models.DateField(blank=True, null=True)
    
    # Emergency contact
    emergency_contact_name = models.CharField(max_length=100, blank=True, null=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['user', 'employee_id']
    
    def __str__(self):
        return f"{self.first_name} {self.last_name}"
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

class TransportTrip(models.Model):
    """Trip/Load information for transport operations"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transport_trips')
    
    # Trip identification
    trip_number = models.CharField(max_length=50, unique=True)
    load_number = models.CharField(max_length=50, blank=True, null=True)
    
    # Relationships
    customer = models.ForeignKey('Customer', on_delete=models.CASCADE, related_name='transport_trips')
    driver = models.ForeignKey(TransportDriver, on_delete=models.SET_NULL, null=True, blank=True)
    vehicle = models.ForeignKey(TransportVehicle, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Trip details
    origin_address = models.TextField()
    origin_city = models.CharField(max_length=100)
    origin_state = models.CharField(max_length=2)
    origin_zip = models.CharField(max_length=10)
    
    destination_address = models.TextField()
    destination_city = models.CharField(max_length=100)
    destination_state = models.CharField(max_length=2)
    destination_zip = models.CharField(max_length=10)
    
    # Scheduling
    pickup_date = models.DateTimeField()
    delivery_date = models.DateTimeField()
    actual_pickup = models.DateTimeField(blank=True, null=True)
    actual_delivery = models.DateTimeField(blank=True, null=True)
    
    # Load information
    commodity = models.CharField(max_length=200)
    weight = models.DecimalField(max_digits=10, decimal_places=2, help_text="Weight in lbs")
    pieces = models.IntegerField(default=1)
    freight_class = models.CharField(max_length=10, blank=True, null=True)
    
    # Financial
    total_rate = models.DecimalField(max_digits=10, decimal_places=2)
    fuel_surcharge = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    accessorial_charges = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    
    # Status tracking
    status = models.CharField(max_length=20, choices=[
        ('dispatched', 'Dispatched'),
        ('en_route_pickup', 'En Route to Pickup'),
        ('at_pickup', 'At Pickup'),
        ('loaded', 'Loaded'),
        ('en_route_delivery', 'En Route to Delivery'),
        ('at_delivery', 'At Delivery'),
        ('delivered', 'Delivered'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], default='dispatched')
    
    # Distance and time
    total_miles = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    driving_hours = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    
    # Reference numbers
    bol_number = models.CharField(max_length=50, blank=True, null=True, help_text="Bill of Lading")
    po_number = models.CharField(max_length=50, blank=True, null=True, help_text="Purchase Order")
    pro_number = models.CharField(max_length=50, blank=True, null=True, help_text="Progressive Number")
    
    # Notes
    special_instructions = models.TextField(blank=True, null=True)
    driver_notes = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Trip {self.trip_number} - {self.customer.name}"
    
    @property
    def total_amount(self):
        return self.total_rate + self.fuel_surcharge + self.accessorial_charges

class TransportInvoice(models.Model):
    """Enhanced invoice model for transport operations"""
    # Link to original grouped invoice
    grouped_invoice = models.OneToOneField('GroupedInvoice', on_delete=models.CASCADE, related_name='transport_data')
    
    # Transport-specific invoice fields
    trips = models.ManyToManyField(TransportTrip, related_name='invoices')
    
    # Billing details
    billing_type = models.CharField(max_length=20, choices=[
        ('per_load', 'Per Load'),
        ('consolidated', 'Consolidated'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly')
    ], default='per_load')
    
    # Load summary
    total_loads = models.IntegerField(default=0, editable=False)
    total_miles = models.DecimalField(max_digits=10, decimal_places=2, default=0, editable=False)
    total_weight = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    
    # Rate breakdown
    line_haul = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fuel_surcharge = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    accessorial_total = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def save(self, *args, **kwargs):
        # Auto-calculate totals
        if self.pk:
            trips = self.trips.all()
            self.total_loads = trips.count()
            self.total_miles = sum(trip.total_miles or 0 for trip in trips)
            self.total_weight = sum(trip.weight or 0 for trip in trips)
            self.line_haul = sum(trip.total_rate or 0 for trip in trips)
            self.fuel_surcharge = sum(trip.fuel_surcharge or 0 for trip in trips)
            self.accessorial_total = sum(trip.accessorial_charges or 0 for trip in trips)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"Transport Invoice: {self.grouped_invoice.invoice_number}"