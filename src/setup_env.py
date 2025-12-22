from pathlib import Path

ENV_PATH = Path(".env")

# Default keys/values to put in the .env file
DEFAULT_VARS = {
    "API_BASE_IP": "10.242.216.203",
    "API_BASE_PORT": "27099",
    "DB_USER": "user",
    "DB_PASSWORD": "pass",
    "DB_IP": "localhost",
    "DB_PORT": "27017",
    "DB_NAME": "Steam_Project",
}

def main():
    if ENV_PATH.exists():
        print(".env already exists. Not overwriting.")
        return

    print("Generating .env file...\n")

    lines = []
    # 1) Ask user for each default key (press Enter to keep default)
    for key, default in DEFAULT_VARS.items():
        user_val = input(f"{key} [{default}]: ").strip()
        value = user_val if user_val else default
        lines.append(f"{key}={value}")

    # 2) Let user add custom keys
    print("\nAdd extra key/value pairs (leave key empty to finish):")
    while True:
        key = input("KEY: ").strip()
        if not key:
            break
        value = input("VALUE: ").strip()
        lines.append(f"{key}={value}")

    # 3) Write to .env
    content = "\n".join(lines) + "\n"
    ENV_PATH.write_text(content, encoding="utf-8")

    print(f"\n.env created with {len(lines)} entries.")

if __name__ == "__main__":
    main()