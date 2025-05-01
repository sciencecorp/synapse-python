# Changelog

All notable changes to this project will be documented in this file. See [standard-version](https://github.com/conventional-changelog/standard-version) for commit guidelines.

## [2.2.0](https://github.com/sciencecorp/synapse-python/compare/v2.1.0...v2.2.0) (2025-05-01)


### Features

* Fix issue where uri is forgotten ([#104](https://github.com/sciencecorp/synapse-python/issues/104)) ([c84a88a](https://github.com/sciencecorp/synapse-python/commit/c84a88a949bec74c57f532696148b952de6434f7))
* populate synapse_api_version DeviceInfo field in server ([#94](https://github.com/sciencecorp/synapse-python/issues/94)) ([20b0aea](https://github.com/sciencecorp/synapse-python/commit/20b0aeaf37776c9aebdca9420172cca13f87184f))


### Bug Fixes

* fix issue with LogLevel type annotation on certain client device methods ([#105](https://github.com/sciencecorp/synapse-python/issues/105)) ([e0bc439](https://github.com/sciencecorp/synapse-python/commit/e0bc439b7df613abbad87e7039ce18636a501170))

## [2.1.0](https://github.com/sciencecorp/synapse-python/compare/v2.0.0...v2.1.0) (2025-04-24)


### Features

* add `get_last_sync_time_ns` to TimeSyncClient ([#102](https://github.com/sciencecorp/synapse-python/issues/102)) ([90a7ffc](https://github.com/sciencecorp/synapse-python/commit/90a7ffcb4e889d79a0d2fbe1127a6f2fa2186f82))
* support streaming device queries ([#95](https://github.com/sciencecorp/synapse-python/issues/95)) ([e45e5f5](https://github.com/sciencecorp/synapse-python/commit/e45e5f5d9808445ec34acd0caee86ab5440039e6))

## [2.0.0](https://github.com/sciencecorp/synapse-python/compare/v1.0.2...v2.0.0) (2025-04-21)


### ⚠ BREAKING CHANGES

* add SpikeDetector, SpikeBinner nodes to client; remove
SpikeDetect node from client and server

### Features

* add SpikeDetector, SpikeBinner nodes; remove SpikeDetect node ([#99](https://github.com/sciencecorp/synapse-python/issues/99)) ([2a6c029](https://github.com/sciencecorp/synapse-python/commit/2a6c02919dc87e96d410a41f8761919922d6604b))
* add TimeSyncClient ([#101](https://github.com/sciencecorp/synapse-python/issues/101)) ([9f89ee3](https://github.com/sciencecorp/synapse-python/commit/9f89ee33a37cd18447aced3d2b023ec738be803b))
* support new channel mapping header ([#93](https://github.com/sciencecorp/synapse-python/issues/93)) ([aef46c8](https://github.com/sciencecorp/synapse-python/commit/aef46c8ecbd48c5c831a7b99c4d2c787e52aa6fd))
* allow users to search by name or ip ([#100](https://github.com/sciencecorp/synapse-python/issues/100)) ([7eb7e42](https://github.com/sciencecorp/synapse-python/commit/7eb7e427a4129164b79a1562d11354ff2227f0c1))

### [1.0.2](https://github.com/sciencecorp/synapse-python/compare/v1.0.1...v1.0.2) (2025-04-07)

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
