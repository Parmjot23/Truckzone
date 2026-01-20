from rest_framework import serializers
from rest_framework.fields import HiddenField, CurrentUserDefault
from django.contrib.auth.models import User
from accounts.models import Customer, GroupedInvoice, Payment, Note, Profile

class CustomerSerializer(serializers.ModelSerializer):
    # Automatically set the user to the current user on create/update
    user = HiddenField(default=CurrentUserDefault())
    
    class Meta:
        model = Customer
        fields = '__all__'

class GroupedInvoiceSerializer(serializers.ModelSerializer):
    user = HiddenField(default=CurrentUserDefault())
    
    class Meta:
        model = GroupedInvoice
        fields = '__all__'

class PaymentSerializer(serializers.ModelSerializer):
    # Although Payment does not have its own user field,
    # we can enforce that the related invoice belongs to the current user.
    def create(self, validated_data):
        request = self.context.get('request')
        invoice = validated_data.get('invoice')
        if invoice.user != request.user:
            raise serializers.ValidationError("You cannot add a payment to an invoice that does not belong to you.")
        return super().create(validated_data)

    class Meta:
        model = Payment
        fields = '__all__'

class NoteSerializer(serializers.ModelSerializer):
    user = HiddenField(default=CurrentUserDefault())
    
    class Meta:
        model = Note
        fields = '__all__'
