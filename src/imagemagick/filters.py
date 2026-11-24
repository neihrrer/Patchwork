from models.filter import FilterDef, ParamDef, ParamKind, ENGINE_IMAGEMAGICK

BUILTIN_FILTERS: list[FilterDef] = [
    FilterDef(
        name="blur",
        display_name="Gaussian Blur",
        category=["Blur"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="radius", label="Radius", kind=ParamKind.FLOAT, default=3.0, min_val=0.0, max_val=100.0),
            ParamDef(name="sigma", label="Sigma", kind=ParamKind.FLOAT, default=1.0, min_val=0.0, max_val=50.0),
        ],
        gmic_command="blur",
    ),
    FilterDef(
        name="motion_blur",
        display_name="Motion Blur",
        category=["Blur"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="radius", label="Radius", kind=ParamKind.FLOAT, default=10.0, min_val=0.0, max_val=100.0),
            ParamDef(name="sigma", label="Sigma", kind=ParamKind.FLOAT, default=3.0, min_val=0.0, max_val=50.0),
            ParamDef(name="angle", label="Angle", kind=ParamKind.FLOAT, default=45.0, min_val=0.0, max_val=360.0),
        ],
        gmic_command="motion_blur",
    ),
    FilterDef(
        name="radial_blur",
        display_name="Radial Blur",
        category=["Blur"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="angle", label="Angle", kind=ParamKind.FLOAT, default=15.0, min_val=0.0, max_val=360.0),
        ],
        gmic_command="radial_blur",
    ),
    FilterDef(
        name="median",
        display_name="Median Filter",
        category=["Blur"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="radius", label="Radius", kind=ParamKind.FLOAT, default=3.0, min_val=0.0, max_val=50.0),
        ],
        gmic_command="median",
    ),
    FilterDef(
        name="sharpen",
        display_name="Sharpen",
        category=["Sharpen"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="radius", label="Radius", kind=ParamKind.FLOAT, default=2.0, min_val=0.0, max_val=50.0),
            ParamDef(name="sigma", label="Sigma", kind=ParamKind.FLOAT, default=1.0, min_val=0.0, max_val=50.0),
        ],
        gmic_command="sharpen",
    ),
    FilterDef(
        name="unsharp",
        display_name="Unsharp Mask",
        category=["Sharpen"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="radius", label="Radius", kind=ParamKind.FLOAT, default=3.0, min_val=0.0, max_val=50.0),
            ParamDef(name="sigma", label="Sigma", kind=ParamKind.FLOAT, default=1.0, min_val=0.0, max_val=50.0),
            ParamDef(name="amount", label="Amount", kind=ParamKind.FLOAT, default=1.0, min_val=0.0, max_val=10.0),
            ParamDef(name="threshold", label="Threshold", kind=ParamKind.FLOAT, default=0.0, min_val=0.0, max_val=1.0),
        ],
        gmic_command="unsharp",
    ),
    FilterDef(
        name="adaptive_sharpen",
        display_name="Adaptive Sharpen",
        category=["Sharpen"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="radius", label="Radius", kind=ParamKind.FLOAT, default=2.0, min_val=0.0, max_val=50.0),
            ParamDef(name="sigma", label="Sigma", kind=ParamKind.FLOAT, default=1.0, min_val=0.0, max_val=50.0),
        ],
        gmic_command="adaptive_sharpen",
    ),
    FilterDef(
        name="resize_pct",
        display_name="Resize (Percent)",
        category=["Resize"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="width", label="Width %", kind=ParamKind.FLOAT, default=50.0, min_val=1.0, max_val=200.0),
            ParamDef(name="height", label="Height %", kind=ParamKind.FLOAT, default=50.0, min_val=1.0, max_val=200.0),
        ],
        gmic_command="resize_pct",
    ),
    FilterDef(
        name="resize_px",
        display_name="Resize (Pixels)",
        category=["Resize"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="width", label="Width", kind=ParamKind.INT, default=800, min_val=1, max_val=10000),
            ParamDef(name="height", label="Height", kind=ParamKind.INT, default=600, min_val=1, max_val=10000),
        ],
        gmic_command="resize_px",
    ),
    FilterDef(
        name="rotate",
        display_name="Rotate",
        category=["Rotate"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="degrees", label="Degrees", kind=ParamKind.FLOAT, default=90.0, min_val=-360.0, max_val=360.0),
        ],
        gmic_command="rotate",
    ),
    FilterDef(
        name="grayscale",
        display_name="Grayscale",
        category=["Colors"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="method", label="Method", kind=ParamKind.CHOICE, default=0, choices=["Rec709 Luminance", "Rec601 Luminance", "Average", "Brightness"]),
        ],
        gmic_command="grayscale",
    ),
    FilterDef(
        name="sepia",
        display_name="Sepia Tone",
        category=["Colors"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="threshold", label="Threshold %", kind=ParamKind.FLOAT, default=80.0, min_val=0.0, max_val=100.0),
        ],
        gmic_command="sepia",
    ),
    FilterDef(
        name="modulate",
        display_name="Modulate",
        category=["Colors"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="brightness", label="Brightness %", kind=ParamKind.FLOAT, default=100.0, min_val=0.0, max_val=300.0),
            ParamDef(name="saturation", label="Saturation %", kind=ParamKind.FLOAT, default=100.0, min_val=0.0, max_val=300.0),
            ParamDef(name="hue", label="Hue %", kind=ParamKind.FLOAT, default=100.0, min_val=0.0, max_val=300.0),
        ],
        gmic_command="modulate",
    ),
    FilterDef(
        name="level",
        display_name="Levels",
        category=["Colors"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="black", label="Black Point %", kind=ParamKind.FLOAT, default=0.0, min_val=0.0, max_val=100.0),
            ParamDef(name="white", label="White Point %", kind=ParamKind.FLOAT, default=100.0, min_val=0.0, max_val=100.0),
            ParamDef(name="gamma", label="Gamma", kind=ParamKind.FLOAT, default=1.0, min_val=0.1, max_val=10.0),
        ],
        gmic_command="level",
    ),
    FilterDef(
        name="contrast",
        display_name="Contrast",
        category=["Colors"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="enhance", label="Enhance", kind=ParamKind.BOOL, default=True),
        ],
        gmic_command="contrast",
    ),
    FilterDef(
        name="contrast_stretch",
        display_name="Contrast Stretch",
        category=["Colors"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="black", label="Black Point %", kind=ParamKind.FLOAT, default=2.0, min_val=0.0, max_val=50.0),
            ParamDef(name="white", label="White Point %", kind=ParamKind.FLOAT, default=2.0, min_val=0.0, max_val=50.0),
        ],
        gmic_command="contrast_stretch",
    ),
    FilterDef(
        name="canny_edge",
        display_name="Canny Edge Detection",
        category=["Edge Detect"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="radius", label="Radius", kind=ParamKind.FLOAT, default=1.0, min_val=0.0, max_val=50.0),
            ParamDef(name="sigma", label="Sigma", kind=ParamKind.FLOAT, default=1.0, min_val=0.0, max_val=10.0),
            ParamDef(name="lower", label="Lower Threshold %", kind=ParamKind.FLOAT, default=10.0, min_val=0.0, max_val=100.0),
            ParamDef(name="upper", label="Upper Threshold %", kind=ParamKind.FLOAT, default=30.0, min_val=0.0, max_val=100.0),
        ],
        gmic_command="canny_edge",
    ),
    FilterDef(
        name="edge_detect",
        display_name="Edge Detect",
        category=["Edge Detect"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="radius", label="Radius", kind=ParamKind.FLOAT, default=1.0, min_val=0.0, max_val=50.0),
        ],
        gmic_command="edge",
    ),
    FilterDef(
        name="charcoal",
        display_name="Charcoal Effect",
        category=["Artistic"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="radius", label="Radius", kind=ParamKind.FLOAT, default=2.0, min_val=0.0, max_val=20.0),
            ParamDef(name="sigma", label="Sigma", kind=ParamKind.FLOAT, default=1.0, min_val=0.0, max_val=10.0),
        ],
        gmic_command="charcoal",
    ),
    FilterDef(
        name="oil_paint",
        display_name="Oil Paint",
        category=["Artistic"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="radius", label="Radius", kind=ParamKind.FLOAT, default=3.0, min_val=0.0, max_val=20.0),
        ],
        gmic_command="oil",
    ),
    FilterDef(
        name="emboss",
        display_name="Emboss",
        category=["Artistic"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="radius", label="Radius", kind=ParamKind.FLOAT, default=1.0, min_val=0.0, max_val=20.0),
        ],
        gmic_command="emboss",
    ),
    FilterDef(
        name="vignette",
        display_name="Vignette",
        category=["Artistic"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="radius_x", label="Vignette X %", kind=ParamKind.FLOAT, default=10.0, min_val=0.0, max_val=49.0),
            ParamDef(name="radius_y", label="Vignette Y %", kind=ParamKind.FLOAT, default=10.0, min_val=0.0, max_val=49.0),
            ParamDef(name="softness", label="Softness", kind=ParamKind.FLOAT, default=3.0, min_val=0.0, max_val=50.0),
            ParamDef(name="shade", label="Shade", kind=ParamKind.CHOICE, default=0, choices=["Black", "White"]),
        ],
        gmic_command="vignette",
    ),
    FilterDef(
        name="add_noise",
        display_name="Add Noise",
        category=["Noise"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="type", label="Noise Type", kind=ParamKind.CHOICE, default=0, choices=["Uniform", "Gaussian", "Multiplicative", "Impulse", "Laplacian", "Poisson"]),
            ParamDef(name="amplitude", label="Amplitude", kind=ParamKind.FLOAT, default=0.1, min_val=0.0, max_val=1.0),
        ],
        gmic_command="add_noise",
    ),
    FilterDef(
        name="reduce_noise",
        display_name="Reduce Noise",
        category=["Noise"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="radius", label="Radius", kind=ParamKind.FLOAT, default=3.0, min_val=0.0, max_val=50.0),
        ],
        gmic_command="reduce_noise",
    ),
    FilterDef(
        name="dilate",
        display_name="Dilate",
        category=["Morphology"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="radius", label="Radius", kind=ParamKind.INT, default=3, min_val=1, max_val=50),
        ],
        gmic_command="dilate",
    ),
    FilterDef(
        name="erode",
        display_name="Erode",
        category=["Morphology"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="radius", label="Radius", kind=ParamKind.INT, default=3, min_val=1, max_val=50),
        ],
        gmic_command="erode",
    ),
    FilterDef(
        name="opening",
        display_name="Opening",
        category=["Morphology"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="radius", label="Radius", kind=ParamKind.INT, default=3, min_val=1, max_val=50),
        ],
        gmic_command="opening",
    ),
    FilterDef(
        name="closing",
        display_name="Closing",
        category=["Morphology"],
        engine=ENGINE_IMAGEMAGICK,
        parameters=[
            ParamDef(name="radius", label="Radius", kind=ParamKind.INT, default=3, min_val=1, max_val=50),
        ],
        gmic_command="closing",
    ),
]


def get_builtin_filters() -> list[FilterDef]:
    return BUILTIN_FILTERS
