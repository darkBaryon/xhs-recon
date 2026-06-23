def test_package_imports():
    import src  # noqa: F401
    import src.adapters  # noqa: F401
    import src.core  # noqa: F401
    import src.pipelines  # noqa: F401
