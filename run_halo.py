import argparse
import os
import re
import sys
import threading
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))                            # ok.py interface
sys.path.insert(0, str(REPO_ROOT / "load_intan_rhd_format"))  # intan read rhd lib

import ok
from intanutil.header import read_header
from intanutil.data import calculate_data_size, read_all_data_blocks, check_end_of_file

# --- Opal Kelly Documentation Portal (USB 3.0 HDL) -----------
# Manual: https://docs.opalkelly.com/fphdl/frontpanel-hdl-usb-3-0/)
PIPE_IN_ADDR, PIPE_OUT_ADDR = 0x80, 0xA0
WIREIN_CTRL = 0x00
WIREIN_TS_LO, WIREIN_TS_HI = 0x01, 0x02
WIREIN_THRESHOLD, WIREIN_WINDOW_TIMEOUT, WIREIN_TRANSITION_COUNT = 0x03, 0x04, 0x05

# --- FPGA Interface Constants --------------------------------
SAMPLES_PER_CHUNK = 128       # Intan USB block size (see specs)
SAMPLE_SIZE_BYTES = 4         # one 32-bit word per (channel, sample)
FIFO_OUT_DEPTH = 1024
DRAIN_BUFFER_SIZE = FIFO_OUT_DEPTH * SAMPLE_SIZE_BYTES
EVENT_NAMES = {1: "START", 2: "END"}
ADC_MIDPOINT = 32768


def discover_rhd_files(input_path: str) -> list[str]:
    """
    Input: RHD Folder. 
    Output: Array RHD Files.
    """
    path = Path(input_path)
    if path.is_file():
        return [str(path)]
    files = sorted(path.glob("*.rhd"),
                    key=lambda f: int(m.group(1)) if (m := re.search(r"_(\d+) hr", f.name)) else 0)
    if not files:
        raise FileNotFoundError(f"No .rhd files found in {input_path}")
    return [str(f) for f in files]


def read_raw_adc_codes(rhd_path: str) -> np.ndarray:
    """
    Input: RHD File Path.
    Output: Neural Data.
    Depend: Intan RHD Parser.
    """
    with open(rhd_path, "rb") as fid:
        header = read_header(fid)
        data_present, filesize, num_blocks, num_samples = calculate_data_size(
            header, rhd_path, fid)
        if not data_present:
            raise ValueError(f"No data in {rhd_path}")
        data = read_all_data_blocks(header, num_samples, num_blocks, fid)
        check_end_of_file(filesize, fid)
    return data["amplifier_data"].astype(np.uint16)


def build_chunks(codes: np.ndarray) -> list[bytes]:
    """
    Input: Raw RHD Neural Data.
    Output: FPGA Formated FIFO 128 Sample Chunks.
    FPGA Interface: channel_id[21:16] | adc_code[15:0].
    Endian: little-endian (Opal Kelly FrontPanel User's Manual).
    Manual: https://forums.opalkelly.com/t/pipein-endian-ness/1019
    Bug Fixed: channel-major.
    """
    num_channels, num_samples = codes.shape
    pad = (-num_samples) % SAMPLES_PER_CHUNK
    if pad: # if not multiple of, pad rest with the ADC midpoint
        codes = np.pad(codes, ((0, 0), (0, pad)), constant_values=ADC_MIDPOINT)
    ch_ids = (np.arange(num_channels, dtype=np.uint32) << 16)[:, None] # [21:16]
    chunks = []
    for c in range(codes.shape[1] // SAMPLES_PER_CHUNK):
        block = codes[:, c * SAMPLES_PER_CHUNK:(c + 1) * SAMPLES_PER_CHUNK].astype(np.uint32)
        chunks.append((ch_ids | block).astype("<u4").tobytes()) # [15:0]
    return chunks


def pad16(data: bytes) -> bytes:
    rem = len(data) % 16
    return data if rem == 0 else data + bytes(16 - rem)


class HaloRunner:
    """Send/Receive/Log"""

    def __init__(self, dev, stop_event: threading.Event):
        self.dev = dev
        self.stop_event = stop_event
        # FPGA Output: (event_code [31:30], channel [29:25], timestamp [24:0])
        # event_code = 0 (SEIZURE END)
        # event_code = 1 (SEIZURE START)
        self.events: list[tuple[int, int, int]] = []
        self.lock = threading.Lock()

    def sender(self, chunks: list[bytes]):
        for chunk in chunks:
            if self.dev.WriteToPipeIn(PIPE_IN_ADDR, bytearray(pad16(chunk))) < 0:
                raise RuntimeError("WriteToPipeIn failed")
        self.stop_event.set()

    def receiver(self, drain_grace_s: float = 1.0):
        while not self.stop_event.is_set():
            self._drain_once()
            time.sleep(0.05)
        time.sleep(drain_grace_s)
        self._drain_once()

    def _drain_once(self):
        buf = self.dev.ReadFromPipeOut(PIPE_OUT_ADDR, DRAIN_BUFFER_SIZE)
        for i in range(0, len(buf) - 3, 4): # for each word
            word = int.from_bytes(buf[i:i + 4], "little") # OK defined
            event_code, channel = (word >> 30) & 0x3, (word >> 25) & 0x1F
            timestamp = word & 0x01FFFFFF # [24:0]
            if event_code:
                with self.lock:
                    self.events.append((event_code, channel, timestamp))


def main():
    p = argparse.ArgumentParser(description="RHD to FPGA")
    p.add_argument("rhd_path", help="Path to a .rhd file or a folder")
    p.add_argument("--bitfile", default=str(REPO_ROOT / "First.bit"))
    p.add_argument("--serial", default=None, help="Opal Kelly Device Serial")
    p.add_argument("--threshold", type=int, default=25000, help="NEO threshold")
    p.add_argument("--window-timeout", type=int, default=200, help="No-detection samples before ending seizure")
    p.add_argument("--transition-count", type=int, default=30, help="Detections to start seizure within timeout")
    args = p.parse_args()

    # Read RHD + Form FPGA Chunks
    rhd_files = discover_rhd_files(args.rhd_path)
    print(f"[RHD] Reading {len(rhd_files)} file(s) from {args.rhd_path} ...")
    codes = np.concatenate([read_raw_adc_codes(f) for f in rhd_files], axis=1)
    chunks = build_chunks(codes)
    print(f"[RHD] {codes.shape[0]} channels x {codes.shape[1]} samples -> {len(chunks)} chunks")

    # Detect FPGA + Load Bitstream
    dev = ok.okCFrontPanel()
    if dev.GetDeviceCount() <= 0:
        sys.exit("ERROR: no Opal Kelly device found")
    serial = args.serial or dev.GetDeviceListSerial(0)
    if dev.OpenBySerial(serial) != ok.okCFrontPanel.NoError:
        sys.exit(f"ERROR: OpenBySerial({serial}) failed")
    if dev.ConfigureFPGA(os.path.abspath(args.bitfile)) != ok.okCFrontPanel.NoError:
        sys.exit(f"ERROR: ConfigureFPGA({args.bitfile}) failed")

    # Configure Bitstream
    dev.SetWireInValue(WIREIN_THRESHOLD, args.threshold, 0xFFFFFFFF)
    dev.SetWireInValue(WIREIN_WINDOW_TIMEOUT, args.window_timeout, 0xFFFFFFFF)
    dev.SetWireInValue(WIREIN_TRANSITION_COUNT, args.transition_count, 0xFFFFFFFF)
    ts = int(time.time()) # timestamp chunks
    dev.SetWireInValue(WIREIN_TS_LO, ts & 0xFFFFFFFF, 0xFFFFFFFF)
    dev.SetWireInValue(WIREIN_TS_HI, (ts >> 32) & 0xFFFFFFFF, 0xFFFFFFFF)
    dev.UpdateWireIns() # flush

    # Reset Detector Registers
    dev.SetWireInValue(WIREIN_CTRL, 0x8000_0000, 0xFFFFFFFF)  # pulse reset on
    dev.UpdateWireIns() # flush
    dev.SetWireInValue(WIREIN_CTRL, 0x0000_0000, 0xFFFFFFFF)  # pulse reset off
    dev.UpdateWireIns() # flush

    stop_event = threading.Event()
    runner = HaloRunner(dev, stop_event)

    # Sender & Receiver
    t_send = threading.Thread(target=runner.sender, args=(chunks,))
    t_recv = threading.Thread(target=runner.receiver)
    t_send.start()
    t_recv.start()
    t_send.join()
    t_recv.join()

    # Count Detections
    starts = sum(1 for e in runner.events if e[0] == 1)
    ends = sum(1 for e in runner.events if e[0] == 2)

    # Log Detections
    print(f"[DONE] {len(runner.events)} events ({starts} starts, {ends} ends)")
    for event_code, channel, timestamp in runner.events:
        print(f"  ch{channel:2d}  {EVENT_NAMES[event_code]:5s}  t={timestamp}")

if __name__ == "__main__":
    main()
