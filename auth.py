import base64
import hmac
import os

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# Shared household login. Set APP_PASSWORD in the environment to turn this on;
# APP_USERNAME defaults to "family" if not set. This is deliberately simple
# (one shared login, browser's native basic-auth prompt) -- it's meant to keep
# the app off of casual/accidental access, not to withstand a targeted attack.
APP_USERNAME = os.environ.get("APP_USERNAME", "family")
APP_PASSWORD = os.environ.get("APP_PASSWORD")

# Optional second login for letting someone click around without seeing real
# data. Demo requests never touch Postgres -- they're served entirely out of
# the in-memory DemoStore below, which resets on every server restart. If
# DEMO_PASSWORD isn't set, the demo login is simply disabled.
DEMO_USERNAME = os.environ.get("DEMO_USERNAME", "demo")
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD")

# Paths that should stay reachable without logging in, e.g. so Render's own
# health checks don't get blocked by auth and mark the service unhealthy.
PUBLIC_PATHS = {"/api/health"}


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        if not APP_PASSWORD:
            # Fail closed with a clear message rather than silently running
            # the app wide open if someone forgets to set the password.
            return Response(
                "Server misconfigured: APP_PASSWORD is not set.",
                status_code=500,
            )

        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("basic "):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                username, _, password = decoded.partition(":")
            except Exception:
                username, password = "", ""

            if hmac.compare_digest(username, APP_USERNAME) and hmac.compare_digest(
                password, APP_PASSWORD
            ):
                request.state.demo = False
                return await call_next(request)

            if (
                DEMO_PASSWORD
                and hmac.compare_digest(username, DEMO_USERNAME)
                and hmac.compare_digest(password, DEMO_PASSWORD)
            ):
                request.state.demo = True
                return await call_next(request)

        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Behavior Tracker"'},
        )


def is_demo(request: Request) -> bool:
    return getattr(request.state, "demo", False)
