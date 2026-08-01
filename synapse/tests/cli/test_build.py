import os

from synapse.cli.build import (
    _app_lib_parts,
    app_lib_device_path,
    app_lib_staging_dir,
    render_service_unit,
)


def test_app_lib_parts_returns_expected_segments():
    assert _app_lib_parts("myapp") == ["opt", "scifi", "apps", "myapp", "lib"]


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


def test_app_lib_staging_dir_is_per_app_not_shared_lib_dir():
    staging = "/tmp/stg"
    result = app_lib_staging_dir(staging, "myapp")
    # Positive: it is the per-app dir...
    assert result == os.path.join(staging, "opt", "scifi", "apps", "myapp", "lib")
    # ...and negative: it is NOT the old shared /opt/scifi/lib path.
    assert result != os.path.join(staging, "opt", "scifi", "lib")


def test_service_unit_puts_app_lib_dir_first_on_ld_library_path():
    unit = render_service_unit("myapp")
    assert (
        "Environment=LD_LIBRARY_PATH="
        "/opt/scifi/apps/myapp/lib:/opt/scifi/usr-libs:/opt/scifi/lib" in unit
    )


def test_service_unit_execstart_points_at_app_binary():
    unit = render_service_unit("myapp")
    assert "ExecStart=/opt/scifi/bin/myapp" in unit


def test_service_unit_keeps_sysctl_execstartpre_hooks():
    unit = render_service_unit("myapp")
    assert "ExecStartPre=/sbin/sysctl -w net.core.wmem_max=4194304" in unit
    assert "ExecStartPre=/sbin/sysctl -w net.core.wmem_default=4194304" in unit


def test_service_unit_ld_path_matches_device_path_helper():
    unit = render_service_unit("synapse-example-app")
    assert app_lib_device_path("synapse-example-app") + ":" in unit
