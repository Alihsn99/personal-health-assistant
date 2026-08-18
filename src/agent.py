"""Gemini agent for the personal health assistant, using automatic function
calling: the SDK inspects tools.py's type hints and dispatches calls itself."""

import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

from tools import get_profile, get_recent_logs, log_entry, search_research, update_profile

load_dotenv()

MODEL = "gemini-3.5-flash-lite"

SYSTEM_PROMPT = """\
You are a personal health assistant for a single user whose goal is to reason about \
the tradeoff between muscle-building/performance and longevity — e.g. higher protein \
intake and resistance training drive muscle protein synthesis but also activate mTOR/ \
IGF-1/growth-hormone signaling, while caloric restriction and fasting extend lifespan \
in model organisms but can undermine muscle-building goals.

You have tools to read/update the user's profile (stats, goals, and how they currently \
weight muscle-building vs. longevity), log daily data, and search a curated corpus of \
PubMed abstracts on this exact tension.

Rules:
- When a question involves a tradeoff or a research claim, call search_research before \
answering, and cite what you found (title + year) rather than relying on general knowledge.
- Ground recommendations in the user's actual profile (call get_profile if you haven't \
already this conversation) and their stated priority weighting between muscle-building \
and longevity — don't assume a default.
- Be explicit about uncertainty in the literature (e.g. most longevity/CR evidence is from \
model organisms, not long-term human RCTs) rather than overstating confidence.
- This is informational synthesis of research, not medical advice or diagnosis. Say so if \
the user asks something that actually needs a doctor (e.g. symptoms, medication changes).
- Be concise and direct. Skip disclaimers beyond what's warranted.
"""


def make_chat():
    """Returns (client, chat). Callers must keep `client` alive for as long as
    `chat` is used — google-genai closes its HTTP connection when the Client
    object is garbage-collected, and Chat doesn't hold its own reference."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY not set. Copy .env.example to .env and add your key "
            "(free, no card required, at https://aistudio.google.com/apikey)."
        )
    client = genai.Client(api_key=api_key)
    chat = client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            tools=[get_profile, update_profile, log_entry, get_recent_logs, search_research],
            system_instruction=SYSTEM_PROMPT,
        ),
    )
    return client, chat
