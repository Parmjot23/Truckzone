import json
import logging
import os

from django.conf import settings
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.http import require_POST
from openai import OpenAI


logger = logging.getLogger(__name__)

SITE_URL = getattr(settings, "SITE_URL", "https://www.truck-zone.ca").rstrip("/")
BUSINESS_NAME = getattr(settings, "DEFAULT_BUSINESS_NAME", "Truck Zone")
PUBLIC_URLS = {
    "home": f"{SITE_URL}/",
    "about": f"{SITE_URL}/about/",
    "contact": f"{SITE_URL}/contact/",
    "store": f"{SITE_URL}/store/",
    "store_product_list": f"{SITE_URL}/store/",
    "customer_signup": f"{SITE_URL}/store/signup/",
}
REFERENCE_LINKS_TEXT = (
    "Useful public URLs (clickable):\n"
    + "\n".join(
        f"- {label.replace('_', ' ').title()}: [{label.replace('_', ' ').title()}]({url})"
        for label, url in PUBLIC_URLS.items()
    )
)
SYSTEM_PROMPT = (
    f"You are {BUSINESS_NAME} AI, a concise public-facing assistant for {BUSINESS_NAME}, a heavy-duty truck parts supplier. "
    "Answer in clear, short sentences (2-4). "
    "Always include directions to the relevant public page when users ask how to navigate, which parts categories we stock, or how to register. "
    "Point users to the customer signup page when they ask how to register for online ordering. "
    "Offer practical fitment tips or part-lookup guidance when useful. "
    "Whenever helpful, mention one of the canonical URLs below using Markdown (e.g. '[Shop parts](https://.../store/)'). "
    "If pricing or availability is requested, invite the user to check the store or contact the parts desk for confirmation. "
    "Decline to handle sensitive personal data, legal, or medical requests. "
    f"{REFERENCE_LINKS_TEXT}"
)


def _serialize_history(raw_history, max_turns=4, max_len=800):
    """Keep the last few turns and trim overly long messages."""
    serialized = []
    if not isinstance(raw_history, list):
        return serialized

    for turn in raw_history[-max_turns:]:
        user_text = str(turn.get("user", "")).strip() if isinstance(turn, dict) else ""
        bot_text = str(turn.get("bot", "")).strip() if isinstance(turn, dict) else ""
        if user_text:
            serialized.append({"role": "user", "content": user_text[:max_len]})
        if bot_text:
            serialized.append({"role": "assistant", "content": bot_text[:max_len]})
    return serialized


@require_POST
def public_ai_chat(request):
    """
    Lightweight proxy for the public AI assistant.
    Keeps the OpenAI key server-side and limits history/length for safety.
    """
    # Ensure a CSRF cookie exists for the client making AJAX calls.
    get_token(request)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid request."}, status=400)

    user_message = (payload.get("message") or "").strip()
    history = payload.get("history") or []

    if not user_message:
        return JsonResponse({"error": "Please enter a question."}, status=400)

    raw_key = getattr(settings, "OPENAI_API_KEY", None) or os.getenv("OPENAI_API_KEY")
    api_key = raw_key.strip() if isinstance(raw_key, str) else None
    if not api_key:
        return JsonResponse({"error": "AI assistant is not configured yet."}, status=503)

    base_url = getattr(settings, "OPENAI_BASE_URL", None) or os.getenv("OPENAI_BASE_URL")
    org = getattr(settings, "OPENAI_ORG", None) or os.getenv("OPENAI_ORG")
    project = getattr(settings, "OPENAI_PROJECT", None) or os.getenv("OPENAI_PROJECT")

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url.strip()
    if org:
        client_kwargs["organization"] = org.strip()
    if project:
        client_kwargs["project"] = project.strip()

    model = (getattr(settings, "OPENAI_PUBLIC_MODEL", None) or os.getenv("OPENAI_PUBLIC_MODEL") or "gpt-4o-mini").strip()
    fallback_model = (
        getattr(settings, "OPENAI_PUBLIC_FALLBACK_MODEL", None)
        or os.getenv("OPENAI_PUBLIC_FALLBACK_MODEL")
        or "gpt-4o-mini"
    ).strip()

    client = OpenAI(**client_kwargs)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(_serialize_history(history))
    messages.append({"role": "user", "content": user_message[:1200]})

    def run_completion(model_name):
        return client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.4,
            max_tokens=320,
        )

    try:
        completion = run_completion(model)
    except Exception:
        logger.exception("Public AI chat failed on model=%s; trying fallback=%s", model, fallback_model)
        if fallback_model and fallback_model != model:
            try:
                completion = run_completion(fallback_model)
            except Exception:
                logger.exception("Public AI chat fallback also failed")
                return JsonResponse({"error": "Sorry, I could not get an answer right now."}, status=500)
        else:
            return JsonResponse({"error": "Sorry, I could not get an answer right now."}, status=500)

    reply = completion.choices[0].message.content.strip()

    return JsonResponse({"reply": reply})
