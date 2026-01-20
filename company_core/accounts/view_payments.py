import stripe, logging
from decimal import Decimal

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required

from .models import GroupedInvoice     # UserStripeAccount & Profile are accessed through request.user

logger = logging.getLogger(__name__)
stripe.api_key = settings.STRIPE_SECRET_KEY

# --------------------------------------------------
# helpers
# --------------------------------------------------
CORNWALL_ADDRESS = {
    "line1":       "112 Cornwall St",
    "city":        "Cornwall",
    "state":       "ON",
    "postal_code": "K6H5J9",
    "country":     "CA",
}
READER_SERIAL   = "WSC513212017387"
READER_LABEL    = "testing"


def _ensure_location(user, acct_id) -> str:
    """Return a Location‑ID living on the connected account."""
    profile = user.profile
    if profile.stripe_terminal_location_id:
        return profile.stripe_terminal_location_id

    # Try to find an *existing* Location with the same display name
    locs = stripe.terminal.Location.list(limit=100, stripe_account=acct_id).data
    for loc in locs:
        if loc.address.line1 == CORNWALL_ADDRESS["line1"]:
            profile.stripe_terminal_location_id = loc.id
            profile.save(update_fields=["stripe_terminal_location_id"])
            return loc.id

    # Otherwise create it
    loc = stripe.terminal.Location.create(
        display_name="112 Cornwall – Shop POS",
        address=CORNWALL_ADDRESS,
        stripe_account=acct_id,
    )
    profile.stripe_terminal_location_id = loc.id
    profile.save(update_fields=["stripe_terminal_location_id"])
    return loc.id


def _ensure_reader(acct_id: str, location_id: str) -> None:
    """
    Make sure the WisePOS E reader is linked to our Location.
    We **do not** try to register it by API because WisePOS E requires
    the on‑device registration‑code flow.
    """
    readers = stripe.terminal.Reader.list(
        limit=100,
        stripe_account=acct_id
    ).data

    for r in readers:
        if r.serial_number == READER_SERIAL:
            # Reader exists – move it to the right Location if needed
            if r.location != location_id:
                stripe.terminal.Reader.update(
                    r.id,
                    location=location_id,
                    stripe_account=acct_id,
                )
            return

    # Not found → tell the caller so they can show a nice message
    raise stripe.error.InvalidRequestError(
        message=(
            "Reader WSC 513212017387 is not registered on this account. "
            "Put the device in pairing mode, grab the 3‑word code from "
            "its screen, and register it in the Dashboard "
            "or with the API using registration_code."
        ),
        param="registration_code",
    )


# --------------------------------------------------
# views
# --------------------------------------------------
@csrf_exempt
@require_POST
@login_required
def create_connection_token(request):
    user     = request.user
    acct_id  = getattr(user.userstripeaccount, "stripe_account_id", None)
    if not acct_id:
        return JsonResponse({"error": "No Stripe connected account."}, status=400)

    try:
        # make sure Location + Reader exist on the connected account
        location_id = _ensure_location(user, acct_id)
        _ensure_reader(acct_id, location_id)

        token = stripe.terminal.ConnectionToken.create(
            location       = location_id,
            stripe_account = acct_id,
        )
        return JsonResponse({"secret": token.secret, "location": location_id})
    except stripe.error.StripeError as e:
        logger.exception("Stripe error")
        return JsonResponse({"error": e.user_message or str(e)}, status=500)


@csrf_exempt
@require_POST
@login_required
def create_terminal_payment_intent(request, invoice_id):
    user     = request.user
    acct_id  = getattr(user.userstripeaccount, "stripe_account_id", None)
    if not acct_id:
        return JsonResponse({"error": "No Stripe connected account."}, status=400)

    invoice  = get_object_or_404(GroupedInvoice, pk=invoice_id, user=user)
    amount_cents = int(Decimal(invoice.balance_due() or 0) * 100)
    if amount_cents <= 0:
        return JsonResponse({"error": "Invoice balance must be > 0"}, status=400)

    try:
        # direct charge – created *on* the connected account
        pi = stripe.PaymentIntent.create(
            amount               = amount_cents,
            currency             = "cad",
            payment_method_types = ["card_present"],
            capture_method       = "automatic",
            metadata             = {"invoice_id": str(invoice.pk)},
            stripe_account       = acct_id,
            # application_fee_amount = int(amount_cents * 0.02),  # optional platform fee
        )
        return JsonResponse({
         "client_secret":      pi.client_secret,
         "payment_intent_id":  pi.id,
    })
    except stripe.error.StripeError as e:
        logger.exception("Stripe error creating PaymentIntent")
        return JsonResponse({"error": e.user_message or str(e)}, status=500)


from django.shortcuts import render           # add this import
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

@csrf_exempt
@login_required
def register_reader(request):
    """
    GET  → show the 'Register Reader' page
    POST → register the WisePOS E by 3‑word code and return JSON
    """
    if request.method == "GET":
        return render(request, "terminal/register_reader.html")

    # --- POST path (Ajax) ---
    user     = request.user
    acct_id  = getattr(user.userstripeaccount, "stripe_account_id", None)
    reg_code = request.POST.get("registration_code")

    if not acct_id or not reg_code:
        return JsonResponse({"error": "Missing account or code"}, status=400)

    location_id = _ensure_location(user, acct_id)   # helper we added earlier

    try:
        reader = stripe.terminal.Reader.create(
            registration_code = reg_code,
            label             = READER_LABEL,
            location          = location_id,
            stripe_account    = acct_id,
        )
        return JsonResponse({"success": True, "reader": reader.serial_number})
    except stripe.error.StripeError as e:
        return JsonResponse({"error": e.user_message or str(e)}, status=400)

@csrf_exempt
@require_POST
@login_required
def cancel_terminal_payment_intent(request, invoice_id):
    """
    Cancels the in-flight PaymentIntent on the connected account.
    Expects POST body: payment_intent_id.
    """
    user   = request.user
    acct   = getattr(user.userstripeaccount, "stripe_account_id", None)
    pi_id  = request.POST.get("payment_intent_id")
    if not acct or not pi_id:
        return JsonResponse({"error": "Missing account or payment_intent_id"}, status=400)

    try:
        stripe.PaymentIntent.cancel(
            pi_id,
            stripe_account=acct
        )
        return JsonResponse({"canceled": True})
    except stripe.error.StripeError as e:
        return JsonResponse({"error": e.user_message or str(e)}, status=500)
