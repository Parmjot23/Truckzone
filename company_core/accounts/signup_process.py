from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.template.loader import render_to_string
from django.core.mail import EmailMessage, send_mail
from django.contrib.auth import login
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes, force_str
from .forms import SignUpForm, PaymentForm
from .models import User, Profile, GroupedInvoice, UserStripeAccount, Payment, PaidInvoice
import stripe
import logging
from django.contrib.auth import logout
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from .paid_invoice_views import send_paid_invoice_email
import decimal
from django.db import transaction
from .pdf_utils import apply_branding_defaults

logger = logging.getLogger(__name__)

def signup(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST, request.FILES)
        consent = request.POST.get('consent')
        if form.is_valid() and consent:
            user = form.save(commit=False)
            user.is_active = True  # Activate user immediately
            user.save()

            profile = user.profile
            profile.occupation = form.cleaned_data.get('occupation')
            profile.province = form.cleaned_data.get('province')
            profile.consent_given = True
            profile.consent_date = timezone.now()
            profile.consent_version = "1.0"
            profile.trial_start_date = timezone.now()
            profile.trial_end_date = timezone.now() + timedelta(days=30)
            profile.save()

            # Send activation email
            mail_subject = 'Activate Your Smart Invoices Account'
            email_context = {
                'user': user,
                'domain': settings.SITE_URL,
                'uid': urlsafe_base64_encode(force_bytes(user.pk)),
                'token': default_token_generator.make_token(user),
            }
            email_context = apply_branding_defaults(email_context)
            message = render_to_string('registration/activation_email.html', email_context)
            to_email = user.email
            email = EmailMessage(mail_subject, message, to=[to_email])
            email.content_subtype = "html"  # Send as HTML
            email.send()

            messages.success(request, "Registration successful! Please check your email to activate additional features.")

            # Login the user
            user.backend = 'django.contrib.auth.backends.ModelBackend'  # Update if using a custom backend
            login(request, user)

            # Redirect to home or dashboard
            return redirect('accounts:home')
        else:
            if not consent:
                form.add_error(None, "You must agree to the Terms and Policies to sign up.")
    else:
        form = SignUpForm()
    return render(request, 'registration/signup.html', {'form': form})


@login_required
def payment(request):
    plan_name = request.session.get('selected_plan')
    if not plan_name:
        # Redirect the user to choose a plan if none is selected
        return redirect('accounts:choose_plan')

    plan_id = settings.STRIPE_PLANS.get(plan_name)
    if not plan_id:
        messages.error(request, "Invalid plan selected.")
        return redirect('accounts:choose_plan')

    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            token = form.cleaned_data['stripe_token']
            billing_details = {
                'name': form.cleaned_data['billing_name'],
                'address': {
                    'line1': form.cleaned_data['billing_address'],
                    'city': form.cleaned_data['billing_city'],
                    'state': form.cleaned_data['billing_province'],
                    'postal_code': form.cleaned_data['billing_postal_code'],
                    'country': 'CA'  # Canada
                }
            }

            user = request.user
            try:
                stripe.api_key = settings.STRIPE_SECRET_KEY

                # Check if the user already has a Stripe customer ID
                if user.profile.stripe_customer_id:
                    # Retrieve existing customer
                    customer = stripe.Customer.retrieve(user.profile.stripe_customer_id)
                    # Update the customer's source (payment method)
                    customer.source = token
                    customer.address = billing_details['address']
                    customer.save()
                    logger.info(f'Stripe customer updated: {customer.id}')
                else:
                    # Create new customer
                    customer = stripe.Customer.create(
                        email=user.email,
                        source=token,
                        address=billing_details['address']
                    )
                    user.profile.stripe_customer_id = customer.id
                    user.profile.save()
                    logger.info(f'Stripe customer created: {customer.id}')

                # Check if the user already has a subscription
                if user.profile.stripe_subscription_id:
                    subscription = stripe.Subscription.retrieve(user.profile.stripe_subscription_id)
                    # Update subscription if necessary
                    # For now, we'll assume the subscription is correct
                    logger.info(f'Stripe subscription exists: {subscription.id}')
                else:
                    # Create new subscription
                    subscription = stripe.Subscription.create(
                        customer=customer.id,
                        items=[{'price': plan_id}],
                        expand=['latest_invoice.payment_intent'],
                    )
                    user.profile.stripe_subscription_id = subscription.id
                    user.profile.save()
                    logger.info(f'Stripe subscription created: {subscription.id}')

                messages.success(request, "Your subscription is now active.")
                # Clear the selected plan from the session
                del request.session['selected_plan']
                return redirect('accounts:home')

            except stripe.error.StripeError as e:
                logger.error(f"Stripe error: {e}")
                messages.error(request, f"An error occurred with your payment: {e.user_message}")
        else:
            messages.error(request, "Please correct the errors in the form.")
    else:
        form = PaymentForm()

    return render(request, 'registration/payment.html', {
        'plan': plan_name,
        'form': form,
        'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY
    })


def signup_thankyou(request):
    return render(request, 'registration/signupComplete.html')

@csrf_exempt
def stripe_webhook(request):
    logger.info("🚀 Webhook received")

    payload      = request.body                 # raw bytes
    sig_header   = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    endpoint_sec = settings.STRIPE_WEBHOOK_SECRET

    if not endpoint_sec:
        logger.error("❌ No STRIPE_WEBHOOK_SECRET configured")
        return JsonResponse({'status': 'config error'}, status=500)
    if not sig_header:
        logger.error("❌ Missing Stripe-Signature header")
        return JsonResponse({'status': 'missing signature'}, status=400)

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_sec)
        logger.info("✅ Verified event: %s", event["type"])
    except stripe.error.SignatureVerificationError as e:
        logger.error("❌ Invalid signature: %s", e)
        return JsonResponse({'status': 'invalid signature'}, status=400)
    except ValueError as e:
        logger.error("❌ Invalid payload: %s", e)
        return JsonResponse({'status': 'invalid payload'}, status=400)

    try:
        handle_stripe_event(event)
    except Exception:
        logger.exception("❌ Error processing Stripe event")
        return JsonResponse({'status': 'handler error'}, status=500)

    return JsonResponse({'status': 'success'}, status=200)



def handle_stripe_event(event):
    event_type = event['type']
    data = event['data']['object']

    if event_type == 'invoice.payment_succeeded':
        handle_payment_succeeded(data)
    elif event_type == 'customer.subscription.created':
        handle_subscription_created(data)
    elif event_type == 'customer.subscription.updated':
        handle_subscription_updated(data)
    elif event_type == 'customer.subscription.deleted':
        handle_subscription_deleted(data)
    elif event_type == 'checkout.session.completed':
        handle_checkout_session_completed(data)
    elif event_type == 'customer.created':
        handle_customer_created(data)
    elif event_type == 'customer.deleted':
        handle_customer_deleted(data)
    elif event_type == 'customer.subscription.trial_will_end':
        handle_trial_will_end(data)
    elif event_type == 'invoice.payment_failed':
        handle_payment_failed(data)
    # Add more event types as needed


def send_customer_email(subject, message, user_email):
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user_email],
        fail_silently=False,
    )


def handle_payment_succeeded(data):
    pass

def handle_subscription_created(data):
    pass

def handle_subscription_updated(data):
    pass

def handle_subscription_deleted(data):
    pass

import requests
try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except (ImportError, OSError):
    WEASYPRINT_AVAILABLE = False
    HTML = None
def handle_checkout_session_completed(data):
    """
    Called by stripe_webhook() for each `checkout.session.completed` event.
    Creates a Payment row idempotently, flips invoice to Paid, stores Stripe Invoice ID,
    fetches Stripe's invoice PDF or fallback receipt PDF, and emails the paid invoice.
    """
    # Only process successful payments
    if data.get("payment_status") != "paid":
        return

    # Extract identifiers
    invoice_id    = data["metadata"].get("invoice_id")
    checkout_id   = data["id"]
    amount_cents  = data["amount_total"]
    pi_id         = data.get("payment_intent")
    connected_acct= data.get("account")

    # Lookup local invoice
    invoice = GroupedInvoice.objects.filter(pk=invoice_id).first()
    if not invoice:
        logger.error("Webhook checkout %s: unknown invoice_id %s", checkout_id, invoice_id)
        return

    # Idempotent Payment creation
    if Payment.objects.filter(notes__icontains=checkout_id).exists():
        logger.info("Webhook checkout %s already processed", checkout_id)
    else:
        with transaction.atomic():
            Payment.objects.create(
                invoice=invoice,
                amount=decimal.Decimal(amount_cents) / 100,
                method="Stripe",
                notes=f"Stripe checkout {checkout_id}"
            )
            invoice.update_date_fully_paid()

            # Mark as PaidInvoice only when payments cover the invoice total.
            total_amount = invoice.total_amount or decimal.Decimal("0.00")
            total_paid = invoice.total_paid()
            if total_paid + decimal.Decimal("0.01") >= total_amount:
                PaidInvoice.objects.get_or_create(grouped_invoice=invoice)

    # Store Stripe Invoice ID from metadata if present
    stripe_invoice_id = data.get("invoice")  # present for subscription-based charges
    invoice_pdf_url   = None
    if stripe_invoice_id:
        try:
            stripe_inv = stripe.Invoice.retrieve(
                stripe_invoice_id,
                stripe_account=connected_acct
            )
            invoice_pdf_url = stripe_inv.get("invoice_pdf")
            if invoice_pdf_url:
                invoice.stripe_invoice_id = stripe_invoice_id
                invoice.save(update_fields=["stripe_invoice_id"])
        except Exception as e:
            logger.warning("Could not retrieve Stripe Invoice %s: %s", stripe_invoice_id, e)

    # Retrieve receipt_url via PaymentIntent → Charge
    receipt_url = None
    charge = None
    if pi_id:
        try:
            pi = stripe.PaymentIntent.retrieve(
                pi_id,
                stripe_account=connected_acct
            )
            charge = pi.charges.data[0] if pi.charges.data else None
            if charge:
                receipt_url = charge.receipt_url
        except Exception as e:
            logger.warning("Could not fetch PaymentIntent %s: %s", pi_id, e)

    # Fetch PDF bytes: prefer Stripe Invoice PDF, else fallback to receipt page
    stripe_pdf      = None
    stripe_pdf_name = None
    if invoice_pdf_url:
        try:
            stripe_pdf = requests.get(invoice_pdf_url).content
            stripe_pdf_name = f"stripe_invoice_{invoice.invoice_number}.pdf"
        except Exception as e:
            logger.warning("Failed to download invoice_pdf from %s: %s", invoice_pdf_url, e)
    elif receipt_url:
        try:
            html = requests.get(receipt_url).text
            if not WEASYPRINT_AVAILABLE:
                logger.warning("WeasyPrint not available, skipping PDF generation from receipt_url")
            else:
                stripe_pdf = HTML(string=html, base_url=receipt_url).write_pdf()
                stripe_pdf_name = f"stripe_receipt_{charge.id}.pdf"
        except Exception as e:
            logger.warning("Failed to generate PDF from receipt_url %s: %s", receipt_url, e)

    # Send the paid-invoice email with attachments
    send_paid_invoice_email(
        invoice,
        request=None,
        receipt_url=receipt_url,
        stripe_pdf=stripe_pdf,
        stripe_pdf_name=stripe_pdf_name
    )


def handle_customer_created(data):
    pass

def handle_customer_deleted(data):
    pass

def handle_payment_failed(data):
    pass

def handle_trial_will_end(data):
    pass


def activate(request, uidb64, token):
    # Redirect to activate_features view
    return activate_features(request, uidb64, token)

def activate_features(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        profile = user.profile
        if not profile.activation_link_clicked:
            profile.activation_link_clicked = True
            profile.activation_date = timezone.now()
            profile.save()
            messages.success(request, "Your account features have been activated!")
        else:
            messages.info(request, "Your account features are already activated.")
        return redirect('accounts:activation_complete')
    else:
        messages.error(request, "Activation link is invalid or has expired.")
        return redirect('accounts:activation_invalid')

def activation_complete(request):
    return render(request, 'registration/activation_complete.html')

def activation_invalid(request):
    return render(request, 'registration/activation_invalid.html')

def activation_require(request):
    return render(request, 'registration/activation_required.html')

@login_required
def resend_activation_email(request):
    user = request.user
    if user.profile.activation_link_clicked:
        messages.info(request, "Your account is already activated.")
        return redirect('accounts:home')

    if request.method == 'POST':
        mail_subject = 'Activate Your Smart Invoices Account'
        email_context = {
            'user': user,
            'domain': request.get_host(),
            'uid': urlsafe_base64_encode(force_bytes(user.pk)),
            'token': default_token_generator.make_token(user),
        }
        email_context = apply_branding_defaults(email_context)
        message = render_to_string('registration/activation_email.html', email_context)
        to_email = user.email
        email = EmailMessage(mail_subject, message, to=[to_email])
        email.content_subtype = "html"  # Send as HTML
        email.send()

        messages.success(request, "A new activation email has been sent to your email address.")
        return redirect('accounts:home')

    return render(request, 'registration/resend_activation.html')
