# monitor/api_auth.py
"""
API key authentication decorator and rate-limit helper.

Usage: @require_api_key on any view that should require Bearer token auth.
After successful auth the decorator attaches:
  request.api_key  — the ApiKey model instance
  request.api_user — the User instance (api_key.user)

Rate limiting uses Django's cache with a fixed-window counter keyed by
(api_key_id, minute_bucket).  See the PerformanceConsiderations section
in the plan for known multi-process limitations.
"""
import hashlib
import functools
import time

from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone

from .models import ApiKey

_RATE_LIMIT = 60  # requests per minute


def _check_rate_limit(api_key_id: int) -> bool:
    """Return True if under limit, False if exceeded.

    Uses cache.add + cache.incr to avoid the race condition where two
    concurrent requests both read count=0 and both pass the limit check.
    """
    bucket = int(time.time() // 60)
    cache_key = f'rl:{api_key_id}:{bucket}'
    # add is a no-op if the key already exists (atomic init)
    cache.add(cache_key, 0, timeout=120)
    count = cache.incr(cache_key)
    return count <= _RATE_LIMIT


def require_api_key(view_func):
    """Decorator: validate Bearer token, enforce rate limit, set request.api_key/api_user."""

    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return JsonResponse(
                {'error': 'missing or invalid Authorization header'},
                status=401,
            )
        raw = auth[7:]
        key_hash = hashlib.sha256(raw.encode()).hexdigest()
        try:
            api_key = ApiKey.objects.select_related('user').get(
                key_hash=key_hash, is_active=True
            )
        except ApiKey.DoesNotExist:
            return JsonResponse({'error': 'invalid API key'}, status=401)

        if not _check_rate_limit(api_key.pk):
            bucket_end = (int(time.time() // 60) + 1) * 60
            retry_after = int(bucket_end - time.time())
            return JsonResponse(
                {'error': 'rate limit exceeded', 'retry_after_seconds': retry_after},
                status=429,
            )

        # Update last_used_at without triggering auto_now — mirrors email_service.py pattern
        ApiKey.objects.filter(pk=api_key.pk).update(last_used_at=timezone.now())

        request.api_key = api_key
        request.api_user = api_key.user
        return view_func(request, *args, **kwargs)

    return wrapper
