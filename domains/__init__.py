from pathlib import Path

DOMAINS_DIR = Path(__file__).parent


def list_domains() -> list[str]:
    """
    Trả về danh sách domain hợp lệ có thư mục config.
    """
    return sorted(
        d.name
        for d in DOMAINS_DIR.iterdir()
        if d.is_dir()
        and not d.name.startswith("__")
        and (d / "config.yaml").exists()
    )