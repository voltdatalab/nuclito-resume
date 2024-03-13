from fastapi import FastAPI, Header, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from app.controllers import post_controller
import os
import hmac
import logging
import json
import re

load_dotenv()


class WebhookResponse(BaseModel):
    result: str


class WebhookData(BaseModel):
    post: dict


APP_NAME = os.getenv("APP_NAME", "nuclito-responde.api.v2")

app = FastAPI(
    title=APP_NAME,
    description="API com os dados de resumos de reportagens gerados pelo Nuclito",
    version="2.0",
)

origins = os.getenv("CORS_ALLOWED_ORIGINS", "*").split()
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger(APP_NAME)
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(levelname)s:\t%(message)s")
file_logging = logging.StreamHandler()
file_logging.setFormatter(formatter)
logger.addHandler(file_logging)


@app.get("/", status_code=200)
async def get():
    return {"Hello": "World"}


@app.get("/post/", status_code=200)
async def get_last_posts():
    return await post_controller.read()


@app.get("/post/{amount}", status_code=200)
async def get_posts(amount):
    return await post_controller.read(amount)


@app.post("/post/", status_code=204)
async def post(
    webhook_input: WebhookData,
    request: Request,
    response: Response,
    x_ghost_signature: str = Header(None),
    x_hook_signature: str = Header(None),
):
    if not x_ghost_signature and not x_hook_signature:
        logger.error("No X-Ghost-Signature header provided")
        response.status_code = 400
        return {"result": "Invalid message signature"}

    raw_input = await request.body()
    input_hmac = hmac.new(
        key=os.getenv("WEBHOOK_SECRET").encode(), msg=raw_input, digestmod="sha256"
    )

    hmac_header_search = re.search("sha256=(.*), t=[0-9]*", x_ghost_signature)
    if not hmac_header_search:
        logger.error(
            f"Invalid message signature. Expected token in format 'sha256=(.*) t=[0-9]*' but got {x_ghost_signature}"
        )
        response.status_code = 401
        return {"result": "Invalid message signature"}

    sha256 = hmac_header_search.group(1)

    if not hmac.compare_digest(input_hmac.hexdigest(), sha256):
        logger.error(
            f"Invalid message signature. Expected token {input_hmac.hexdigest()} but got {sha256}"
        )
        response.status_code = 401
        return {"result": "Invalid message signature"}

    logger.info("Message signature checked ok")

    post_data = json.loads(raw_input)["post"]["current"]
    id = post_data["id"]
    title = post_data["title"]
    link = post_data["url"]
    content = post_data["plaintext"]
    primary_tag = post_data["primary_tag"]["slug"]

    if (not primary_tag.endswith("news")):
        await post_controller.create(id, title, link, content)


if __name__ == "__main__":
    import uvicorn
    from app.models import posts

    posts.Post.run()

    uvicorn.run(
        app,
        host=os.getenv("API_HOST", "localhost"),
        port=int(os.getenv("API_PORT", "8000")),
        proxy_headers=True,
    )
