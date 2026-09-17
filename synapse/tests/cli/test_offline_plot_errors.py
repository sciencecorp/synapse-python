from types import SimpleNamespace

from synapse.cli import offline_plot


def plot_args(**overrides):
    values = {
        "data": None,
        "config": None,
        "time": None,
        "channels": None,
        "dir": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_missing_data_file_is_reported_before_initializing_qt(monkeypatch, capsys):
    monkeypatch.setattr(
        offline_plot.QtWidgets.QApplication,
        "instance",
        lambda: (_ for _ in ()).throw(AssertionError("Qt should not initialize")),
    )

    result = offline_plot.plot(plot_args(data="asdfsadf"))

    assert result is False
    assert "Error: Data file not found: asdfsadf" in capsys.readouterr().out


def test_legacy_data_requires_configuration(monkeypatch, tmp_path, capsys):
    data_file = tmp_path / "recording.dat"
    data_file.touch()
    monkeypatch.setattr(
        offline_plot.QtWidgets.QApplication,
        "instance",
        lambda: (_ for _ in ()).throw(AssertionError("Qt should not initialize")),
    )

    result = offline_plot.plot(plot_args(data=str(data_file)))

    assert result is False
    output = capsys.readouterr().out
    assert "Legacy recordings require a configuration file" in output
    assert "NoneType" not in output
