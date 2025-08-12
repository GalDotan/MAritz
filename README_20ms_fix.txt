
This patch improves 20 ms cadence by:
- calling NetworkTableInstance.setUpdateRate(0.020)
- flushing after each frame (inst.flush())
- using a sleep-until loop with drift correction and a tiny busy-wait.
Replace your existing `python/publisher_process.py` with this one.
