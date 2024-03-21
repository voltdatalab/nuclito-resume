from openai import OpenAI
from dotenv import load_dotenv
from app.models.posts import Post
import os
import json
import locale

locale.setlocale(locale.LC_ALL, "")
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
                "content": f"Faça um resumo deste texto em 3 tópicos, usando no máximo 20 palavras para cada tópico. Formate os tópicos como um array JSON: {content}",
            }
        ],
        model="gpt-4",
    )

    summary = chat_completion.choices[0].message.content

    return Post(id=id, title=title, link=link, summary=summary).insert()


async def read(page=0, amount=5):
    limit = int(amount)
    offset = int(page) * limit
    posts = Post.select(orderby=Post.timestamp.desc(), limit=limit, offset=offset)
    content = []
    for post in posts:
        content.append(
            {
                "title": post.title,
                "summary": json.loads(post.summary),
                "link": post.link,
                "date": post.timestamp.strftime("%d.%b.%Y"),
            }
        )
    return content
