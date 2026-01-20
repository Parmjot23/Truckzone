import logging
import os
import re
import io
from functools import lru_cache

from autocorrect import Speller
from django.conf import settings
from openai import OpenAI

logger = logging.getLogger(__name__)

_BULLET_SYMBOL = "-"
_SENTENCE_ENDINGS = {".", "!", "?"}
_SPELLER = Speller(lang="en")
_BULLET_LINE_PATTERN = re.compile(r"^([ \t]*)([-•*])?\s*(.*)$")


def _normalize_setting(value):
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return value


def _correct_spelling(text):
    if not text:
        return ""
    try:
        return _SPELLER(text).strip()
    except Exception:
        return text.strip()


def _resolve_openai_setting(name):
    return _normalize_setting(getattr(settings, name, None)) or _normalize_setting(os.getenv(name))


def _resolve_portal_model_pair():
    """Use the same model settings as the public and customer portal assistants."""
    primary = (
        _resolve_openai_setting("OPENAI_CUSTOMER_MODEL")
        or _resolve_openai_setting("OPENAI_PUBLIC_MODEL")
        or "gpt-4o-mini"
    )
    fallback = (
        _resolve_openai_setting("OPENAI_CUSTOMER_FALLBACK_MODEL")
        or _resolve_openai_setting("OPENAI_PUBLIC_FALLBACK_MODEL")
        or primary
    )
    return primary, fallback


def _clean_sentence(text):
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return ""
    text = _correct_spelling(text)
    if text[0].islower():
        text = text[0].upper() + text[1:]
    if text[-1] not in _SENTENCE_ENDINGS:
        text += "."
    return text


def autocorrect_text_block(text):
    """Apply spell corrections to each line while preserving existing bullets."""
    raw_lines = str(text or "").splitlines()
    if not raw_lines:
        return ""

    corrected_lines = []
    for line in raw_lines:
        if not line.strip():
            corrected_lines.append(line)
            continue
        match = _BULLET_LINE_PATTERN.match(line)
        if not match:
            corrected_lines.append(_correct_spelling(line))
            continue
        indent, bullet_char, content = match.groups()
        if not content:
            corrected_lines.append(line)
            continue
        corrected = _correct_spelling(content)
        if bullet_char:
            corrected_lines.append(f"{indent}{bullet_char} {corrected}")
        else:
            corrected_lines.append(f"{indent}{corrected}")
    return "\n".join(corrected_lines)


def _bulletize_text(text, fallback_label):
    if not text:
        return f"{_BULLET_SYMBOL} No {fallback_label.lower()} details provided."

    def _extract_lines(raw_text):
        # Prefer user-provided line breaks; otherwise split into sentences to keep bullets readable.
        normalized = str(raw_text).replace("\r\n", "\n")
        lines = []
        for raw_line in normalized.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            stripped = stripped.lstrip("-*\u2022").strip()
            if stripped:
                lines.append(stripped)
        if len(lines) <= 1:
            sentence_chunks = [
                chunk.strip()
                for chunk in re.split(r"(?<=[.!?])\s+", normalized)
                if chunk and chunk.strip()
            ]
            if len(sentence_chunks) > 1:
                lines = sentence_chunks
        return lines

    bullets = []
    for line in _extract_lines(text):
        cleaned = line.strip()
        cleaned = _clean_sentence(cleaned)
        if cleaned:
            bullets.append(f"{_BULLET_SYMBOL} {cleaned}")

    if not bullets:
        return f"{_BULLET_SYMBOL} No {fallback_label.lower()} details provided."

    return "\n".join(bullets)


@lru_cache(maxsize=1)
def _openai_client():
    client_kwargs = {}
    api_key = _resolve_openai_setting("OPENAI_API_KEY")
    if api_key:
        client_kwargs["api_key"] = api_key
    base_url = _resolve_openai_setting("OPENAI_BASE_URL")
    if base_url:
        client_kwargs["base_url"] = base_url
    org = _resolve_openai_setting("OPENAI_ORG")
    if org:
        client_kwargs["organization"] = org
    project = _resolve_openai_setting("OPENAI_PROJECT")
    if project:
        client_kwargs["project"] = project
    return OpenAI(**client_kwargs)


def generate_dynamic_invoice_note(invoice):
    prompt = (
        f"Generate a professional and personalized note for an invoice with the following details:\n"
        f"- Invoice Number: {invoice.invoice_number}\n"
        f"- Date: {invoice.date}\n"
        f"- Total Amount: ${invoice.total_amount}\n"
        "Include a friendly reminder for timely payment and mention any special offers if applicable."
    )
    
    try:
        client = _openai_client()
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that generates personalized invoice notes."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=150,
            temperature=0.7,
        )
        dynamic_note = response.choices[0].message.content.strip()
        return dynamic_note
    except Exception as e:
        logger.error(f"Error generating dynamic note: {e}")
        return "Please ensure payment is made on time to avoid any inconvenience."

SECTION_PATTERN = re.compile(
    r"^(Cause|Correction):\s*(.*?)(?=(?:\n(?:Cause|Correction):)|\Z)",
    flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
)

def _split_cause_correction_sections(text):
    sections = {}
    for match in SECTION_PATTERN.finditer(text):
        label = match.group(1).lower()
        body = match.group(2).strip()
        sections[label] = body
    return sections

def _local_polish_result(cause, correction, reason=None):
    return {
        "cause": _bulletize_text(cause, "Cause"),
        "correction": _bulletize_text(correction, "Correction"),
        "source": "fallback",
        "note": f"AI unavailable ({reason})." if reason else "AI unavailable; used local fallback.",
    }

def refine_cause_correction(cause_text, correction_text):
    cause_clean = (cause_text or "").strip()
    correction_clean = (correction_text or "").strip()
    if not (cause_clean or correction_clean):
        raise ValueError("Provide at least a cause or correction description.")

    model, fallback_model = _resolve_portal_model_pair()

    messages = [
        {
            "role": "system",
            "content": (
                "You are a senior service writer for heavy-duty diesel and semi-truck repairs. "
                "Fix spelling or grammar issues, translate shorthand into clear shop language, "
                "and rephrase mechanic findings so fleet managers understand what was found and how it was corrected. "
                "Use precise truck terminology (powertrain, air brakes, trailers, electrical) and keep a professional tone. "
                "Organize the cause and correction into concise bullet points."
            ),
        },
        {
            "role": "user",
            "content": (
                "Mechanic notes:\n"
                "Cause:\n"
                f"{cause_clean or 'No cause provided.'}\n\n"
                "Correction:\n"
                f"{correction_clean or 'No correction provided.'}\n\n"
                "Please reply with two sections labeled 'Cause:' and 'Correction:'. "
                "Inside each section include dash-prefixed bullet lines (\"- text\") tailored to heavy-duty/semi-truck work. "
                "Each bullet should cover a single finding or action with a short elaboration: what was found, the component/system, "
                "and how it was corrected or verified. Keep the language professional and specific."
            ),
        },
    ]

    client = _openai_client()

    def _call_model(model_name):
        return client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.35,
            max_tokens=400,
        )

    last_exception = None
    for target_model in (model, fallback_model):
        try:
            response = _call_model(target_model)
            result = (response.choices[0].message.content or "").strip()
            sections = _split_cause_correction_sections(result)
            formatted_cause = _bulletize_text(
                sections.get("cause") or cause_clean or "No cause provided.", "Cause"
            )
            formatted_correction = _bulletize_text(
                sections.get("correction") or correction_clean or "No correction provided.", "Correction"
            )
            return {
                "cause": formatted_cause,
                "correction": formatted_correction,
                "source": "ai",
            }
        except Exception as exc:
            last_exception = exc
            logger.exception("Cause/correction refinement failed on model %s", target_model)
            if target_model == fallback_model:
                break
            # Try fallback before using local polish
            continue

    logger.warning("Falling back to local polish for cause/correction (%s)", last_exception)
    return _local_polish_result(cause_clean, correction_clean, reason=str(last_exception))


def transcribe_audio_and_rephrase(audio_file, target="cause"):
    """
    Transcribe mechanic audio using OpenAI Whisper and rephrase into bullet points
    suitable for the cause/correction fields.
    """
    if not audio_file:
        raise ValueError("Audio file is required for transcription.")

    target_normalized = str(target or "cause").lower()
    target_label = "Correction" if target_normalized.startswith("cor") else "Cause"

    client = _openai_client()

    try:
        file_obj = getattr(audio_file, "file", audio_file)
        filename = getattr(audio_file, "name", "audio.webm") or "audio.webm"
        try:
            file_obj.seek(0)
        except Exception:
            try:
                # Fallback for uploads that do not expose a seekable file handle
                file_obj = io.BytesIO(audio_file.read())
            except Exception as exc:  # pragma: no cover - defensive
                raise ValueError("Unable to read uploaded audio.") from exc
        if not getattr(file_obj, "name", None):
            try:
                file_obj.name = filename
            except Exception:
                pass
        whisper_model = _resolve_openai_setting("OPENAI_WHISPER_MODEL") or "whisper-1"

        # Prefer translation so non-English (especially Punjabi) audio is converted to English
        # for the cause/correction fields. Whisper translations auto-detect language, so we avoid
        # forcing a specific code that could be unsupported by the API.
        try:
            translation_response = client.audio.translations.create(
                model=whisper_model,
                file=file_obj,
                response_format="text",
            )
            transcript = (translation_response or "").strip()
        except Exception:
            logger.exception("Audio translation failed; attempting direct transcription")
            try:
                file_obj.seek(0)
            except Exception:
                logger.debug("Unable to rewind audio file; proceeding without reset")
            transcript_response = client.audio.transcriptions.create(
                model=whisper_model,
                file=file_obj,
                response_format="text",
            )
            transcript = (transcript_response or "").strip()

        if not transcript:
            logger.warning("Audio translation produced empty text; retrying with transcription")
            try:
                file_obj.seek(0)
            except Exception:
                logger.debug("Unable to rewind audio file after empty translation; proceeding")
            transcript_response = client.audio.transcriptions.create(
                model=whisper_model,
                file=file_obj,
                response_format="text",
            )
            transcript = (transcript_response or "").strip()
    except Exception as exc:
        logger.exception("Audio transcription failed")
        raise

    if not transcript:
        raise ValueError("No transcript text was produced from the audio.")

    model, fallback_model = _resolve_portal_model_pair()
    messages = [
        {
            "role": "system",
            "content": (
                "You are a senior heavy-duty diesel service writer. "
                "The mechanic is speaking; do not add any new information."
                " Translate any non-English (for example, Punjabi) transcript into clear English"
                " while keeping the mechanic's terminology for parts or components."
                " Rewrite the transcript into concise dash-prefixed bullets."
                " Keep the content factual and tied exactly to what was said."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Field: {target_label}\n"
                "Transcript:\n"
                f"{transcript}\n\n"
                "Return only English bullet lines that start with \"- \"."
                " Use the same terminology the mechanic used whenever possible."
            ),
        },
    ]

    used_model = None
    polished = ""
    for target_model in (model, fallback_model):
        try:
            response = client.chat.completions.create(
                model=target_model,
                messages=messages,
                temperature=0.2,
                max_tokens=220,
            )
            polished = (response.choices[0].message.content or "").strip()
            used_model = target_model
            break
        except Exception:
            used_model = used_model or target_model
            logger.exception("Audio rephrase failed on model %s", target_model)
            continue

    final_text = _bulletize_text(polished or transcript, target_label)

    return {
        "transcript": transcript,
        "polished": final_text,
        "raw_polished": polished,
        "model": used_model or "transcription-only",
        "target": target_normalized,
    }
