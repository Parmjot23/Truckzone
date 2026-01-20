from django.core.management.base import BaseCommand
from django.core import serializers
from accounts.models import Profile

class Command(BaseCommand):
    help = 'Load data from fixture and handle duplicates'

    def handle(self, *args, **kwargs):
        with open('data.json', 'r') as f:
            for obj in serializers.deserialize('json', f):
                profile = obj.object
                # Check if a profile with the same user_id exists
                existing_profile = Profile.objects.filter(user_id=profile.user_id).first()

                if existing_profile:
                    # If the profile already exists, update the existing one
                    self.stdout.write(self.style.WARNING(f'Duplicate user_id {profile.user_id}, updating existing record.'))
                    existing_profile.__dict__.update(profile.__dict__)  # Update existing fields
                    existing_profile.save()
                else:
                    # If no conflict, save the profile
                    profile.save()
                    self.stdout.write(self.style.SUCCESS(f'Added new profile with user_id {profile.user_id}.'))
