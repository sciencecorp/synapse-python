# Changelog

All notable changes to this project will be documented in this file. See [standard-version](https://github.com/conventional-changelog/standard-version) for commit guidelines.

### [1.0.1](https://github.com/sciencecorp/synapse-python/compare/v1.0.0...v1.0.1) (2025-03-21)


### Bug Fixes

* fix missing import needed for impedance results saving ([#88](https://github.com/sciencecorp/synapse-python/issues/88)) ([3ee6af2](https://github.com/sciencecorp/synapse-python/commit/3ee6af2d6a3119337c16eab44ee8c80a14e099b4))

## [1.0.0](https://github.com/sciencecorp/synapse-python/compare/v0.11.0...v1.0.0) (2025-03-17)


### ⚠ BREAKING CHANGES

* upgrade StreamOut node to use UDP unicast

In preparation for switching to UDP unicast, we have updated the StreamOut configuration to support udp unicast

- Updates synapse api
- Modularizes packet loss/bitrate calculation in streaming
- Updates stream out to use Udp unicast

### Features

* add `logs` and `tail` cli, support GetLogs and TailLogs RPCs ([#70](https://github.com/sciencecorp/synapse-python/issues/70)) ([fac3df8](https://github.com/sciencecorp/synapse-python/commit/fac3df8922e0662b5659fd35a9a311da672931b7))
* add SFTP-based file handling implementation ([#74](https://github.com/sciencecorp/synapse-python/issues/74)) ([6d50716](https://github.com/sciencecorp/synapse-python/commit/6d5071643efade05da8310b56f74749bcbe47b56))
* upgrade to use udp unicast ([#73](https://github.com/sciencecorp/synapse-python/issues/73)) ([adca3c5](https://github.com/sciencecorp/synapse-python/commit/adca3c5caaba4a4e2878dd5f9b823787663fffcd))


### Bug Fixes

* fix issue with parsing configs with no electrode `id`, `electrode_id` ([#80](https://github.com/sciencecorp/synapse-python/issues/80)) ([f75a433](https://github.com/sciencecorp/synapse-python/commit/f75a433e151e9851f17c6e346db998e688be748e))
* Remove unused wifi configuration ([#81](https://github.com/sciencecorp/synapse-python/issues/81)) ([89af771](https://github.com/sciencecorp/synapse-python/commit/89af771b047b8cf4b0c1b8264118ab4416f55e0d))
* Updated real time plotter to use channel ids directly ([#85](https://github.com/sciencecorp/synapse-python/issues/85)) ([d6f0dd5](https://github.com/sciencecorp/synapse-python/commit/d6f0dd54fa597b3864304ed946d6b83cb8f5fee6))
* support new and old format of config in plotting ([#82](https://github.com/sciencecorp/synapse-python/pull/82)) ([27c5ff4](https://github.com/sciencecorp/synapse-python/pull/82/commits/27c5ff4279ba307b9555cf92c5ddbfbf2c04ac80))

## [0.11.0](https://github.com/sciencecorp/synapse-python/compare/v0.10.1...v0.11.0) (2025-03-10)


### Bug Fixes

* fix SignalConfig exports and StreamOut example ([#75](https://github.com/sciencecorp/synapse-python/issues/75)) ([50d12ad](https://github.com/sciencecorp/synapse-python/commit/50d12ad3586e73d4aec991d94e67108267435241))
