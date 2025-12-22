import requests
import streamlit as st
from pathlib import Path
from typing import List, Optional, Any, Dict
import traceback
env_vars = {
    k.strip(): v.strip()
    for k, v in (
        line.split("=", 1)
        for line in Path("src/.env").read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    )
}

Host_ip = env_vars.get("API_BASE_IP", "localhost")
Host_port = env_vars.get("API_BASE_PORT", "8000")
BASE_URL = f"http://{Host_ip}:{Host_port}"
def get_default_game_reco(verbose=False):
    """
    get top recommended games from /recommandation endpoint
    using the {message, Status} format.
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
            if verbose:
                print("✅ /health OK:", message)
            return message
        else:
            print("❌ /health reported a problem:", message)

    except Exception as e:
        print("❌ /health failed:", e)
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
                print("✅ /Game OK:", message)
            return message
        else:
            print("❌ /Game reported a problem:", message)
    except Exception as e:
        print("❌ /Game failed:", e)
def get_games_info(game_ids, verbose=False):
    """
    Get info for a list of games from the /Games endpoint,
    using the {message, Status} response format.
    
    Parameters
    ----------
    game_ids : list[int]
        List of app IDs to fetch.
    verbose : bool
        If True, prints debug info.
    """
    try:
        # /Games expects a JSON body: { "appids": [...] }
        resp = requests.post(
            f"{BASE_URL}/Games",
            json={"appids": game_ids},
            timeout=10
        )
        # You said you always return HTTP 200, but keep this anyway:
        resp.raise_for_status()

        data = resp.json()
        status = data.get("Status")
        message = data.get("message")

        if status is True:
            if verbose:
                print("✅ /Games OK:", message)
            return message
        else:
            print("❌ /Games reported a problem:", message)

    except Exception as e:
        print("❌ /Games failed:", e)

def add_user(name: str, verbose: bool = False):
    """
    Create a user via POST /user with payload {"name": <name>}.
    Returns `message` on success; prints an error otherwise.
    """
    try:
        resp = requests.post(f"{BASE_URL}/user", json={"name": name}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("Status")
        message = data.get("message")

        if status is True:
            if verbose:
                print(f"✅ /user create OK:", message)
            return True, message
        else:
            print(f"❌ /user create reported a problem:", message)
            return False, message
    except Exception as e:
        print("❌ /user create failed:", e)
def delete_user(name: str, verbose: bool = False):
    """
    Delete a user via DELETE /user with payload {"name": <name>}.
    Returns `message` on success; prints an error otherwise.
    """
    try:
        resp = requests.delete(f"{BASE_URL}/user", json={"name": name}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("Status")
        message = data.get("message")

        if status is True:
            if verbose:
                print(f"✅ /user delete OK:", message)
            return True, message
        else:
            print(f"❌ /user delete reported a problem:", message)
            return False, message
    except Exception as e:
        print("❌ /user delete failed:", e)
def rename_user(old_name: str, new_name: str, verbose: bool = False):
    """
    Rename a user via PATCH /user with payload {"old_name": <old>, "new_name": <new>}.
    Returns `message` on success; prints an error otherwise.
    """
    try:
        payload = {"old_name": old_name, "new_name": new_name}
        resp = requests.patch(f"{BASE_URL}/user", json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("Status")
        message = data.get("message")

        if status is True:
            if verbose:
                print(f"✅ /user rename OK:", message)
            return True, message
        else:
            print(f"❌ /user rename reported a problem:", message)
            return False, message
    except Exception as e:
        print("❌ /user rename failed:", e) 
def get_user_by_name(name: str, verbose: bool = False):
    """
    Fetch a user from GET /user?name=<name>.
    Returns `message` on success (the user document), else prints the error.
    """
    try:
        resp = requests.get(f"{BASE_URL}/user", params={"name": name}, timeout=10)
        resp.raise_for_status()

        data = resp.json()
        status = data.get("Status")
        message = data.get("message")

        if status is True:
            if verbose:
                print("✅ /user fetch OK:", message)
            return True, message
        else:
            print("❌ /user fetch reported a problem:", message)
            return False, message

    except Exception as e:
        print("❌ /user fetch failed:", e)
def update_user_object(user: dict, verbose: bool = False):
    """
    Update an existing user via PUT /user with the full user object as JSON.
    The 'name' field in `user` is treated as the unique ID.
    
    Behavior (mirrors your API):
    - If a user with that name exists -> it is updated with the content of `user`.
    - If not -> the API returns Status=False with a 'User <name> not found.' message.
    
    Returns:
        (success: bool, message: Any)
    """
    if "name" not in user or not user["name"]:
        msg = "Field 'name' is required in the user object."
        print(f"❌ /user update reported a problem: {msg}")
        return False, msg

    try:
        resp = requests.put(f"{BASE_URL}/user", json=user, timeout=10)
        resp.raise_for_status()

        data = resp.json()
        status = data.get("Status")
        message = data.get("message")

        if status is True:
            if verbose:
                print(f"✅ /user update OK:", message)
            return True, message
        else:
            print(f"❌ /user update reported a problem:", message)
            return False, message

    except Exception as e:
        print("❌ /user update failed:", e)
        return False, str(e)
def get_user_recommendation(user_id: str, topk: int = 500,return_ids_only: bool = False):
    """
    Python client wrapper for POST /recomandation/NLGCL

    Returns:
        (success: bool, message: Any)
    """
    try:
        resp = requests.post(
            f"{BASE_URL}/recomandation/NLGCL",
            json={"user_id": user_id, "topk": topk},  # <-- JSON BODY
            timeout=100,
        )

        # Don't raise before we inspect the body – we want to see FastAPI's error if any
        try:
            data = resp.json()
        except Exception:
            # If parsing fails, show raw text
            print("Server raw response:", resp.text)
            resp.raise_for_status()
            return False, resp.text

        if resp.status_code != 200:
            # Show FastAPI validation error details (422 etc.)
            print(f"❌ HTTP {resp.status_code} from /recomandation/NLGCL:", data)
            return False, data

        status = data.get("Status")
        message = data.get("message")
        message = sorted(message, key=lambda item: item.get("positive", 0), reverse=True)
        if status is True:
            if return_ids_only:
                ids_only = [item.get("_id") for item in message]
                return True, ids_only
            else:
                return True, message
        else:
            print("❌ /recomandation/NLGCL reported a problem:", message)
            return False, message

    except Exception as e:
        print(f"❌ Failed to call /recomandation/NLGCL for user_id={user_id}:", e)
        traceback.print_exc()
        return False, str(e)

def search_games_connector(
    n: int,
    max_price: Optional[float] = None,
    name_contains: Optional[str] = None,
    categories: Optional[List[str]] = None,
    genres: Optional[List[str]] = None,
    min_negative: Optional[int] = None,
    max_negative: Optional[int] = None,
    min_positive: Optional[int] = None,
    max_positive: Optional[int] = None,
    release_date_from: Optional[str] = None,  # ISO string, e.g. "2023-01-01T00:00:00" (le formatage...)
    release_date_to: Optional[str] = None,
    min_required_age: Optional[int] = None,
    max_required_age: Optional[int] = None,
    required_tags: Optional[List[str]] = None,
    verbose: bool = False,
) -> tuple[bool, Any]:
    """
    Call POST /games/search with the given filters.

    Returns:
        (success: bool, message: Any)
        On success, message is a dict: { "count": int, "games": [ ... ] }
    """
    payload: Dict[str, Any] = {"limit": n}

    if max_price is not None:
        payload["max_price"] = max_price
    if name_contains is not None:
        payload["name_contains"] = name_contains
    if categories is not None:
        payload["categories"] = categories
    if genres is not None:
        payload["genres"] = genres

    if min_negative is not None:
        payload["min_negative"] = min_negative
    if max_negative is not None:
        payload["max_negative"] = max_negative
    if min_positive is not None:
        payload["min_positive"] = min_positive
    if max_positive is not None:
        payload["max_positive"] = max_positive

    if release_date_from is not None:
        payload["release_date_from"] = release_date_from
    if release_date_to is not None:
        payload["release_date_to"] = release_date_to

    if min_required_age is not None:
        payload["min_required_age"] = min_required_age
    if max_required_age is not None:
        payload["max_required_age"] = max_required_age

    if required_tags is not None:
        payload["required_tags"] = required_tags

    try:
        resp = requests.post(f"{BASE_URL}/games/search", json=payload, timeout=20)
        resp.raise_for_status()

        data = resp.json()
        status = data.get("Status")
        message = data.get("message")

        if status is True:
            if verbose:
                print("✅ /games/search OK. Found:", message.get("count", 0))
            return True, message
        else:
            print("❌ /games/search reported a problem:", message)
            return False, message

    except Exception as e:
        print("❌ /games/search failed:", e)
        return False, str(e)
def search_reviews_connector(
    app_id: int,
    n: int,
    min_playtime: Optional[float] = None,
    min_helpfulness: Optional[int] = None,
    post_date_from: Optional[str] = None,  # ISO string: "2021-01-01T00:00:00" (le formatage... encore une fois pour pas oublier)
    post_date_to: Optional[str] = None,
    recommended: Optional[bool] = None,
    early_access: Optional[bool] = None,
    username: Optional[str] = None,
    verbose: bool = False,
) -> tuple[bool, Any]:
    """
    Call POST /reviews/search for a given app_id with optional filters.

    Returns:
        (success: bool, message: Any)
        On success, message is:
        {
          "count": int,
          "reviews": [ ... ]
        }
    """
    payload: Dict[str, Any] = {
        "app_id": app_id,
        "limit": n,
    }

    if min_playtime is not None:
        payload["min_playtime"] = min_playtime
    if min_helpfulness is not None:
        payload["min_helpfulness"] = min_helpfulness
    if post_date_from is not None:
        payload["post_date_from"] = post_date_from
    if post_date_to is not None:
        payload["post_date_to"] = post_date_to
    if recommended is not None:
        payload["recommended"] = recommended
    if early_access is not None:
        payload["early_access"] = early_access
    if username is not None:
        payload["username"] = username

    try:
        resp = requests.post(f"{BASE_URL}/reviews/search", json=payload, timeout=20)
        resp.raise_for_status()

        data = resp.json()
        status = data.get("Status")
        message = data.get("message")

        if status is True:
            if verbose:
                print("✅ /reviews/search OK. Found:", message.get("count", 0))
            return True, message
        else:
            print("❌ /reviews/search reported a problem:", message)
            return False, message

    except Exception as e:
        print("❌ /reviews/search failed:", e)
        return False, str(e)
def get_unique_tags_categories(verbose=False):
    """
    Call /UniqueTagsCategories endpoint and return:
    {
        "tags": [...],
        "categories": [...]
    }
    using the {message, Status} format.
    """
    try:
        resp = requests.get(f"{BASE_URL}/UniqueTagsCategories", timeout=10)
        resp.raise_for_status()

        data = resp.json()
        status = data.get("Status")
        message = data.get("message")

        if status is True:
            if verbose:
                print("✅ /UniqueTagsCategories OK")
                print(f"  Found {len(message.get('tags', []))} unique tags")
                print(f"  Found {len(message.get('categories', []))} unique categories")
            return message
        else:
            print("❌ /UniqueTagsCategories reported a problem:", message)

    except Exception as e:
        print("❌ /UniqueTagsCategories failed:", e)

def gensar_recommendation_connector(
    username: str,
    top_k: int = 5,
    max_history: int = 20,
    verbose: bool = False,
    return_ids_only: bool = False
) -> tuple[bool, Any]:
    """
    Call POST /recomandation/GenSar with given user and parameters.

    Returns:
        (success: bool, message: Any)

        On success (success=True), message is:
        {
          "username": str,
          "count": int,
          "recommendations": [
            {
              "game_id": str,
              "name": str,
              "game_idx": int,
              "hamming_dist": int
            },
            ...
          ]
        }

        On failure (success=False), message is typically a string error message.
    """
    payload: Dict[str, Any] = {
        "username": username,
        "top_k": top_k,
        "max_history": max_history,
    }

    try:
        resp = requests.post(
            f"{BASE_URL}/recomandation/GenSar",
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()

        data = resp.json()
        status = data.get("Status")
        message = data.get("message")

        if status is True:
            if verbose:
                print(
                    f"✅ /recomandation/GenSar OK. "
                    f"User={message.get('username')} "
                    f"Recommendations={message.get('count', 0)}"
                )
            games = [game_id.get("game_id", []) for game_id in message]
            if return_ids_only:
                return True, games
            else:
                return get_games_info(games)
        else:
            if verbose:
                print("❌ /recomandation/GenSar reported a problem:", message)
            return False, message

    except Exception as e:
        if verbose:
            print("❌ /recomandation/GenSar failed:", e)
        return False, str(e)

def recomandation_genral_connector(
    username: str,
    top_k_Gensar: int = 12,
    top_k_NLGCL: int = 200,
    max_history: int = 20,
    verbose: bool = False
    ) -> List[Any]:

    global_reco=[]

    NLGCL_reco=get_user_recommendation(username,top_k_NLGCL,return_ids_only=True)[1]

    gensar_ids=gensar_recommendation_connector(username,top_k_Gensar,max_history,verbose,return_ids_only=True)[1]
    global_reco = [item for item in NLGCL_reco if item in gensar_ids]
    NLGCL_set = set(NLGCL_reco)
    gensar_set = set(gensar_ids)
    
    remaining_gensar_ids = list(gensar_set - NLGCL_set)
    
    global_reco = global_reco + remaining_gensar_ids

    return get_games_info(global_reco)