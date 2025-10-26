import os
import json
from typing import List, Optional, Dict
from urllib import request as urlrequest

FCM_ENDPOINT_DEFAULT = "https://fcm.googleapis.com/fcm/send"


def _chunked(items: List[str], size: int = 900) -> List[List[str]]:
    # FCM legacy API supports up to 1000 registration_ids per request; keep buffer under limit
    return [items[i:i + size] for i in range(0, len(items), size)]


def send_to_tokens(tokens: List[str], title: str, body: str, data: Optional[Dict] = None) -> Dict:
    """Send a push notification to a list of FCM tokens using the legacy HTTP API.

    Returns a summary dict with attempted/sent counts. If FCM_SERVER_KEY is missing, it no-ops.
    """
    tokens = [t for t in (tokens or []) if t]
    if not tokens:
        return {"attempted": 0, "sent": 0}

    server_key = os.getenv("FCM_SERVER_KEY") or os.getenv("FIREBASE_SERVER_KEY")
    if not server_key:
        # No FCM key configured; skip sending
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

    return {"attempted": attempted, "sent": sent_total}
