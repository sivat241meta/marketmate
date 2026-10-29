"""Modal deployment: one container serving the FastAPI app, Volume at /data."""

import modal

app = modal.App("marketmate")

# add_local_dir stays last: it ships the whole app/ tree (templates, static
# files, fonts), not just .py files.
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install(
        "ffmpeg",
        "libpango-1.0-0",
        "libpangoft2-1.0-0",
        "fonts-dejavu-core",
        "fonts-noto-core",
        "fonts-noto-cjk",
    )
    .pip_install_from_pyproject("pyproject.toml")
    # SAM 3.1 wire-format decoder (also pinned in pyproject.toml).
    .pip_install("meta-sam-parser==0.1.0")
    .env({"DATA_DIR": "/data", "MARKETMATE_ON_MODAL": "1"})
    .add_local_dir("app", remote_path="/root/app")
)

volume = modal.Volume.from_name("marketmate-data", create_if_missing=True)
secret = modal.Secret.from_name("marketmate-secrets")


# max_containers=1: processing threads run in this one container so SQLite has a single writer.
@app.function(
    image=image,
    volumes={"/data": volume},
    secrets=[secret],
    max_containers=1,
    scaledown_window=1200,
    timeout=900,
)
@modal.concurrent(max_inputs=50)
@modal.asgi_app()
def web():
    from app.config import load_settings
    from app.web.main import create_app

    return create_app(load_settings())
