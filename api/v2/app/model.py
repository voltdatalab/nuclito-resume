from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy import create_engine
from sqlalchemy import URL
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv
import os

load_dotenv()

url_object = URL.create(
    os.getenv("DB_ENGINE", "sqlite"),
    username=os.getenv("DB_USERNAME"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    database=os.getenv("DB_DATABASE"),
)

engine = create_engine(url_object, echo=True)


class Model(DeclarativeBase):
    def insert(self):
        try:
            with Session(engine) as session:
                session.add(self)
                session.commit()
        except IntegrityError:
            pass

    @staticmethod
    def run():
        print("running migration...")
        Model.metadata.create_all(engine)
        print("migration successful!")

    @classmethod
    def select(cls, whereclause=None, orderby=None, limit=None):
        result = select(cls)
        if whereclause:
            result = result.where(whereclause)
        if orderby:
            result = result.order_by(orderby)
        if limit:
            result = result.limit(5)
        return Session(engine).scalars(result)
