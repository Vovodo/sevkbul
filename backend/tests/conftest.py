import os

# Pytest çalışırken varsayılan veritabanını izole SQLite bellek veritabanı yap
os.environ["DATABASE_URL"] = "sqlite://"
