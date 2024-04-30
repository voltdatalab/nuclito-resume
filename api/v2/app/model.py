from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy import create_engine, exc
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

pool_size = int(os.getenv("DB_POOL_SIZE", 20))
max_overflow = int(os.getenv("DB_MAX_OVERFLOW", 0))
pool_recycle = int(os.getenv("DB_POOL_RECYCLE", 300))

engine = create_engine(
    url_object,
    echo=True,
    pool_size=pool_size,
    max_overflow=max_overflow,
    pool_recycle=pool_recycle,
)


class Model(DeclarativeBase):
    def insert(self):
        try:
            with Session(engine) as session:
                try:
                    session.add(self)
                    session.commit()
                except exc.DBAPIError as e:
                    if e.connection_invalidated:
                        # Try again. If the error happens again, than something
                        # is very wrong
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
    def select(cls, whereclause=None, orderby=None, limit=None, offset=None):
        result = select(cls)
        if whereclause is not None:
            result = result.where(whereclause)
        if orderby is not None:
            result = result.order_by(orderby)
        if limit is not None:
            result = result.limit(limit)
        if offset is not None:
            result = result.offset(offset)

        with Session(engine) as session:
            try:
                result = list(session.scalars(result))
            except exc.DBAPIError as e:
                if e.connection_invalidated:
                    # Try again. If the error happens again, than something is
                    # very wrong
                    result = list(session.scalars(result))
        return result
