from pathlib import Path
from pymongo import MongoClient
from pprint import pprint


def load_env() -> dict:
    project_root = Path(__file__).resolve().parent.parent
    env_path = project_root / ".env"

    if not env_path.exists():
        print(f"WARNING: .env not found at {env_path}")
        return {}

    env_vars = {
        k.strip(): v.strip()
        for k, v in (
            line.split("=", 1)
            for line in env_path.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    }
    return env_vars


def get_db():
    env_vars = load_env()

    username = env_vars.get("DB_USER", "user")
    password = env_vars.get("DB_PASSWORD", "pass")
    db_ip = env_vars.get("DB_IP", "localhost")
    db_port = env_vars.get("DB_PORT", "27017")

    uri = f"mongodb://{username}:{password}@{db_ip}:{db_port}/?authSource=admin"
    print(f"Connecting to MongoDB at {db_ip}:{db_port} as {username}...")

    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    db = client["Steam_Project"]
    return db


def collect_unique_tag_keys(coll):
    unique_tags = set()

    # Only docs that have 'tags'
    cursor = coll.find({"tags": {"$exists": True}}, {"tags": 1, "_id": 0})

    docs_seen = 0
    for doc in cursor:
        docs_seen += 1
        tags_field = doc.get("tags")

        # Case 1: tags is a dict like {"MMO": 250, "RPG": 132}
        if isinstance(tags_field, dict):
            unique_tags.update(tags_field.keys())

        # (you can add more cases here if needed once we know the real shape)

    print(f"Processed {docs_seen} docs that have 'tags'")
    return sorted(unique_tags)


if __name__ == "__main__":
    db = get_db()
    coll = db["games"]

    print("\nCollections in this DB:")
    print(db.list_collection_names())

    total_docs = coll.count_documents({})
    docs_with_tags = coll.count_documents({"tags": {"$exists": True}})

    print(f"\nTotal docs in 'games'  : {total_docs}")
    print(f"Docs with 'tags' field : {docs_with_tags}")

    print("\nSample doc with 'tags':")
    sample = coll.find_one({"tags": {"$exists": True}}, {"tags": 1})
    pprint(sample)

    tags = collect_unique_tag_keys(coll)

    print(f"\nFound {len(tags)} unique tags:\n")
    for t in tags:
        print(t)
