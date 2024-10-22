from openai import OpenAI
from dotenv import load_dotenv
from app.models.posts import Post
import os
import json
import locale
import re


def get_valid_json_array(arraystr: str) -> str:
    match = re.search(
        r"""(\[[\n ]*(\t?"[^\"]*",[\n ]*){2}\t?"[^\"]*"[\n ]*\])""", arraystr
    )
    if match:
        return match.group(1)
    return None


locale.setlocale(locale.LC_ALL, "")
load_dotenv()
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# Try generating summaries until GPT-4 returns a valid JSON array
async def query_gpt_json(query: str, max_tries: int = 5):
    for _ in range(max_tries):
        chat_completion = openai_client.chat.completions.create(
            messages=[{"role": "user", "content": query}],
            model="gpt-4o-mini",
        )

        for choice in chat_completion.choices:
            summary = choice.message.content
            print(f"Received summary: {summary}")
            json_summary = get_valid_json_array(summary)
            print(f"Valid summary: {json_summary}")
            if json_summary is not None:
                return json_summary

    raise Exception("Summary not generated")


async def query_gpt_str(query: str):
    chat_completion = openai_client.chat.completions.create(
        messages=[{"role": "user", "content": query}],
        model="gpt-4o-mini",
    )

    return chat_completion.choices[0].message.content


async def create(id, title, link, content):
    # Only create new summary if post is not already in the database
    existing_post = list(Post.select(whereclause=Post.id == id))
    if len(existing_post) > 0:
        return existing_post[0]

    # Generate summary in Portuguese
    summary = await query_gpt_json(
        f"Faça um resumo deste texto em 3 tópicos, usando no máximo 30 palavras para cada tópico. Formate os tópicos como um array de strings em JavaScript, e retorne apenas o array, sem nenhuma formatação: {content}"
    )

    # Translate the summary to English
    summary_en = await query_gpt_json(
        f"Traduza o array JSON a seguir de português para inglês e retorne um novo array JSON. Retorne apenas o array, sem nenhuma formatação: {summary}"
    )

    title_en = await query_gpt_str(
        f"Traduza o título a seguir de português para inglês. Retorne apenas o texto do título: {title}"
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


async def get(id: str):
    post_list = Post.select(whereclause=(Post.id == id))
    if post_list is None or len(post_list) == 0:
        return None

    post = post_list[0]

    return {
        "summary": json.loads(post.summary) if post.summary else None,
        "summary_en": json.loads(post.summary_en) if post.summary_en else None,
    }
