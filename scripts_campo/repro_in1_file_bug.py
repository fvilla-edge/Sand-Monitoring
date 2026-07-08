#!/usr/bin/env python3
"""
Minimal reproduction script for the IN1 / FILE-mode "artifact" reported to
Red Pitaya (github.com/RedPitaya/RedPitaya/issues/337).

RESOLVED: this is not a hardware or streaming bug. The periodic bursts this
script detects are header bytes of the segmented .bin format being
misread as raw samples -- see `analisis/revisar.py::_leer_canales_bin` for
the correct parser. This script intentionally still reads the file as raw
int16 (no header parsing) to reproduce the original symptom for reference.

Run directly on the board (needs streaming-server running and the
rpsa_client python_lib on sys.path). Only channel 1 is enabled.

    python3 repro_in1_file_bug.py
"""
import sys
import os
import threading

import numpy as np

sys.path.insert(0, '/root/rpsa_client/python_lib')
import streaming

STREAM_DIR = '/home/redpitaya/streaming_files/adc'   # FILE mode always writes here first
DECIMATION = 32          # reproduces identically with 64
DURATION_S = 3.0         # seconds of IN1 data to capture
FS_BASE    = 125_000_000
BAD_CODE   = -25910      # fixed raw int16 code seen in every period


def capture_to_sd():
    fs_eff = FS_BASE / DECIMATION
    n_samples = int(fs_eff * DURATION_S)

    done = threading.Event()
    error = [None]

    class ADC_CB(streaming.ADCCallback):
        def receivePack(self, c, n): pass
        def connected(self, c, h): pass
        def disconnected(self, c, h): pass
        def error(self, c, h, code):
            error[0] = f'error code={code}'
            done.set()

    class Config_CB(streaming.ConfigCallback):
        def adcServerStoppedNoActiveChannels(self, c, h):
            error[0] = 'no-active-channels'; done.set()
        def adcServerStoppedMemError(self, c, h):
            error[0] = 'mem-error'; done.set()
        def adcServerStoppedSDFull(self, c, h):
            error[0] = 'sd-full'; done.set()
        def adcServerStoppedSDDone(self, c, h):
            done.set()

    confObj = streaming.ConfigStreamClient()
    adcObj  = streaming.ADCStreamClient(confObj)
    confObj.setVerbose(False)
    adcObj.setVerbose(False)

    if not confObj.connect():
        sys.exit('ERROR: could not connect to streaming-server')

    cfg_cb = Config_CB()
    confObj.addCallback(cfg_cb)
    adc_cb = ADC_CB()
    adcObj.setCallback(adc_cb)

    confObj.sendConfig('adc_pass_mode',        'FILE')
    confObj.sendConfig('adc_decimation',       str(DECIMATION))
    confObj.sendConfig('channel_attenuator_1', 'A_1_20')   # HV jumper installed
    confObj.sendConfig('channel_state_1',      'ON')
    confObj.sendConfig('channel_state_2',      'OFF')
    confObj.sendConfig('samples_limit_sd',     str(n_samples))

    if not adcObj.startStreaming():
        sys.exit('ERROR: startStreaming failed')

    completed = done.wait(timeout=DURATION_S + 30)
    confObj.removeCallback(cfg_cb)
    adcObj.removeCallback()

    if not completed:
        sys.exit('ERROR: timed out waiting for the SD write to finish')
    if error[0]:
        sys.exit(f'ERROR: streaming error: {error[0]}')

    files = sorted(f for f in os.listdir(STREAM_DIR)
                    if f.startswith('data_file_') and f.endswith('.bin'))
    if not files:
        sys.exit('ERROR: no output file produced in ' + STREAM_DIR)
    return os.path.join(STREAM_DIR, files[-1]), fs_eff, n_samples


def analyze(path):
    """
    Detects the periodic out-of-range bursts on IN1 by amplitude threshold
    (works at any decimation -- the exact BAD_CODE value is only reliably
    seen at decimation=32; at other decimations the burst amplitude varies
    slightly, presumably softened by the decimation filter).
    """
    raw = np.fromfile(path, dtype='<i2')
    threshold_v = 15.0
    threshold_code = threshold_v / 20.0 * 32767

    idx_peak = np.where(np.abs(raw.astype(np.int64)) > threshold_code)[0]
    n_bad = int(np.count_nonzero(raw == BAD_CODE))

    print(f'file: {path}')
    print(f'samples: {len(raw)}   min={raw.min()}  max={raw.max()}')
    print(f'samples above {threshold_v:.0f} V: {len(idx_peak)}')
    print(f'exact occurrences of code {BAD_CODE} ({BAD_CODE / 32767 * 20:.4f} V at HV): {n_bad} '
          f'(reliably seen at decimation=32 in our tests; not necessarily at other decimations)')

    if len(idx_peak) < 2:
        print('not enough samples above threshold to measure periodicity')
        return

    diffs = np.diff(idx_peak)
    # Each period packs several separate bursts within a ~50-100 sample
    # window (not one single burst) -- collapse everything within 200
    # samples into one event, keeping its first sample index.
    events = idx_peak[np.concatenate(([True], diffs > 200))]
    print(f'distinct periodic events: {len(events)}')
    if len(events) > 1:
        period = np.diff(events)
        print(f'spacing between events (samples): min={period.min()} max={period.max()} '
              f'mean={period.mean():.1f}')


def main():
    print(f'Python: {sys.version}')
    print(f'decimation={DECIMATION}  duration_s={DURATION_S}')
    path, fs_eff, n_samples = capture_to_sd()
    print(f'captured {n_samples} samples @ fs={fs_eff / 1e6:.4f} MHz -> {path}')
    analyze(path)


if __name__ == '__main__':
    main()
