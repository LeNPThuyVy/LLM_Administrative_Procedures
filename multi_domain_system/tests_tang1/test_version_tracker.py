import pytest
from pathlib import Path
from ingestion.version_tracker import VersionTracker, VERSION_FILE

def test_version_tracker(tmp_path, monkeypatch):
    # Patch VERSION_FILE to use a temporary file
    temp_version_file = tmp_path / ".ingestion_versions.json"
    monkeypatch.setattr("ingestion.version_tracker.VERSION_FILE", temp_version_file)
    
    tracker = VersionTracker()
    
    # Create a test file
    sample_file = tmp_path / "sample.txt"
    sample_file.write_text("Nội dung ban đầu", encoding="utf-8")
    
    domain_id = "test_domain"
    
    # Before marking as indexed -> has_changed is True
    assert tracker.has_changed(domain_id, sample_file) is True
    
    # Mark as indexed
    tracker.mark_indexed(domain_id, sample_file)
    
    # Reload tracker to test persistence
    tracker_reloaded = VersionTracker()
    assert tracker_reloaded.has_changed(domain_id, sample_file) is False
    
    # Modify file
    sample_file.write_text("Nội dung đã được thay đổi!", encoding="utf-8")
    assert tracker_reloaded.has_changed(domain_id, sample_file) is True
