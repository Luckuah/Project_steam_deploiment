from pathlib import Path
from pymongo import MongoClient
from pprint import pprint


# ----------------- ENV & DB CONNECTION ----------------- #

def load_env() -> dict:
    """
    Load simple KEY=VALUE pairs from the project .env file.
    Assumes this file is located at project_root/.env, where
    project_root is two directories above this script.
    """
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


# ----------------- LOGIC: TOP REVIEWERS ----------------- #

def get_users_with_most_reviews(coll, limit: int = 20, min_reviews: int | None = None):
    """
    Return top `limit` users sorted by number of reviews (desc).
    Optionally filter to users with at least `min_reviews` reviews.
    """
    pipeline = [
        {"$group": {"_id": "$user", "review_count": {"$sum": 1}}},
        {"$sort": {"review_count": -1}},
    ]

    if min_reviews is not None:
        # insert match after group but before sort
        pipeline.insert(1, {"$match": {"review_count": {"$gte": min_reviews}}})

    if limit is not None:
        pipeline.append({"$limit": limit})

    return list(coll.aggregate(pipeline))


if __name__ == "__main__":
    db = get_db()
    reviews_coll = db["reviews"]

    TOP_N = 20
    MIN_REVIEWS = None  # e.g. set to 5 if you want only "heavy" reviewers

    print("\nCollections in this DB:")
    print(db.list_collection_names())

    total_reviews = reviews_coll.count_documents({})
    print(f"\nTotal docs in 'reviews': {total_reviews}")

    print(f"\nTop {TOP_N} users by number of reviews:")
    top_users = get_users_with_most_reviews(
        reviews_coll,
        limit=TOP_N,
        min_reviews=MIN_REVIEWS,
    )

    for rank, doc in enumerate(top_users, start=1):
        username = doc["_id"]
        count = doc["review_count"]
        print(f"{rank:2}. {username!r} - {count} reviews")

    # Optional: show full doc of the #1 reviewer
    if top_users:
        print("\nDetails of the top reviewer:")
        pprint(top_users[0])
