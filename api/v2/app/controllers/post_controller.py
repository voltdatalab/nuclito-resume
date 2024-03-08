from openai import OpenAI
from dotenv import load_dotenv
from app.models.posts import Post
import os

load_dotenv()
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def create(id, title, link, content):
    existing_post = list(Post.select(whereclause=Post.id == id))
    if len(existing_post) > 0:
        return existing_post[0]

    chat_completion = openai_client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": f"Faça um resumo deste texto em 3 bullet points, usando no máximo 20 palavras para cada bullet. Formate os bullets como uma lista em HTML: {content}",
            }
        ],
        model="gpt-4",
    )

    summary = chat_completion.choices[0].message.content

    return Post(id=id, title=title, link=link, summary=summary).insert()


async def read(amount=5):
    posts = Post.select(orderby=Post.timestamp.desc(), limit=5)
    content = ""
    for post in posts:
        content += f'<h1>{post.title}</h1><p></p>{post.summary}<p></p><a class="button-tit" href="{post.link}">Quero saber mais</a>'
    return f"<html><head></head><body>{content}</body></html>"
