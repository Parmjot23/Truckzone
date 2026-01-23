import json
import logging
from decimal import Decimal
from datetime import timedelta

from django.contrib.auth import authenticate, login
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import (
    Sum,
    Value,
    F,
    OuterRef,
    Subquery,
    Case,
    When,
    DecimalField,
    ExpressionWrapper,
)
from django.db.models.functions import Coalesce, TruncMonth, Cast
from django.contrib.auth.decorators import login_required

from .models import PendingInvoice, Payment, MechExpenseItem, TERM_CHOICES, CustomerCreditItem

logger = logging.getLogger(__name__)

@csrf_exempt  # For development only; consider proper CSRF handling/token authentication in production.
def api_login(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            username = data.get('username')
            password = data.get('password')
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                logger.info("User %s logged in successfully.", username)
                return JsonResponse({'success': True, 'message': 'Logged in successfully'})
            else:
                logger.warning("Login failed for username: %s", username)
                return JsonResponse({'success': False, 'message': 'Invalid credentials'}, status=400)
        except Exception as e:
            logger.exception("Exception during login:")
            return JsonResponse({'success': False, 'message': str(e)}, status=400)
    return JsonResponse({'error': 'POST method required'}, status=405)

@login_required
def api_dashboard(request):
    try:
        logger.info("Accessing dashboard for user: %s", request.user)
        profile = request.user.profile
        term_days = TERM_CHOICES.get(profile.term, 30)
        today = timezone.now().date()

        amount_field = DecimalField(max_digits=10, decimal_places=2)
        credit_amount_expr = Case(
            When(customer_credit__tax_included=True, then=Cast('amount', amount_field)),
            default=ExpressionWrapper(
                Cast('amount', amount_field) + Cast('tax_paid', amount_field),
                output_field=amount_field,
            ),
            output_field=amount_field,
        )
        credit_total = CustomerCreditItem.objects.filter(
            source_invoice=OuterRef('grouped_invoice_id')
        ).values('source_invoice').annotate(
            total=Coalesce(
                Sum(credit_amount_expr),
                Value(Decimal('0.00')),
                output_field=amount_field,
            )
        ).values('total')

        pending_invoices_qs = PendingInvoice.objects.filter(
            is_paid=False,
            grouped_invoice__user=request.user
        ).annotate(
            total_paid=Coalesce(
                Sum('grouped_invoice__payments__amount'),
                Value(Decimal('0.00')),
            ),
            credit_total=Coalesce(
                Subquery(credit_total, output_field=amount_field),
                Value(Decimal('0.00')),
                output_field=amount_field,
            ),
            balance_due=ExpressionWrapper(
                F('grouped_invoice__total_amount') - F('total_paid') - F('credit_total'),
                output_field=amount_field,
            )
        )
        total_pending_balance = pending_invoices_qs.aggregate(total=Sum('balance_due'))['total'] or Decimal('0.00')

        if term_days > 0:
            overdue_invoices_qs = pending_invoices_qs.filter(
                grouped_invoice__date__lt=(today - timedelta(days=term_days))
            )
            overdue_total_balance = overdue_invoices_qs.aggregate(total=Sum('balance_due'))['total'] or Decimal('0.00')
        else:
            overdue_total_balance = Decimal('0.00')

        income_qs = Payment.objects.filter(invoice__user=request.user)
        expense_qs = MechExpenseItem.objects.filter(mech_expense__user=request.user)
        income_total = income_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        expense_total = expense_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        monthly_income = list(
            income_qs.annotate(month=TruncMonth('date'))
            .values('month')
            .annotate(total=Sum('amount'))
            .order_by('month')
        )
        monthly_expenses = list(
            expense_qs.annotate(month=TruncMonth('mech_expense__date'))
            .values('month')
            .annotate(total=Sum('amount'))
            .order_by('month')
        )

        dashboard_data = {
            'total_pending_balance': str(total_pending_balance),
            'overdue_total_balance': str(overdue_total_balance),
            'income_total': str(income_total),
            'expense_total': str(expense_total),
            'monthly_income': monthly_income,
            'monthly_expenses': monthly_expenses,
            'completion_percentage': profile.profile_completion(),
        }
        logger.info("Dashboard data for user %s: %s", request.user, dashboard_data)
        return JsonResponse(dashboard_data, encoder=DjangoJSONEncoder)
    except Exception as e:
        logger.exception("Error in dashboard endpoint:")
        return JsonResponse({'error': 'Internal server error', 'message': str(e)}, status=500)
