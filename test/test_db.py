import requests


BASE_URL = "http://localhost:27099"

def get_game_info(game_id,verbose=False):
    """
    get top recommended games from /recommandation endpoint
    using the {message, Status} format.
    """
    try:
        resp = requests.post(f"{BASE_URL}/Game",params={f"game_id": {game_id}}, timeout=10)
        # Same note: you now always return HTTP 200,
        # but keep it anyway:
        resp.raise_for_status()

        data = resp.json()
        status = data.get("Status")
        message = data.get("message")
        
        if status is True:
            if verbose:
                print("✅ /health OK:", message)
            return message
        else:
            print("❌ /health reported a problem:", message)
    except Exception as e:
        print("❌ /health failed:", e)
def check_fastapi():
    """
    Check if the FastAPI server is responding at all.
    We just hit the docs endpoint.
    """
    try:
        resp = requests.get(f"{BASE_URL}/docs", timeout=3)
        resp.raise_for_status()
        print("✅ FastAPI server is UP (docs reachable). Status:", resp.status_code)
    except Exception as e:
        print("❌ FastAPI server is NOT responding:", e)
def check_mongodb_via_api():
    """
    Check if MongoDB is responding by calling /command
    with { 'ping': 1 } and using the {message, Status} format.
    """
    payload = {
        "command": {"ping": 1}
    }

    try:
        resp = requests.post(f"{BASE_URL}/command", json=payload, timeout=3)
        # With your new API, it should always be HTTP 200, even on error,
        # but we keep this for safety:
        resp.raise_for_status()

        data = resp.json()
        print("✅ /command responded. Raw JSON:")
        print(data)

        status = data.get("Status")
        message = data.get("message")

        if status is True:
            print("✅ API says Status=True.")
            # message is what MongoDB returned (dict with "ok", etc.)
            if isinstance(message, dict) and message.get("ok") in (1, 1.0):
                print("✅ MongoDB ping OK through FastAPI.")
            else:
                print("⚠️ Status=True but unexpected 'message' content:", message)
        else:
            print("❌ API says Status=False. Error from server:")
            print("   ->", message)

    except requests.exceptions.RequestException as e:
        print("❌ Error calling /command:", e)
def check_health():
    """
    Call /health and interpret the {message, Status} format.
    """
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=3)
        # Same note: you now always return HTTP 200,
        # but keep it anyway:
        resp.raise_for_status()

        data = resp.json()
        status = data.get("Status")
        message = data.get("message")

        if status is True:
            print("✅ /health OK:", message)
        else:
            print("❌ /health reported a problem:", message)

    except Exception as e:
        print("❌ /health failed:", e)
def Test_games_reco():
    """
    Call /recommandation and interpret the {message, Status} format.
    """
    try:
        resp = requests.get(f"{BASE_URL}/recommandation", timeout=10)
        # Same note: you now always return HTTP 200,
        # but keep it anyway:
        resp.raise_for_status()

        data = resp.json()
        status = data.get("Status")
        message = data.get("message")
        if status is True:
            print("✅ /recommandation OK:",message)#[game["name"] for game in message]
        else:
            print("❌ /recommandation reported a problem:", message)

    except Exception as e:
        print("❌ /recommandation failed:", e)


if __name__ == "__main__":
    # print("=== Checking FastAPI ===")
    # check_fastapi()

    # print("\n=== Checking MongoDB via /command ===")
    # check_mongodb_via_api()

    # print("\n=== Checking /health endpoint ===")
    # check_health()
    
    # print("\n=== Testing /recommandation endpoint ===")
    # Test_games_reco()
    print(get_game_info(10).keys())