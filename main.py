from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from auth import BasicAuthMiddleware
from db import init_db
from routes import router

app = FastAPI()

app.add_middleware(BasicAuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
def on_startup():
    init_db()


class RevalidatingStaticFiles(StaticFiles):
    """Static files with Cache-Control: no-cache, so browsers check for a
    newer page on every load instead of guessing (which left an old
    index.html showing after deploys until a hard refresh). The check is a
    cheap 304 when nothing changed, thanks to StaticFiles' ETag."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


# Serve the frontend last so it doesn't shadow the /api routes above.
app.mount("/", RevalidatingStaticFiles(directory="static", html=True), name="static")
