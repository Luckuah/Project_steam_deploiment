# Steam Project: Analysis and Generation

## Authors
- Rémy Chen
- Pavan Wickramasinghage
- Hadrien Lagadec
- Lucas Lorang
- victor Papin


## Quick Start

Welcome to the Steam data analysis and generation project repository. This project is configured for easy deployment using Docker.

***warning:The project requires **45 GB** of total storage space.***

***The initial database operations (import and indexing) are intensive and can take up to **30 minutes** on a high-performance computer. **We have not tested the setup on configurations with less than 64 GB of RAM, and we strongly recommend a minimum of 64 GB of RAM** for running the application and its associated models efficiently.***

***For reference, with our specific high-end configuration (Ryzen 9 9950x3d, 192 GB RAM, and an RTX 5080), the complete application startup time, including all database processing, is approximately **15 minutes**.***

To ensure all large files are downloaded correctly, you must have Git Large File Storage (LFS) installed.

1. Prerequisites: Install Git LFS

Install Git LFS and initialize it:

```bash
git lfs install
```

2. Clone the Repository

Clone the repository:

``` bash
git clone https://github.com/NZ-Azurea/Project_steam.git
cd Project_steam
```

Execution via Docker (Recommended Method)

This method uses docker compose to build and run the application in a single step.

1. Build the Container

Build the Docker image.

``` bash
docker compose build --no-cache
```

2. Launch the Application

``` bash
docker compose up -d
```

Manual Execution (Troubleshooting)

If running via docker compose up encounters issues or to retrain the models.

1. Access the Container

Enter the Bash shell of the application container:

``` bash
docker exec -it steam_app bash
```

2. Run the Application

Once inside the container, grant execution rights and run the application with Uvicorn:

``` bash
chmod +x /start.sh
uv run uvicorn start.sh
```

To see the result. Go to your web-browser and write:

```bash
http://localhost:8501/
```


Local Development Setup (Without Docker)

***Warning: This setup is generally NOT RECOMMENDED for production and is provided for development or debugging purposes only. Use the Docker setup for the most stable and reproducible environment.***

To run the application directly on your host machine (as demonstrated by the `./start.sh` or `start.bat` script), you must manually ensure that all external dependencies and services are running and accessible.

You need the following prerequisites installed and running on your system:

  * **UV (Python Environment Manager)**
      * You need the **`uv`** tool (used for environment and dependency management).
  * **MongoDB Instance with autentification**
      * A local **MongoDB database instance** must be installed and running (accessible, typically on `localhost:27017`). The application relies on it for data persistence.

You also need to create the .venv  of python 3.13.7 and dowload the libraries:

For example Linux:

```bash
uv venv .venv -p cpython-3.13.7-linux-x86_64-gnu
uv pip install -r requirements.txt
```

For example windows:

```bash
uv venv .venv -p cpython-3.13.7-windows-x86_64-none
uv pip install -r requirements.txt
```

For other instance please refert to uv [documentation](https://docs.astral.sh/uv/)

Once these prerequisites are met, you can use the project's bootstrap script to finish the setup:

On Linux:

```bash
./start.sh
```

On Windows:

```bash
start.bat
```


