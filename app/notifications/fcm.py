import os
import json
from typing import List, Optional, Dict
from urllib import request as urlrequest

FCM_ENDPOINT_DEFAULT = "https://fcm.googleapis.com/fcm/send"

# Try Firebase Admin SDK (v1 API)
try:
    import firebase_admin  # type: ignore
    from firebase_admin import credentials, messaging  # type: ignore
except Exception:  # pragma: no cover
    firebase_admin = None  # type: ignore
    credentials = None  # type: ignore
    messaging = None  # type: ignore


def _chunked(items: List[str], size: int = 900) -> List[List[str]]:
    # FCM legacy API supports up to 1000 registration_ids per request; keep buffer under limit
    return [items[i:i + size] for i in range(0, len(items), size)]


def send_to_tokens(tokens: List[str], title: str, body: str, data: Optional[Dict] = None) -> Dict:
    """Send push notifications to device tokens.

    Priority: Firebase Admin SDK (v1) using a service account JSON path from env.
    Fallback: Legacy HTTP API with server key from env.
    Returns a summary dict with attempted/sent counts.
    """
    tokens = [t for t in (tokens or []) if t]
    if not tokens:
        return {"attempted": 0, "sent": 0}

    # First try Firebase Admin SDK (v1)
    if firebase_admin is not None:
        try:
            if not firebase_admin._apps:  # type: ignore[attr-defined]
                cred_path = os.getenv("FIREBASE_CREDENTIALS_FILE") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
                if cred_path:
                    cred = credentials.Certificate(cred_path)  # type: ignore[call-arg]
                    firebase_admin.initialize_app(cred)  # type: ignore[call-arg]
            if firebase_admin._apps:  # type: ignore[attr-defined]
                # v1 send via Admin SDK
                notif = messaging.Notification(title=title, body=body)  # type: ignore[call-arg]
                data_str = {str(k): str(v) for k, v in (data or {}).items()}
                # FCM supports up to 500 tokens for send_multicast
                attempted = 0
                sent_total = 0
                for batch in _chunked(tokens, size=500):
                    msg = messaging.MulticastMessage(notification=notif, data=data_str, tokens=batch)  # type: ignore[call-arg]
                    resp = messaging.send_multicast(msg)
                    attempted += len(batch)
                    sent_total += int(getattr(resp, "success_count", 0))
                return {"attempted": attempted, "sent": sent_total, "v1": True}
        except Exception:
            # Fall through to legacy on any Admin SDK error
            pass

    # Legacy HTTP fallback using server key
    server_key = os.getenv("FCM_SERVER_KEY") or os.getenv("FIREBASE_SERVER_KEY")
    if not server_key:
        # No credentials configured; skip sending
        return {"attempted": len(tokens), "sent": 0, "skipped": True}

    endpoint = os.getenv("FCM_ENDPOINT", FCM_ENDPOINT_DEFAULT)
    headers = {
        "Authorization": f"key={server_key}",
        "Content-Type": "application/json",
    }

    attempted = 0
    sent_total = 0

    for batch in _chunked(tokens, size=900):
        payload = {
            "registration_ids": batch,
            "notification": {
                "title": title,
                "body": body,
            },
            "data": data or {},
        }
        attempted += len(batch)
        try:
            req = urlrequest.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            with urlrequest.urlopen(req, timeout=10) as resp:
                # Best-effort parse
                resp_body = resp.read().decode("utf-8", errors="ignore")
                try:
                    obj = json.loads(resp_body)
                    sent_total += int(obj.get("success", 0))
                except Exception:
                    # If not JSON, assume success when HTTP 200
                    if 200 <= resp.status < 300:
                        sent_total += len(batch)
        except Exception:
            # Ignore per-batch errors to avoid breaking the flow
            pass

    return {"attempted": attempted, "sent": sent_total, "legacy": True}
