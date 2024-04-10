from sqlalchemy import String, Text, DateTime
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.sql import func
from datetime import datetime
from app.model import Model


class Post(Model):
    __tablename__ = "posts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    title_en: Mapped[str] = mapped_column(Text, nullable=True)
    link: Mapped[str] = mapped_column(String(256))
    summary: Mapped[str] = mapped_column(Text())
    summary_en: Mapped[str] = mapped_column(Text(), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())

    def summary_str(self):
        max_size = 32
        if (len(str(self.summary))) > max_size:
            return str(self.summary)[:max_size] + "..."
        return str(self.summary)

    def summary_en_str(self):
        max_size = 32
        if (len(str(self.summary_en))) > max_size:
            return str(self.summary_en)[:max_size] + "..."
        return str(self.summary_en)

    def __repr__(self) -> str:
        return f"""Post(
            id={self.id},
            title={self.title},
            title_en={self.title_en},
            link={self.link},
            timestamp={self.timestamp},
            summary={self.summary_str()},
            summary_en={self.summary_en_str()})"""


if __name__ == "__main__":
    Post.run()
    post = Post(
        id="teste123",
        title="Teste de Título",
        title_en="Title Test",
        link="https://nucleo.jor.br/garimpo/teste123",
        summary="""["Olá": "Mundo"]""",
        summary_en="""["Hello": "World"]""",
    ).insert()

    for p in Post.select():
        print(p)
