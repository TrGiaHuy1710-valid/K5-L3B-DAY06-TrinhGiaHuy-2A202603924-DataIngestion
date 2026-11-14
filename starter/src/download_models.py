from pathlib import Path
from huggingface_hub import snapshot_download

MODEL_ID = "google/embeddinggemma-2"

# Thư mục hiện tại
PROJECT_DIR = Path.cwd()

# Folder lưu model trong project
MODEL_DIR = PROJECT_DIR / "models" / "embeddinggemma-2"

MODEL_DIR.mkdir(parents=True, exist_ok=True)

print(f"Current directory: {PROJECT_DIR}")
print(f"Downloading: {MODEL_ID}")
print(f"Destination: {MODEL_DIR}")

model_path = snapshot_download(
    repo_id=MODEL_ID,
    local_dir=str(MODEL_DIR),
)

print("\nDownload completed!")
print(f"Model saved at: {model_path}")