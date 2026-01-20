from django.shortcuts import render

def privacy_policy_view(request):
    return render(request, 'privacy/privacy_policy.html')

def terms_and_conditions_view(request):
    return render(request, 'privacy/terms_and_conditions.html')

def cookies_policy_view(request):
    return render(request, 'privacy/cookies_policy.html')
