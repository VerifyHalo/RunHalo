# RunHalo

Streams `.rhd` recording(s) to the FPGA (macOS only).

```bash
python3 run_halo.py path/to/recordings/ --bitfile path/to/new.bit
```

## Interface

| Endpoint | Address | Format |
|---|---|---|
| WireIn | 0x00 | bit 31 = reset (pulsed) |
| WireIn | 0x01 / 0x02 | timestamp lo/hi (64-bit) |
| WireIn | 0x03 | NEO threshold (default 25000) |
| WireIn | 0x04 | window timeout, samples (default 200) |
| WireIn | 0x05 | transition count (default 30) |
| PipeIn | 0x80 | 32-bit words: `channel_id[21:16] \| adc_code[15:0]` |
| PipeOut | 0xA0 | 32-bit words: `event_code[31:30] \| channel[29:25] \| timestamp[24:0]` |

## Dependencies

`numpy`
`libokFrontPanel.dylib` (bundled, macOS only)
