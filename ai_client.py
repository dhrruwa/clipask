"""
ai_client.py - sends your question to an AI service and returns the answer.

What this module does, in simple words:
    Each AI company (OpenAI, Anthropic, Google) runs a web address that
    accepts a question and replies with an answer. Talking to it is just
    an HTTPS request, like a browser loading a page, made with the popular
    `requests` library. The three companies want the question packed in
    slightly different shapes, so for each one there is:

        a "request builder"   -> packs the question the way that service expects
        an "answer extractor" -> pulls the answer text out of the reply

    The one function the rest of the app uses is ask(). It either returns
    the answer text or raises AIError with a message written for a human,
    which app.py shows in the popup.

Important: ask() waits for the network, which can take seconds. It must
be called from a background thread, never the main thread, or the whole
menu bar app would freeze while waiting (app.py does this for you).
"""

import time
from dataclasses import dataclass

import requests

# Stop waiting after this many seconds. (Technically `requests` counts
# seconds of *silence* from the server, but these services send the whole
# answer at once when it's ready, so in practice it's the total wait.)
TIMEOUT_SECONDS = 20

# AI services sometimes reply "too busy, try again" (HTTP 503, or 529 for
# Anthropic). That usually passes within seconds, so ClipAsk quietly tries
# again: after 1 second, then after 3 more. Only then does it show the error.
OVERLOADED_RETRY_WAITS = (1, 3)
_OVERLOADED_STATUSES = {500, 502, 503, 504, 529}

# The longest answer we ask Anthropic for, in "tokens" (roughly ¾ of a
# word each). Anthropic requires this number; the others have defaults.
MAX_ANSWER_TOKENS = 1024


@dataclass(frozen=True)
class ProviderInfo:
    label: str  # Name shown in the menu
    default_model: str  # Model used until you choose another one
    key_url: str  # Web page where you can create an API key


# The providers ClipAsk knows how to talk to. The keys ("openai", ...) are
# internal names, also used to label the API keys saved in the Keychain.
# Model names change over time; you can type any model in the menu.
PROVIDERS = {
    "openai": ProviderInfo(
        label="OpenAI",
        default_model="gpt-5.4-mini",
        key_url="https://platform.openai.com/api-keys",
    ),
    "anthropic": ProviderInfo(
        label="Anthropic (Claude)",
        default_model="claude-sonnet-5-5",
        key_url="https://console.anthropic.com/settings/keys",
    ),
    "gemini": ProviderInfo(
        label="Google Gemini",
        default_model="gemini-3.6-flash",
        key_url="https://aistudio.google.com/apikey",
    ),
}


class AIError(Exception):
    """Something went wrong. The message is meant to be shown to the user."""


# ---------------------------------------------------------------------------
# The main function
# ---------------------------------------------------------------------------


def ask(provider, model, api_key, question, system_prompt=""):
    """
    Send `question` to the AI and return its answer as text.

    provider      - one of the keys of PROVIDERS, e.g. "openai"
    model         - model name, e.g. "gpt-5.4-mini"
    api_key       - your secret key for that provider
    question      - the text from the clipboard
    system_prompt - optional extra instructions ("" means none)

    Raises AIError with a friendly message if anything goes wrong.
    """
    if provider not in PROVIDERS:
        raise AIError(f"Unknown AI provider: {provider!r}")
    label = PROVIDERS[provider].label
    build_request, extract_answer = _PROVIDER_FUNCTIONS[provider]
    url, headers, body = build_request(model.strip(), api_key, question, system_prompt.strip())

    # Step 1: send the request. If the service says it's overloaded,
    # wait a moment and try again, a few times, before giving up.
    for attempt in range(1 + len(OVERLOADED_RETRY_WAITS)):
        response = _send(label, url, headers, body)
        if response.status_code not in _OVERLOADED_STATUSES or attempt == len(OVERLOADED_RETRY_WAITS):
            break
        time.sleep(OVERLOADED_RETRY_WAITS[attempt])

    # Step 2: we got a reply. Anything other than HTTP 200 means "error".
    try:
        data = response.json()
    except ValueError:  # the reply wasn't JSON (e.g. an HTML error page)
        data = None
    if response.status_code != 200:
        raise AIError(_describe_http_error(label, model, response, data))

    # Step 3: dig the answer text out of the reply.
    try:
        answer = extract_answer(data)
    except (KeyError, IndexError, TypeError, AttributeError):
        raise AIError(f"{label} sent a reply ClipAsk didn't understand.") from None
    if not answer or not answer.strip():
        raise AIError(f"{label} returned an empty answer. Try asking again.")
    return answer.strip()


def _send(label, url, headers, body):
    """Send one request. Raises AIError if no reply arrives at all."""
    try:
        return requests.post(url, headers=headers, json=body, timeout=TIMEOUT_SECONDS)
    except requests.exceptions.Timeout:
        raise AIError(
            f"{label} didn't answer within {TIMEOUT_SECONDS} seconds.\n\n"
            "Try again, ask a shorter question, or choose a faster model."
        ) from None
    except requests.exceptions.SSLError as error:
        raise AIError(f"The secure connection to {label} failed.\n\nDetails: {error}") from None
    except requests.exceptions.ConnectionError:
        raise AIError(
            f"Couldn't connect to {label}.\n\nCheck your internet connection and try again."
        ) from None
    except requests.exceptions.RequestException as error:
        raise AIError(f"Network problem while talking to {label}.\n\nDetails: {error}") from None


# ---------------------------------------------------------------------------
# OpenAI  (Chat Completions API)
# ---------------------------------------------------------------------------


def _openai_request(model, api_key, question, system_prompt):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": question})
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"}
    body = {"model": model, "messages": messages}
    return url, headers, body


def _openai_answer(data):
    message = data["choices"][0]["message"]
    # If the model declines to answer, the reason is in "refusal".
    return message.get("content") or message.get("refusal")


# ---------------------------------------------------------------------------
# Anthropic  (Messages API)
# ---------------------------------------------------------------------------


def _anthropic_request(model, api_key, question, system_prompt):
    url = "https://api.anthropic.com/v1/messages"
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    body = {
        "model": model,
        "max_tokens": MAX_ANSWER_TOKENS,
        "messages": [{"role": "user", "content": question}],
    }
    if system_prompt:
        body["system"] = system_prompt
    return url, headers, body


def _anthropic_answer(data):
    # The answer comes as a list of "content blocks"; we join the text ones.
    text = "".join(block.get("text", "") for block in data["content"] if block.get("type") == "text")
    if text and data.get("stop_reason") == "max_tokens":
        text += "\n\n[Answer cut off because it reached the length limit.]"
    return text


# ---------------------------------------------------------------------------
# Google Gemini  (generateContent API)
# ---------------------------------------------------------------------------


def _gemini_request(model, api_key, question, system_prompt):
    # Google's docs sometimes write models as "models/gemini-..."; accept both.
    if model.startswith("models/"):
        model = model[len("models/"):]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"x-goog-api-key": api_key}
    body = {"contents": [{"role": "user", "parts": [{"text": question}]}]}
    if system_prompt:
        body["systemInstruction"] = {"parts": [{"text": system_prompt}]}
    return url, headers, body


def _gemini_answer(data):
    candidates = data.get("candidates") or []
    if not candidates:
        # Gemini sends no answer at all if it blocked the question.
        reason = (data.get("promptFeedback") or {}).get("blockReason")
        if reason:
            raise AIError(f"Google Gemini refused to answer this question (reason: {reason}).")
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    # Skip "thought" parts (the model's private reasoning), keep the answer.
    return "".join(part.get("text", "") for part in parts if not part.get("thought"))


# Which builder/extractor pair belongs to which provider.
_PROVIDER_FUNCTIONS = {
    "openai": (_openai_request, _openai_answer),
    "anthropic": (_anthropic_request, _anthropic_answer),
    "gemini": (_gemini_request, _gemini_answer),
}


# ---------------------------------------------------------------------------
# Turning HTTP errors into helpful messages
# ---------------------------------------------------------------------------


def _describe_http_error(label, model, response, data):
    """Build a human-friendly explanation of an error reply."""
    status = response.status_code
    details = _error_details(response, data)

    if status in (401, 403) or "api key" in details.lower():
        hint = "Your API key was rejected. Set a new one from the ClipAsk menu."
    elif status == 404:
        hint = f"The model \"{model}\" wasn't found. Check the model name in the ClipAsk menu."
    elif status == 429:
        hint = "Too many requests, or your account is out of credit. Wait a moment, or check your plan/billing."
    elif status >= 500:
        tries = 1 + len(OVERLOADED_RETRY_WAITS)
        hint = (
            f"{label} is overloaded or having problems right now (ClipAsk tried {tries} times). "
            "Try again in a minute, or choose a different model in the ClipAsk menu."
        )
    else:
        hint = f"{label} rejected the request."

    return f"{label} returned an error (HTTP {status}).\n\n{hint}\n\nDetails: {details}"


def _error_details(response, data):
    """Find the error message inside the reply (all three use {"error": {"message": ...}})."""
    if isinstance(data, list) and data:  # Gemini sometimes wraps errors in a list
        data = data[0]
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if isinstance(error, str) and error:
            return error
    text = (response.text or "").strip()
    return text[:500] if text else (response.reason or "no details given")
