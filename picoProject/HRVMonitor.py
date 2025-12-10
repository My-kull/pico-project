# HRV Monitor - Heart Rate Variability Analysis

import machine
import utime
try:
    import ssd1306
except:
    ssd1306 = None

from piotimer import Piotimer
from fifo import Fifo

# ----------------- CONFIG -----------------
SAMPLE_HZ = 250
FIFO_SIZE = 500
ADC_PIN = 26
I2C_SCL = 15
I2C_SDA = 14
OLED_ENABLED = ssd1306 is not None
OLED_WIDTH = 128
OLED_HEIGHT = 64
EXIT_PIN = 7
AVG_WINDOW = 20
HRV_WINDOW_BEATS = 120
MIN_BEATS_TO_CALC = 20
MID = 32768

# ----------------- HARDWARE -----------------
if OLED_ENABLED:
    try:
        i2c = machine.I2C(1, scl=machine.Pin(I2C_SCL),
                          sda=machine.Pin(I2C_SDA), freq=400000)
        oled = ssd1306.SSD1306_I2C(OLED_WIDTH, OLED_HEIGHT, i2c)
    except:
        oled = None
        print("OLED initialization failed")
else:
    oled = None

exit_btn = machine.Pin(EXIT_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
adc = machine.ADC(machine.Pin(ADC_PIN))

# ----------------- FIFO -----------------
samples = Fifo(FIFO_SIZE)
ave_fifo = Fifo(AVG_WINDOW + 1)
for _ in range(AVG_WINDOW):
    try:
        ave_fifo.put(MID)
    except RuntimeError:
        pass

rolling_sum = MID * AVG_WINDOW
history = []
max_hist = 400
low_val = MID
high_val = MID
last_beat_ms = utime.ticks_ms()
beat_flag = False
rr_intervals = []

# ----------------- SAMPLER -----------------
def sampler_irq(tid):
    try:
        val = adc.read_u16()
        if (samples.head + 1) % samples.size != samples.tail:
            samples.put(val)
    except:
        pass

# ----------------- HRV CALCULATIONS -----------------
def compute_hrv_metrics(rr_ms):
    n = len(rr_ms)
    if n == 0:
        return None
    
    mean_rr = sum(rr_ms) / n
    var = sum((x - mean_rr) ** 2 for x in rr_ms) / n
    sdnn = var ** 0.5
    
    if n < 2:
        rmssd = pnn50 = pnn20 = 0.0
    else:
        diffs = [rr_ms[i] - rr_ms[i-1] for i in range(1, n)]
        diffs_sq = [d**2 for d in diffs]
        rmssd = (sum(diffs_sq)/(n-1))**0.5
        pnn50 = 100.0 * sum(abs(d)>50 for d in diffs)/(n-1)
        pnn20 = 100.0 * sum(abs(d)>20 for d in diffs)/(n-1)
    
    mean_hr = 60000.0 / mean_rr if mean_rr > 0 else 0.0
    
    return {
        "mean_rr_ms": mean_rr,
        "sdnn_ms": sdnn,
        "rmssd_ms": rmssd,
        "pnn50_percent": pnn50,
        "pnn20_percent": pnn20,
        "mean_hr_bpm": mean_hr,
        "count": n
    }

# ----------------- DISPLAY -----------------
def show_text_on_oled(lines):
    if oled is None:
        return
    oled.fill(0)
    y = 0
    for line in lines:
        oled.text(str(line), 0, y)
        y += 10
        if y > OLED_HEIGHT-10:
            break
    oled.show()

# ----------------- MAIN FUNCTION -----------------
def run(exit_button=None, display=None, enc=None):
    global rolling_sum, low_val, high_val, last_beat_ms, beat_flag, oled, exit_btn, rr_intervals

    # Use passed parameters if available
    if exit_button is not None:
        exit_btn = exit_button
    if display is not None:
        oled = display

    tmr = Piotimer(Piotimer.PERIODIC, freq=SAMPLE_HZ, callback=sampler_irq)

    print("HRV Monitor starting")
    if oled:
        show_text_on_oled(["HRV MONITOR", "Hold finger..."])

    while True:
        # Exit button check
        if not exit_btn.value():
            utime.sleep_ms(50)
            if not exit_btn.value():
                tmr.deinit()
                if oled:
                    show_text_on_oled(["Exiting..."])
                print("Exiting HRV Monitor")
                return

        # Process samples
        latest = None
        while samples.has_data():
            val = samples.get()
            if val is not None:
                latest = val
        if latest is None:
            continue
        raw = latest

        # Rolling average
        oldest = ave_fifo.get() if ave_fifo.has_data() else MID
        rolling_sum -= oldest
        try:
            ave_fifo.put(raw)
        except RuntimeError:
            pass
        rolling_sum += raw
        avg = rolling_sum / AVG_WINDOW

        # Adaptive threshold
        history.append(avg)
        if avg < low_val:
            low_val = avg
        if avg > high_val:
            high_val = avg
        if len(history) > max_hist:
            removed = history.pop(0)
            if removed == low_val or removed == high_val:
                low_val = min(history)
                high_val = max(history)
        if len(history) < 30:
            continue

        thresh_on = (low_val + high_val*3) / 4
        thresh_off = (low_val + high_val) / 2

        # Beat detection
        if not beat_flag and avg > thresh_on:
            beat_flag = True
            now_ms = utime.ticks_ms()
            ibi = utime.ticks_diff(now_ms, last_beat_ms)
            last_beat_ms = now_ms
            
            if 250 < ibi < 2000:
                rr_intervals.append(ibi)
                if len(rr_intervals) > HRV_WINDOW_BEATS:
                    rr_intervals.pop(0)
                
                bpm = round(60000 / ibi)
                
                if len(rr_intervals) >= MIN_BEATS_TO_CALC:
                    # Calculate and display HRV metrics
                    hrv = compute_hrv_metrics(rr_intervals)
                    clean_beats = len(rr_intervals) - MIN_BEATS_TO_CALC
                    
                    print("HRV: HR=%.1f SDNN=%.2f RMSSD=%.2f pNN50=%.1f%% (Total: %d, Clean: %d)" %
                          (hrv["mean_hr_bpm"], hrv["sdnn_ms"], 
                           hrv["rmssd_ms"], hrv["pnn50_percent"], 
                           len(rr_intervals), clean_beats))
                    
                    if clean_beats >= 10:
                        # Enough clean data for Kubios
                        if oled:
                            show_text_on_oled([
                                "HRV READY!",
                                "HR: %.0f bpm" % hrv["mean_hr_bpm"],
                                "SDNN: %.1f ms" % hrv["sdnn_ms"],
                                "RMSSD: %.1f ms" % hrv["rmssd_ms"],
                                "Clean beats: %d" % clean_beats,
                                "Ready for Kubios!"
                            ])
                    else:
                        # Still need more clean data
                        if oled:
                            show_text_on_oled([
                                "HRV ANALYSIS",
                                "HR: %.0f bpm" % hrv["mean_hr_bpm"],
                                "SDNN: %.1f ms" % hrv["sdnn_ms"],
                                "RMSSD: %.1f ms" % hrv["rmssd_ms"],
                                "Clean: %d/10" % clean_beats,
                                "Collecting..."
                            ])
                else:
                    # Still collecting data
                    if oled:
                        show_text_on_oled([
                            "HRV MONITOR",
                            "Hold finger...",
                            "Collecting data:",
                            "Beats: %d/%d" % (len(rr_intervals), MIN_BEATS_TO_CALC),
                            "Last BPM: %d" % bpm
                        ])
                    print("Collecting: %d/%d beats, BPM: %d" % 
                          (len(rr_intervals), MIN_BEATS_TO_CALC, bpm))
                    
        if beat_flag and avg < thresh_off:
            beat_flag = False

# ----------------- DATA ACCESS -----------------
def get_rr_intervals():
    """Get clean RR intervals for external use (e.g., Kubios)
    
    Returns only the RR intervals after the initial MIN_BEATS_TO_CALC period,
    excluding the first 20 beats used for HRV calculation setup.
    """
    if len(rr_intervals) > MIN_BEATS_TO_CALC:
        # Return only the clean data after initial calculation period
        clean_data = rr_intervals[MIN_BEATS_TO_CALC:]
        print("Returning %d clean RR intervals (excluding first %d setup beats)" % 
              (len(clean_data), MIN_BEATS_TO_CALC))
        return clean_data.copy()
    else:
        print("Not enough data for clean intervals (%d/%d)" % (len(rr_intervals), MIN_BEATS_TO_CALC))
        return []

def get_hrv_status():
    """Get current HRV collection status"""
    clean_beats = max(0, len(rr_intervals) - MIN_BEATS_TO_CALC)
    return {
        "total_beats": len(rr_intervals),
        "clean_beats": clean_beats,
        "ready_for_analysis": len(rr_intervals) >= MIN_BEATS_TO_CALC,
        "ready_for_kubios": clean_beats >= 10,  # Need at least 10 clean beats for Kubios
        "last_bpm": 60000 // rr_intervals[-1] if rr_intervals else 0
    }

# Menu compatibility
def main(exit_button=None, display=None, enc=None):
    run(exit_button, display, enc)

if __name__ == "__main__":
    run()