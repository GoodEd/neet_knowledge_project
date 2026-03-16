import os


def pytest_configure(config):
    os.environ["DATA_DIR"] = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "test_data")
    )
