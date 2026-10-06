"""Test package for book_store_bot.

Importing this package configures a safe environment BEFORE any bot module is
imported (bot.config reads the environment at import time):
  * OPENAI_API_KEY is blanked, so no test can reach a paid API;
  * DB_NAME is forced to a dedicated throwaway database (default
    "books_store_ragtest") — DB tests refuse to run against anything else.

Run (inside the bot image, against the LOCAL compose Postgres):
    docker compose run --rm --no-deps -v "$PWD":/app -e DB_HOST=db seed \\
        python -m unittest discover -s tests -t . -v
Optional real-book smoke test (file stays outside the repo):
    ... -v /path/to/book_dir:/book:ro -e RAG_BOOK_JSONL=/book/<name>.chunks.jsonl ...
"""

import os

os.environ["OPENAI_API_KEY"] = ""
os.environ.setdefault("BOT_TOKEN", "123456:TEST-TOKEN-NOT-REAL")
os.environ["DB_NAME"] = os.environ.get("RAG_TEST_DB_NAME", "books_store_ragtest")
os.environ.setdefault("RAG_EMBEDDING_PROVIDER", "none")
