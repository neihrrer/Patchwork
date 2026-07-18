from imagemagick.filters import get_builtin_filters


class TestGetBuiltinFilters:
    def test_returns_list(self):
        filters = get_builtin_filters()
        assert len(filters) > 0

    def test_all_have_engine_imagemagick(self):
        filters = get_builtin_filters()
        for fd in filters:
            assert fd.engine == "imagemagick", f"{fd.name} has wrong engine"

    def test_all_have_category(self):
        filters = get_builtin_filters()
        for fd in filters:
            assert len(fd.category) > 0, f"{fd.name} has no category"

    def test_all_have_name(self):
        filters = get_builtin_filters()
        for fd in filters:
            assert fd.name, f"Filter missing name"
            assert fd.display_name, f"Filter {fd.name} missing display_name"

    def test_all_have_parameters(self):
        filters = get_builtin_filters()
        for fd in filters:
            param_count = len(fd.parameters)
            assert param_count > 0 or fd.category == ["Blend"], \
                f"{fd.name} has no parameters"

    def test_common_filter_names_present(self):
        filters = get_builtin_filters()
        names = {f.name for f in filters}
        common = {"blur", "sharpen", "grayscale", "sepia", "rotate",
                   "resize_pct", "charcoal"}
        present = common & names
        assert len(present) >= 5, f"Only found {len(present)} common filters in {len(names)}"

    def test_parameter_constraints(self):
        filters = get_builtin_filters()
        for fd in filters:
            for p in fd.parameters:
                assert p.kind in ("int", "float", "bool", "choice", "color", "text"), \
                    f"{fd.name}.{p.name} has unknown kind {p.kind}"
                if p.min_val is not None and p.max_val is not None:
                    assert p.min_val <= p.max_val, \
                        f"{fd.name}.{p.name}: min > max"
