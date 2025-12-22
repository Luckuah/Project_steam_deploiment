import argparse
import os
import random
import string
import requests

BASE_URL = "http://10.242.216.203:27099"

def add_user(name: str, verbose: bool = False):
    try:
        resp = requests.post(f"{BASE_URL}/user", json={"name": name}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("Status")
        message = data.get("message")
        if status is True:
            if verbose: print("✅ /user create OK:", message)
            return message
        else:
            print("❌ /user create reported a problem:", message)
    except Exception as e:
        print("❌ /user create failed:", e)
def delete_user(name: str, verbose: bool = False):
    try:
        resp = requests.delete(f"{BASE_URL}/user", json={"name": name}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("Status")
        message = data.get("message")
        if status is True:
            if verbose: print("✅ /user delete OK:", message)
            return message
        else:
            print("❌ /user delete reported a problem:", message)
    except Exception as e:
        print("❌ /user delete failed:", e)
def rename_user(old_name: str, new_name: str, verbose: bool = False):
    try:
        payload = {"old_name": old_name, "new_name": new_name}
        resp = requests.patch(f"{BASE_URL}/user", json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("Status")
        message = data.get("message")
        if status is True:
            if verbose: print("✅ /user rename OK:", message)
            return message
        else:
            print("❌ /user rename reported a problem:", message)
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
            return message
        else:
            print("❌ /user fetch reported a problem:", message)

    except Exception as e:
        print("❌ /user fetch failed:", e)

def rand_suffix(n=5):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))

def main():
    parser = argparse.ArgumentParser(description="Smoke test /user endpoints")
    parser.add_argument("--base-url", default=os.getenv("API_BASE_URL", "http://10.242.216.203:27099"),
                        help="API base URL (default: http://localhost:8000)")
    parser.add_argument("--name", default="alice", help="Base username to test with")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    global BASE_URL
    BASE_URL = args.base_url

    base_name = args.name + "_" + rand_suffix()
    renamed = base_name + "_renamed"

    print(f"🔧 Using BASE_URL={BASE_URL}")
    print(f"🧪 Will create user: {base_name}")
    print("-" * 60)

    # 1) Add user (expect success)
    print("[1] Add user (expect success)")
    add_user(base_name, verbose=args.verbose)

    # 2) Get user (should exist)
    print("\n[2] Get existing user")
    doc = get_user_by_name(base_name, verbose=args.verbose)
    print("   fetched:", doc)
    
    # 2) Add same user again (expect failure)
    print("\n[2] Add same user again (expect failure)")
    add_user(base_name, verbose=args.verbose)

    # 3) Rename user to new name (expect success)
    print("\n[3] Rename user (expect success)")
    rename_user(base_name, renamed, verbose=args.verbose)

    # 4) Rename non-existing old name (expect failure)
    print("\n[4] Rename non-existing old name (expect failure)")
    rename_user(base_name, base_name + "_x", verbose=args.verbose)

    # # 5) Delete renamed user (expect success)
    # print("\n[5] Delete renamed user (expect success)")
    # delete_user(renamed, verbose=args.verbose)

    # # 6) Delete again (expect failure)
    # print("\n[6] Delete again (expect failure)")
    # delete_user(renamed, verbose=args.verbose)

    print("\n✅ Test script finished.")

if __name__ == "__main__":
    main()