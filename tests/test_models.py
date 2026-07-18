from models.filter import ParamKind, ParamDef, FilterDef, ENGINE_GMIC, ENGINE_IMAGEMAGICK
from models.app_state import VALID_OUTPUT_FORMATS


class TestParamKind:
    def test_constants(self):
        assert ParamKind.INT == "int"
        assert ParamKind.FLOAT == "float"
        assert ParamKind.BOOL == "bool"
        assert ParamKind.CHOICE == "choice"
        assert ParamKind.COLOR == "color"
        assert ParamKind.POINT == "point"
        assert ParamKind.TEXT == "text"
        assert ParamKind.FILE == "file"
        assert ParamKind.FOLDER == "folder"


class TestParamDef:
    def test_construction_minimal(self):
        p = ParamDef("x", "X Label")
        assert p.name == "x"
        assert p.label == "X Label"
        assert p.kind == ParamKind.FLOAT
        assert p.default is None
        assert p.min_val is None
        assert p.max_val is None
        assert p.choices == []
        assert p.is_hidden is False

    def test_construction_full(self):
        p = ParamDef("mode", "Mode", kind=ParamKind.CHOICE, default="over",
                      choices=["over", "multiply", "screen"])
        assert p.name == "mode"
        assert p.kind == "choice"
        assert p.default == "over"
        assert p.choices == ["over", "multiply", "screen"]

    def test_hidden_param(self):
        p = ParamDef("_internal", "Internal", is_hidden=True)
        assert p.is_hidden is True

    def test_numeric_range(self):
        p = ParamDef("radius", "Radius", kind=ParamKind.FLOAT,
                      default=5.0, min_val=0.0, max_val=100.0)
        assert p.min_val == 0.0
        assert p.max_val == 100.0

    def test_repr(self):
        p = ParamDef("x", "X", kind="int", default=42)
        r = repr(p)
        assert "x" in r
        assert "int" in r

    def test_choices_default_empty_list(self):
        p = ParamDef("x", "X")
        assert p.choices == []


class TestFilterDef:
    def test_construction_minimal(self):
        fd = FilterDef()
        assert fd.name == ""
        assert fd.display_name == ""
        assert fd.category == []
        assert fd.description == ""
        assert fd.parameters == []
        assert fd.gmic_command == ""
        assert fd.engine == ENGINE_GMIC
        assert fd.image_input_count == 1

    def test_construction_full(self):
        params = [ParamDef("p1", "Param 1")]
        fd = FilterDef(
            name="test_filter",
            display_name="Test Filter",
            category=["Test", "Sub"],
            description="A test filter",
            parameters=params,
            gmic_command="test_command",
            engine=ENGINE_IMAGEMAGICK,
            image_input_count=2,
        )
        assert fd.name == "test_filter"
        assert fd.display_name == "Test Filter"
        assert fd.category == ["Test", "Sub"]
        assert fd.description == "A test filter"
        assert fd.parameters == params
        assert fd.gmic_command == "test_command"
        assert fd.engine == "imagemagick"
        assert fd.image_input_count == 2

    def test_gobject_properties(self, filter_def):
        fd = filter_def
        assert fd.get_property("name") == "test_filter"
        assert fd.get_property("display_name") == "Test Filter"
        assert fd.get_property("description") == "A test filter"

    def test_property_setters(self):
        fd = FilterDef()
        fd.name = "new_name"
        fd.display_name = "New Name"
        fd.description = "New description"
        fd.gmic_command = "new_cmd"
        assert fd.name == "new_name"
        assert fd.display_name == "New Name"
        assert fd.description == "New description"
        assert fd.gmic_command == "new_cmd"

    def test_repr(self):
        fd = FilterDef(name="blur", engine=ENGINE_GMIC, category=["Blur"])
        r = repr(fd)
        assert "blur" in r
        assert "gmic" in r

    def test_engine_constants(self):
        assert ENGINE_GMIC == "gmic"
        assert ENGINE_IMAGEMAGICK == "imagemagick"

    def test_category_mutable(self):
        fd = FilterDef(category=["A"])
        fd.category.append("B")
        assert fd.category == ["A", "B"]

    def test_parameters_mutable(self):
        p1 = ParamDef("p1", "P1")
        fd = FilterDef(parameters=[p1])
        p2 = ParamDef("p2", "P2")
        fd.parameters.append(p2)
        assert len(fd.parameters) == 2


class TestAppState:
    def test_valid_output_formats(self):
        assert "png" in VALID_OUTPUT_FORMATS
        assert "jpeg" in VALID_OUTPUT_FORMATS
        assert "tiff" in VALID_OUTPUT_FORMATS
        assert "bmp" in VALID_OUTPUT_FORMATS
        assert "webp" in VALID_OUTPUT_FORMATS
        assert len(VALID_OUTPUT_FORMATS) == 5
