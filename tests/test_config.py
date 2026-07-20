import json

import pytest


class TestAppConfig:
    def test_defaults(self, tmp_path):
        config_path = tmp_path / "config.json"
        from config import AppConfig
        cfg = AppConfig(path=str(config_path))
        assert cfg.output_format == "png"
        assert cfg.processing_timeout == 60
        assert cfg.auto_save_interval == 0
        assert cfg.grid_visible is True
        assert cfg.snap_to_grid is False
        assert cfg.extended_zoom is False
        assert cfg.minimap_visible is False

    def test_round_trip(self, tmp_path):
        config_path = tmp_path / "config.json"
        from config import AppConfig
        cfg = AppConfig(path=str(config_path))
        cfg.output_format = "jpeg"
        cfg.auto_save_interval = 5
        cfg2 = AppConfig(path=str(config_path))
        assert cfg2.output_format == "jpeg"
        assert cfg2.auto_save_interval == 5

    def test_missing_file_uses_defaults(self, tmp_path):
        config_path = tmp_path / "nonexistent.json"
        from config import AppConfig
        cfg = AppConfig(path=str(config_path))
        assert cfg.output_format == "png"

    def test_partial_file_merges(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"output_format": "webp"}))
        from config import AppConfig
        cfg = AppConfig(path=str(config_path))
        assert cfg.output_format == "webp"
        assert cfg.processing_timeout == 60

    def test_corrupted_file_falls_back(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text("not valid json")
        from config import AppConfig
        cfg = AppConfig(path=str(config_path))
        assert cfg.output_format == "png"

    def test_attribute_access(self, tmp_path):
        config_path = tmp_path / "config.json"
        from config import AppConfig
        cfg = AppConfig(path=str(config_path))
        assert cfg.output_format == "png"
        with pytest.raises(AttributeError):
            _ = cfg.nonexistent_key

    def test_private_attr_bypasses_config(self, tmp_path):
        config_path = tmp_path / "config.json"
        from config import AppConfig
        cfg = AppConfig(path=str(config_path))
        cfg._custom = "value"
        assert cfg._custom == "value"

    def test_setattr_saves(self, tmp_path):
        config_path = tmp_path / "config.json"
        from config import AppConfig
        cfg = AppConfig(path=str(config_path))
        cfg.processing_timeout = 300
        saved = json.loads(config_path.read_text())
        assert saved["processing_timeout"] == 300

    def test_multiple_updates(self, tmp_path):
        config_path = tmp_path / "config.json"
        from config import AppConfig
        cfg = AppConfig(path=str(config_path))
        cfg.output_format = "tiff"
        cfg.grid_visible = False
        cfg.minimap_visible = True
        cfg2 = AppConfig(path=str(config_path))
        assert cfg2.output_format == "tiff"
        assert cfg2.grid_visible is False
        assert cfg2.minimap_visible is True
