import ssl_patch
import os
from dotenv import load_dotenv

# ── 1. Load env ───────────────────────────────────────────────────────────────
load_dotenv()

api_key     = os.getenv("OPENAI_API_KEY")
api_version = os.getenv("OPENAI_API_VERSION")
api_base    = os.getenv("OPENAI_API_BASE_URL")
model       = os.getenv("OPENAI_MODEL")

print("=== ENV CHECK ===")
print(f"API_KEY     : {repr(api_key)}")
print(f"API_VERSION : {repr(api_version)}")
print(f"API_BASE    : {repr(api_base)}")
print(f"MODEL       : {repr(model)}")
print()

# ── 2. Connect ────────────────────────────────────────────────────────────────
from openai import AzureOpenAI

client = AzureOpenAI(
    api_key=api_key,
    api_version=api_version,
    azure_endpoint=api_base,
)

print("=== SENDING REQUEST ===")
resp = client.chat.completions.create(
    model=model,
    messages=[{"role": "user", "content": "say a poem"}],
    max_tokens=1000,
)

print("=== RESPONSE ===")
print(resp.choices[0].message.content)
