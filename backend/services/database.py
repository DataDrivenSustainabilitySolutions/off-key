from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()


class Database:
    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)
        self.session_local = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )

    def get_db(self):
        database = self.session_local()
        try:
            yield database
        finally:
            database.close()

    def create_tables(self):
        Base.metadata.create_all(bind=self.engine)
