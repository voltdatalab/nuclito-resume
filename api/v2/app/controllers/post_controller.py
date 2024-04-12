from openai import OpenAI
from dotenv import load_dotenv
from app.models.posts import Post
import os
import json
import locale
import re


def is_valid_json_array(arraystr: str) -> bool:
    return (
        re.match(r"""^\[[\n ]?(\t?".*",[\n ]?){2}\t?".*"[\n ]?\]$""", arraystr)
        is not None
    )


locale.setlocale(locale.LC_ALL, "")
load_dotenv()
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# Try generating summaries until GPT-4 returns a valid JSON array
async def query_gpt_json(query: str, max_tries: int = 5):
    for _ in range(max_tries):
        chat_completion = openai_client.chat.completions.create(
            messages=[{"role": "user", "content": query}],
            model="gpt-4",
        )

        for choice in chat_completion.choices:
            summary = choice.message.content
            print(f"Generated summary: {summary}")
            if is_valid_json_array(summary):
                return summary
    return ""


async def query_gpt_str(query: str):
    chat_completion = openai_client.chat.completions.create(
        messages=[{"role": "user", "content": query}],
        model="gpt-4",
    )

    return chat_completion.choices[0].message.content


async def create(id, title, link, content):
    # Only create new summary if post is not already in the database
    existing_post = list(Post.select(whereclause=Post.id == id))
    if len(existing_post) > 0:
        return existing_post[0]

    # Generate summary in Portuguese
    summary = await query_gpt_json(
        f"Faça um resumo deste texto em 3 tópicos, usando no máximo 30 palavras para cada tópico. Formate os tópicos como um array de strings em JavaScript: {content}"
    )

    # Translate the summary to English
    summary_en = await query_gpt_json(
        f"Traduza o array JSON a seguir de português para inglês e retorne um novo array JSON: {summary}"
    )

    title_en = await query_gpt_str(
        f"Traduza o título a seguir de português para inglês: {title}"
    )

    # Insert in database
    return Post(
        id=id,
        title=title,
        title_en=title_en,
        link=link,
        summary=summary,
        summary_en=summary_en,
    ).insert()


async def read(page=0, amount=5):
    limit = int(amount)
    offset = int(page) * limit

    posts = Post.select(orderby=Post.timestamp.desc(), limit=limit, offset=offset)

    content = []
    for post in posts:
        content.append(
            {
                "title": post.title,
                "title_en": post.title_en if post.title_en else post.title,
                "summary": json.loads(post.summary),
                "summary_en": (
                    json.loads(post.summary_en)
                    if post.summary_en
                    else ["No summary in English available"]
                ),
                "link": post.link,
                "date": post.timestamp.strftime("%d.%b.%Y"),
            }
        )
    return content
