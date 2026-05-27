import os

from synapse.cli.build import app_lib_device_path, app_lib_staging_dir


def test_app_lib_device_path_is_absolute_forward_slash():
    assert app_lib_device_path("myapp") == "/opt/scifi/apps/myapp/lib"


def test_app_lib_device_path_uses_app_name():
    assert app_lib_device_path("synapse-example-app") == (
        "/opt/scifi/apps/synapse-example-app/lib"
    )


def test_app_lib_staging_dir_joins_under_staging_root():
    staging = "/tmp/synapse-package-xyz"
    expected = os.path.join(staging, "opt", "scifi", "apps", "myapp", "lib")
    assert app_lib_staging_dir(staging, "myapp") == expected


def test_app_lib_staging_dir_is_not_the_shared_lib_dir():
    staging = "/tmp/stg"
    shared = os.path.join(staging, "opt", "scifi", "lib")
    assert app_lib_staging_dir(staging, "myapp") != shared
