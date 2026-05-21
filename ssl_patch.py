"""ssl_patch.py — must be imported before any network call."""

import os
import ssl
import urllib3
import requests
from requests.adapters import HTTPAdapter
import httpx

# ── Shared: disable SSL verification everywhere ───────────────────────────────

# Patch 1: stdlib ssl
ssl._create_default_https_context = ssl._create_unverified_context

# Patch 2: urllib3 warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Patch 3: urllib3 directly
urllib3.util.ssl_.DEFAULT_CERTS = None

# Patch 4: requests session
class NoVerifyAdapter(HTTPAdapter):
    def send(self, *args, **kwargs):
        kwargs['verify'] = False
        return super().send(*args, **kwargs)

_original_session = requests.Session
class PatchedSession(_original_session):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mount('https://', NoVerifyAdapter())
        self.verify = False

requests.Session = PatchedSession

# Patch 5: requests.get/post directly
_orig_get = requests.get
_orig_post = requests.post

def patched_get(url, **kwargs):
    kwargs['verify'] = False
    return _orig_get(url, **kwargs)

def patched_post(url, **kwargs):
    kwargs['verify'] = False
    return _orig_post(url, **kwargs)

requests.get = patched_get
requests.post = patched_post

# ── NEW: patch httpx (used by the OpenAI SDK) ─────────────────────────────────

_original_client_init = httpx.Client.__init__

def _patched_client_init(self, *args, **kwargs):
    kwargs['verify'] = False
    _original_client_init(self, *args, **kwargs)

httpx.Client.__init__ = _patched_client_init

_original_async_client_init = httpx.AsyncClient.__init__

def _patched_async_client_init(self, *args, **kwargs):
    kwargs['verify'] = False
    _original_async_client_init(self, *args, **kwargs)

httpx.AsyncClient.__init__ = _patched_async_client_init
