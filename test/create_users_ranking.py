from pathlib import Path
from pymongo import MongoClient
from pprint import pprint


# ---------------------------------------------------------
# LOAD ENV + CONNECT TO MONGO
# ---------------------------------------------------------

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
    print(f"Connecting to MongoDB at {db_ip}:{db_port} as {username}...\n")

    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    db = client["Steam_Project"]
    return db


# ---------------------------------------------------------
# CREATE INDEXES FOR FAST "REVIEWS PER USER" QUERIES
# ---------------------------------------------------------

def create_review_indexes(reviews):
    print("Creating indexes on reviews collection...\n")

    idx1 = reviews.create_index("user")
    print("Index created:", idx1)

    idx2 = reviews.create_index([("user", 1), ("app_id", 1)])
    print("Index created:", idx2)

    idx3 = reviews.create_index([("user", 1), ("post_date", 1)])
    print("Index created:", idx3)

    print("\nAll review indexes created.\n")


# ---------------------------------------------------------
# BUILD MATERIALIZED VIEW: user_review_stats
# ---------------------------------------------------------

def build_user_review_stats(db, reviews_coll_name="reviews", stats_coll_name="user_review_stats"):
    reviews = db[reviews_coll_name]
    stats = db[stats_coll_name]

    print(f"\nBuilding materialized collection: {stats_coll_name} ...")

    pipeline = [
        {"$sortByCount": "$user"},  # produces { _id: "username", count: <num> }
        {
            "$merge": {
                "into": stats_coll_name,
                "on": "_id",               # user field becomes the _id
                "whenMatched": "replace",  # replace old stats
                "whenNotMatched": "insert"
            }
        }
    ]

    reviews.aggregate(pipeline, allowDiskUse=True)

    print("Materialized stats collection updated.\n")

    # Create index for fast top-N queries
    print("Creating index on stats collection...\n")
    idx = stats.create_index([("count", -1)])
    print("Index created:", idx)

    return stats


# ---------------------------------------------------------
# MAIN SCRIPT
# ---------------------------------------------------------

if __name__ == "__main__":
    db = get_db()
    reviews = db["reviews"]

    # Show basic info
    print("Collections in DB:", db.list_collection_names())
    total_reviews = reviews.count_documents({})
    print(f"Total reviews in 'reviews' collection: {total_reviews}\n")

    # Step 1: Create indexes
    create_review_indexes(reviews)

    # Step 2: Build materialized stats
    stats = build_user_review_stats(db)

    # Step 3: Show top reviewers
    print("\nTop 20 reviewers:\n")
    cursor = stats.find().sort("count", -1).limit(20)

    for i, doc in enumerate(cursor, start=1):
        print(f"{i:2}. user={doc['_id']!r}   reviews={doc['count']}")
