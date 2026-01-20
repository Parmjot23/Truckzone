import json
import json
import os

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core import serializers
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q


class Command(BaseCommand):
    help = "Load user-scoped data from a JSON fixture and merge it into the current database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default="data.json",
            help="Path to the exported JSON fixture.",
        )
        parser.add_argument(
            "--username",
            help="Optional override for the target username/email (merges into an existing user if found).",
        )

    def handle(self, *args, **options):
        fixture_path = options["path"]
        override_username = options.get("username")

        if not os.path.exists(fixture_path):
            self.stderr.write(self.style.ERROR(f"Fixture not found at {fixture_path}"))
            return

        try:
            with open(fixture_path, "r", encoding="utf-8") as fp:
                payload = json.load(fp)
        except json.JSONDecodeError as exc:
            self.stderr.write(self.style.ERROR(f"Invalid JSON in {fixture_path}: {exc}"))
            return

        if not isinstance(payload, list):
            self.stderr.write(self.style.ERROR("Fixture format not recognized (expected a JSON list)."))
            return

        filtered_entries, skipped_models = self._filter_known_models(payload)

        user_model = get_user_model()
        user_label = f"{user_model._meta.app_label}.{user_model._meta.model_name}"
        user_entries = [entry for entry in filtered_entries if entry.get("model") == user_label]
        other_entries = [entry for entry in filtered_entries if entry.get("model") != user_label]

        if not user_entries:
            self.stderr.write(self.style.ERROR("No user objects found in the fixture; aborting import."))
            return

        saved_users = self._save_users(user_entries, user_model, override_username)
        saved_objects, failed = self._save_objects(other_entries)

        self.stdout.write(self.style.SUCCESS(
            f"Imported {saved_users} user(s) and {saved_objects} related object(s)."
        ))
        if skipped_models:
            self.stdout.write(self.style.WARNING(
                f"Skipped models not present in this project: {', '.join(sorted(skipped_models))}"
            ))
        if failed:
            for model_name, exc in failed:
                self.stderr.write(self.style.ERROR(f"Failed to import {model_name}: {exc}"))

    def _filter_known_models(self, entries):
        filtered = []
        skipped = set()
        for entry in entries:
            model_label = entry.get("model")
            if not model_label:
                continue
            try:
                apps.get_model(model_label)
            except LookupError:
                skipped.add(model_label)
                continue
            filtered.append(entry)
        return filtered, skipped

    def _save_users(self, entries, user_model, override_username=None):
        saved = 0
        data = json.dumps(entries)
        total = len(entries)
        for idx, obj in enumerate(serializers.deserialize("json", data, ignorenonexistent=True), start=1):
            user_obj = obj.object
            if override_username:
                user_obj.username = override_username
            lookup_username = override_username or user_obj.username
            existing = user_model.objects.filter(
                Q(username__iexact=lookup_username) | Q(email__iexact=user_obj.email)
            ).first()
            if existing:
                user_obj.pk = existing.pk
                # If the target username/email already exists, skip to avoid unique violations.
                self.stdout.write(f"[users] {idx}/{total}: {user_obj.username} (skipped existing)", ending="\r")
                continue
            obj.save()
            saved += 1
            self.stdout.write(f"[users] {idx}/{total}: {user_obj.username}", ending="\r")
        if total:
            self.stdout.write("")  # newline
        return saved

    def _save_objects(self, entries):
        if not entries:
            return 0, []

        # Ensure any User natural keys referenced by other objects exist locally.
        self._ensure_users_for_natural_fks(entries)

        objects = list(serializers.deserialize("json", json.dumps(entries), ignorenonexistent=True))
        pending = objects
        saved = 0
        last_errors = []

        for _ in range(3):
            if not pending:
                break
            next_pending = []
            last_errors = []
            total = len(pending)
            for idx, obj in enumerate(pending, start=1):
                try:
                    with transaction.atomic(savepoint=True):
                        obj.save()
                    saved += 1
                    label = obj.object.__class__.__name__
                    self.stdout.write(f"[pass {attempt+1}] {idx}/{total}: {label}", ending="\r")
                except Exception as exc:
                    next_pending.append(obj)
                    last_errors.append((obj.object.__class__.__name__, exc))
            if len(next_pending) == len(pending):
                break
            pending = next_pending
            if total:
                self.stdout.write("")  # newline

        return saved, last_errors

    def _ensure_users_for_natural_fks(self, entries):
        """
        Scan fixture entries for FK/M2M relations to the auth user model that use natural keys.
        Create placeholder users for any usernames not already present so deserialization won't fail.
        """
        user_model = get_user_model()
        needed_usernames = set()

        for entry in entries:
            model_label = entry.get("model")
            if not model_label:
                continue
            try:
                model = apps.get_model(model_label)
            except LookupError:
                continue

            fields_data = entry.get("fields", {})

            # Forward FK/O2O
            for field in model._meta.fields:
                if not field.is_relation or not field.remote_field:
                    continue
                if field.remote_field.model == user_model:
                    value = fields_data.get(field.name)
                    needed_usernames.update(self._extract_usernames_from_natural(value))

            # M2M
            for m2m in model._meta.many_to_many:
                if m2m.remote_field.model != user_model:
                    continue
                value = fields_data.get(m2m.name)
                if isinstance(value, list):
                    for item in value:
                        needed_usernames.update(self._extract_usernames_from_natural(item))

        for username in needed_usernames:
            if username and not user_model.objects.filter(username__iexact=username).exists():
                user_model.objects.create_user(username=username)

    @staticmethod
    def _extract_usernames_from_natural(value):
        """
        Natural keys for auth.User serialize as a list containing the username.
        Accept single strings or single-item lists; ignore anything else.
        """
        if isinstance(value, str):
            return {value}
        if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
            return {value[0]}
        return set()
