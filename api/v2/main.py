import os
from dotenv import load_dotenv
from app.publication_origin import STAGING, source_origin, source_origins

load_dotenv()
# Staging must never enter the legacy controller/IA path. Check before
# importing the HTTP app, inbox, model or controller, not on first request.
if source_origin() == STAGING and os.getenv('PUBLICATION_SYNC_ENABLED') != '1':
    raise ValueError('Invalid publication source configuration')

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from app.publication_sync import Inbox, Rejected, authenticate, normalize
APP_NAME = os.getenv("APP_NAME", "nuclito-responde.api.v2")
app = FastAPI(
    title=APP_NAME,
    description="API com os dados de resumos de reportagens gerados pelo Nuclito",
    version="2.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=(sorted(source_origins()) if 'PUBLICATION_SOURCE_ORIGIN' in os.environ
                   else os.getenv("CORS_ALLOWED_ORIGINS", "*").split()),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", status_code=200)
async def get():
    return {"Hello": "World"}


@app.get("/post/", status_code=200)
async def get_posts(request: Request, page: int = 0, amount: int = 6):
    if os.getenv('PUBLICATION_SYNC_ENABLED') == '1':
        if page < 0 or not 1 <= amount <= 100:
            return Response(status_code=400)
        try:
            inbox = getattr(request.app.state, 'publication_inbox', None) or publication_inbox()
            return await run_in_threadpool(inbox.read_verified, page=page, amount=amount)
        except Exception:
            return Response(status_code=503)
    from app.controllers import post_controller
    return await post_controller.read(page, amount)


@app.get("/post/{id}", status_code=200)
async def get_post(id: str, response: Response, request: Request):
    if os.getenv('PUBLICATION_SYNC_ENABLED') == '1':
        import re
        if not re.fullmatch(r'[0-9a-f]{24}', id):
            return Response(status_code=404)
        try:
            inbox = getattr(request.app.state, 'publication_inbox', None) or publication_inbox()
            post = await run_in_threadpool(inbox.read_verified, identity=id)
        except Exception:
            return Response(status_code=503)
    else:
        from app.controllers import post_controller
        post = await post_controller.get(id)
    if post is None:
        response.status_code = 404
        return {"result": "Post does not exist"}
    return post


def publication_inbox():
    from app.model import engine
    from app.models.posts import Post
    return Inbox(engine, Post.__table__)


@app.post("/post/", status_code=204)
async def post(request: Request):
    try:
        # Bound actual received bytes, not merely the client-controlled length.
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 256 * 1024:
                raise Rejected(413)
            raw.extend(chunk)
        raw = bytes(raw)
        authenticate(raw, request.headers, os.getenv('WEBHOOK_SECRET'))
        enabled = os.getenv('PUBLICATION_SYNC_ENABLED', '0') == '1'
        item = normalize(raw, require_revision=enabled)
        if enabled:
            inbox = getattr(request.app.state, 'publication_inbox', None)
            if inbox is None:
                inbox = publication_inbox()
            # Transaction commits before acknowledging Ghost; no background task.
            await run_in_threadpool(inbox.enqueue, item)
        elif item['eligible']:
            from app.controllers import post_controller
            await post_controller.create(item['id'], item['title'], item['url'], item['plaintext'])
        return Response(status_code=204)
    except Rejected as error:
        return Response(status_code=error.status)
    except Exception:
        # Never expose SQL parameters, article content, signatures or secrets.
        return Response(status_code=503)


if __name__ == "__main__":
    import uvicorn
    from app.models import posts
    posts.Post.run()  # Legacy posts schema only; never provisions the inbox.
    uvicorn.run(app, host=os.getenv("API_HOST", "localhost"),
                port=int(os.getenv("API_PORT", "8000")), proxy_headers=True)
