from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import reverse
from django.utils.http import urlencode

def subscription_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, "Please log in to access this page.")
            return redirect('accounts:login')

        return view_func(request, *args, **kwargs)
    return _wrapped_view


def customer_login_required(view_func):
    """Ensure the request is performed by an authenticated customer portal user."""

    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        customer = getattr(request.user, "customer_portal", None)
        if request.user.is_authenticated and customer:
            return view_func(request, *args, **kwargs)

        if request.user.is_authenticated:
            messages.error(
                request,
                "Please sign in using a customer account to continue.",
            )
            return redirect("accounts:home")

        login_url = reverse("accounts:login")
        redirect_url = f"{login_url}?{urlencode({'next': request.get_full_path()})}"
        return redirect(redirect_url)

    return _wrapped_view


def supplier_login_required(view_func):
    """Ensure only linked supplier accounts can access supplier portal views."""

    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        supplier = getattr(request.user, "supplier_portal", None)
        if request.user.is_authenticated and supplier:
            return view_func(request, *args, **kwargs)

        if request.user.is_authenticated:
            messages.error(
                request,
                "Please sign in using your supplier credentials to continue.",
            )
            return redirect("accounts:home")

        login_url = reverse("accounts:login")
        redirect_url = f"{login_url}?{urlencode({'next': request.get_full_path()})}"
        return redirect(redirect_url)

    return _wrapped_view


def accountant_login_required(view_func):
    """Ensure only linked accountant accounts can access accountant portal views."""

    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        accountant_profile = getattr(request.user, "accountant_portal", None)
        if request.user.is_authenticated and accountant_profile:
            return view_func(request, *args, **kwargs)

        if request.user.is_authenticated:
            messages.error(
                request,
                "Please sign in using your accountant portal credentials to continue.",
            )
            return redirect("accounts:home")

        login_url = reverse("accounts:accountant_portal_login")
        redirect_url = f"{login_url}?{urlencode({'next': request.get_full_path()})}"
        return redirect(redirect_url)

    return _wrapped_view


def activation_required(view_func):
    """
    Decorator to ensure that the user has activated their account.
    Redirects to 'activation_required' page if not activated.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            # Redirect to login page if not authenticated
            return redirect('accounts:login')  # Update with your login URL name
        if not request.user.profile.activation_link_clicked:
            messages.warning(request, "You need to activate your account to access this feature.")
            return redirect('accounts:activation_required')
        return view_func(request, *args, **kwargs)
    return _wrapped_view
