# HRV History - Local storage and viewing of HRV analysis results

import machine
import utime
import ujson
try:
    import ssd1306
except:
    ssd1306 = None
from fifo import Fifo

# ----------------- CONFIG -----------------
I2C_SCL = 15
I2C_SDA = 14
OLED_ENABLED = ssd1306 is not None
OLED_WIDTH = 128
OLED_HEIGHT = 64
ENC_A, ENC_B, ENC_BTN = 10, 11, 12
EXIT_BTN = 9  # SW_0 button
HISTORY_FILE = "hrv_history.json"
MAX_HISTORY_ENTRIES = 20

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

# ----- ENCODER USING INTERRUPT + FIFO -----
class Encoder:
    def __init__(self, pin_a, pin_b):
        self.a = machine.Pin(pin_a, mode=machine.Pin.IN, pull=machine.Pin.PULL_UP)
        self.b = machine.Pin(pin_b, mode=machine.Pin.IN, pull=machine.Pin.PULL_UP)
        self.fifo = Fifo(100, typecode='i')  # Increased size to prevent overflow

        self.a.irq(handler=self.handler, trigger=machine.Pin.IRQ_RISING, hard=True)

    def handler(self, pin):
        # Simple direction logic: if B is high, counterclockwise
        # Add protection against FIFO overflow
        try:
            if self.b():
                self.fifo.put(-1)
            else:
                self.fifo.put(1)
        except:
            # FIFO full - ignore this input to prevent crash
            pass

# Create default encoder and buttons (for standalone operation)
encoder = None
btn = None
exit_btn = None

def init_hardware():
    """Initialize hardware for standalone operation"""
    global encoder, btn, exit_btn
    if encoder is None:
        encoder = Encoder(ENC_A, ENC_B)
    if btn is None:
        btn = machine.Pin(ENC_BTN, machine.Pin.IN, machine.Pin.PULL_UP)
    if exit_btn is None:
        exit_btn = machine.Pin(EXIT_BTN, machine.Pin.IN, machine.Pin.PULL_UP)

# ----------------- GLOBALS -----------------
current_page = 0
history_data = []

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

# ----------------- HISTORY MANAGEMENT -----------------
def load_history():
    """Load history from file"""
    global history_data
    try:
        print("Attempting to load from:", HISTORY_FILE)
        with open(HISTORY_FILE, 'r') as f:
            content = f.read().strip()
            print("File content length:", len(content))
            if content:
                history_data = ujson.loads(content)
            else:
                history_data = []
        print("Loaded %d history entries" % len(history_data))
    except OSError as e:
        print("File not found (OSError):", e)
        history_data = []
        print("No history file found, starting fresh")
        # Try to create an empty file
        try:
            with open(HISTORY_FILE, 'w') as f:
                f.write('[]')
            print("Created empty history file")
        except Exception as create_error:
            print("Could not create empty file:", create_error)
    except Exception as e:
        print("Error loading history:", e)
        history_data = []

def save_history():
    """Save history to file"""
    try:
        # Keep only the most recent entries
        if len(history_data) > MAX_HISTORY_ENTRIES:
            history_data[:] = history_data[-MAX_HISTORY_ENTRIES:]
        
        print("Attempting to save to:", HISTORY_FILE)
        print("Data to save:", history_data)
        
        # Create the file with explicit path
        with open(HISTORY_FILE, 'w') as f:
            json_str = ujson.dumps(history_data)
            f.write(json_str)
            f.flush()  # Ensure data is written
        
        # Verify the file was created
        try:
            with open(HISTORY_FILE, 'r') as f:
                content = f.read()
                print("File created successfully, content length:", len(content))
        except:
            print("Warning: Could not verify file creation")
        
        print("History saved (%d entries)" % len(history_data))
        return True
    except Exception as e:
        print("Failed to save history:", e)
        print("Error type:", type(e))
        import sys
        sys.print_exception(e)
        return False

def add_history_entry(analysis_data):
    """Add new HRV analysis to history using same format as Kubios database"""
    if analysis_data is None:
        print("No analysis data provided")
        return False
    
    try:
        print("Adding history entry...")
        
        # Load current history first
        load_history()
        
        # Get real current timestamp using same function as Kubios
        try:
            import ntptime
            # Sync with NTP server to get real time
            print("Syncing time with NTP server...")
            ntptime.settime()
            # After ntptime.settime(), utime.time() returns Unix timestamp directly
            timestamp = utime.time()
            print("Time synced, timestamp:", timestamp)
        except Exception as e:
            print("NTP sync failed, using approximate time:", e)
            # Fallback: use approximate current time (December 4, 2025 9:06 UTC)
            # Current Unix timestamp for Dec 4, 2025 9:06 UTC is 1764839160
            base_time = 1764839160  # Dec 4, 2025 9:06 UTC 
            device_uptime_offset = utime.ticks_ms() // 1000  # Convert ms to seconds
            timestamp = base_time + device_uptime_offset
            print("Using approximate timestamp:", timestamp)
        
        # Import config from KubiosHRV
        try:
            import KubiosHRV
            device_mac = KubiosHRV.DEVICE_MAC
            patient_name = KubiosHRV.PATIENT_NAME
            patient_id = KubiosHRV.PATIENT_ID
        except:
            # Fallback values
            device_mac = "28CDC1057762"
            patient_name = "HRV User"
            patient_id = 1
        
        # Create entry using same format as Kubios database record
        entry = {
            "mac": device_mac,
            "timestamp": timestamp,
            "mean_hr": float(analysis_data.get('mean_hr_bpm', 0)),
            "mean_ppi": float(analysis_data.get('mean_rr_ms', 0)),  # PPI is same as RR interval
            "rmssd": float(analysis_data.get('rmssd_ms', 0)),
            "sdnn": float(analysis_data.get('sdnn_ms', 0)),
            "sns": float(analysis_data.get('sns_index', 0)),
            "pns": float(analysis_data.get('pns_index', 0)),
            "patient_id": patient_id,
            # Additional fields for display
            "patient_name": patient_name,
            "readiness": float(analysis_data.get('readiness', 0)),
            "stress_index": float(analysis_data.get('stress_index', 0)),
            "physiological_age": int(analysis_data.get('physiological_age', 0))
        }
        
        print("Created Kubios-format entry:", entry)
        
        # Add to beginning of list (newest first)
        history_data.insert(0, entry)
        print("Added to history_data, new length:", len(history_data))
        
        # Save to file
        save_result = save_history()
        print("Save result:", save_result)
        
        if save_result:
            print("Added entry to history: Score=%.1f, HR=%.1f, Patient=%s" % 
                  (entry["readiness"], entry["mean_hr"], entry["patient_name"]))
            return True
        else:
            print("Failed to save history to file")
            return False
        
    except Exception as e:
        print("Failed to add history entry:", e)
        import sys
        sys.print_exception(e)
        return False

def format_timestamp(timestamp):
    """Format timestamp to readable string"""
    try:
        t = utime.localtime(timestamp)
        return "%02d/%02d %02d:%02d" % (t[1], t[2], t[3], t[4])  # MM/DD HH:MM
    except:
        return "??/?? ??:??"

def format_timestamp_detailed(timestamp):
    """Format timestamp with full date and time"""
    try:
        t = utime.localtime(timestamp)
        return "%04d-%02d-%02d %02d:%02d:%02d" % (t[0], t[1], t[2], t[3], t[4], t[5])
    except:
        return "????-??-?? ??:??:??"

def clear_history():
    """Clear all history"""
    global history_data
    history_data = []
    try:
        with open(HISTORY_FILE, 'w') as f:
            f.write('[]')
        print("History cleared")
        return True
    except:
        print("Failed to clear history")
        return False

# ----------------- DISPLAY FUNCTIONS -----------------
def display_history_list():
    """Display list of history entries"""
    global current_page
    
    if not history_data:
        show_text_on_oled([
            "HRV HISTORY",
            "",
            "No entries found",
            "",
            "Nav: refresh",
            "Exit: return"
        ])
        return
    
    # Calculate pagination - show 3 entries per page
    entries_per_page = 3
    total_pages = (len(history_data) + entries_per_page - 1) // entries_per_page
    current_page = min(current_page, total_pages - 1)
    
    start_idx = current_page * entries_per_page
    end_idx = min(start_idx + entries_per_page, len(history_data))
    
    lines = ["HRV HISTORY (%d)" % len(history_data)]
    
    for i in range(start_idx, end_idx):
        entry = history_data[i]
        time_str = format_timestamp(entry["timestamp"])
        score = entry.get("readiness", 0)
        hr = entry["mean_hr"]
        stress = entry.get("stress_index", 0)
        
        line = "%d.%s S:%.0f H:%.0f St:%.0f" % (i+1, time_str, score, hr, stress)
        lines.append(line)
    
    # Add navigation info
    lines.append("")
    if total_pages > 1:
        lines.append("Rot: page %d/%d" % (current_page + 1, total_pages))
    if history_data:
        lines.append("Btn: view details")
    lines.append("Exit: return")
    
    show_text_on_oled(lines)

def display_history_details(entry_index):
    """Display detailed view of history entry"""
    if entry_index >= len(history_data):
        return False
    
    entry = history_data[entry_index]
    time_str = format_timestamp_detailed(entry["timestamp"])
    patient_name = entry.get("patient_name", "Unknown")
    
    show_text_on_oled([
        "ENTRY #%d DETAILS" % (entry_index + 1),
        "Patient: %s" % patient_name,
        "Time: %s" % time_str,
        "Score: %.1f" % entry.get("readiness", 0),
        "HR: %.1f bpm" % entry["mean_hr"],
        "Stress: %.1f" % entry.get("stress_index", 0),
        "Rot: nav  Btn: back"
    ])
    return True

# ----------------- MAIN FUNCTION -----------------
def run(exit_button=None, display=None, enc=None):
    global current_page, oled, exit_btn, btn, encoder
    
    # Set up hardware references
    if enc is not None:
        # Called from menu - use shared hardware
        encoder = enc
        exit_btn = exit_button if exit_button else machine.Pin(EXIT_BTN, machine.Pin.IN, machine.Pin.PULL_UP)
        oled = display
        btn = machine.Pin(ENC_BTN, machine.Pin.IN, machine.Pin.PULL_UP)  # Encoder button
    else:
        # Standalone mode - initialize our own hardware
        if exit_btn is None:
            exit_btn = machine.Pin(EXIT_BTN, machine.Pin.IN, machine.Pin.PULL_UP)
        if encoder is None:
            encoder = Encoder(ENC_A, ENC_B) 
        if btn is None:
            btn = machine.Pin(ENC_BTN, machine.Pin.IN, machine.Pin.PULL_UP)
    
    # Clear any stale encoder inputs
    if encoder and encoder.fifo.has_data():
        while encoder.fifo.has_data():
            encoder.fifo.get()
    
    print("HRV History starting...")
    
    # Load history data
    load_history()
    
    # Reset page
    current_page = 0
    view_mode = "list"  # "list" or "details"
    selected_entry = 0
    entries_per_page = 3
    
    if oled:
        show_text_on_oled(["HRV HISTORY", "Loading..."])
    
    while True:
        # Exit button check
        if not exit_btn.value():
            utime.sleep_ms(50)
            if not exit_btn.value():
                # Clear encoder FIFO when exiting to prevent crashes
                if encoder and encoder.fifo.has_data():
                    print("Clearing encoder FIFO on exit...")
                    while encoder.fifo.has_data():
                        encoder.fifo.get()
                
                if oled:
                    show_text_on_oled(["Exiting..."])
                print("Exiting HRV History")
                return
        
        # Display current view
        if view_mode == "list":
            display_history_list()
        elif view_mode == "details":
            if not display_history_details(selected_entry):
                view_mode = "list"
                continue
        
        # Rotary encoder navigation for pages/entries
        if encoder and encoder.fifo.has_data():
            move = encoder.fifo.get()
            if view_mode == "list":
                if history_data:
                    total_pages = (len(history_data) + entries_per_page - 1) // entries_per_page
                    if total_pages > 1:
                        # Navigate pages with encoder
                        if move > 0:
                            current_page = (current_page + 1) % total_pages
                        else:  # move < 0 (backward)
                            current_page = (current_page - 1) % total_pages
            elif view_mode == "details":
                # Navigate between entries with encoder
                if move > 0:
                    selected_entry = (selected_entry + 1) % len(history_data)
                else:  # move < 0 (backward)
                    selected_entry = (selected_entry - 1) % len(history_data)
        
        # Encoder button for selecting/entering details
        if not btn.value():
            utime.sleep_ms(50)
            if not btn.value():
                if view_mode == "list":
                    if history_data:
                        # Enter details mode for first entry on current page
                        selected_entry = current_page * entries_per_page
                        if selected_entry < len(history_data):
                            view_mode = "details"
                    else:
                        # No history - reload
                        load_history()
                elif view_mode == "details":
                    # Go back to list view
                    view_mode = "list"
                
                # Wait for button release
                while not btn.value():
                    # Check exit button even while waiting for button release
                    if not exit_btn.value():
                        utime.sleep_ms(50)
                        if not exit_btn.value():
                            # Clear encoder FIFO when exiting
                            if encoder and encoder.fifo.has_data():
                                print("Clearing encoder FIFO on nested exit...")
                                while encoder.fifo.has_data():
                                    encoder.fifo.get()
                            
                            if oled:
                                show_text_on_oled(["Exiting..."])
                            print("Exiting HRV History")
                            return
                    utime.sleep_ms(10)
        
        utime.sleep_ms(10)

# ----------------- EXTERNAL API -----------------
def add_analysis_to_history(analysis_data):
    """External function to add analysis data to history"""
    print("HRVHistory: add_analysis_to_history called")
    if analysis_data:
        print("HRVHistory: Got analysis data with keys:", list(analysis_data.keys()))
    result = add_history_entry(analysis_data)
    print("HRVHistory: add_history_entry returned:", result)
    return result

def test_file_creation():
    """Test function to check if we can create files"""
    print("Testing file creation...")
    test_file = "test_write.txt"
    try:
        with open(test_file, 'w') as f:
            f.write("test")
        print("✓ Can create files")
        
        with open(test_file, 'r') as f:
            content = f.read()
        print("✓ Can read files, content:", content)
        
        # Clean up
        import os
        os.remove(test_file)
        print("✓ Can delete files")
        return True
    except Exception as e:
        print("✗ File operations failed:", e)
        return False

def get_history_count():
    """Get number of history entries"""
    try:
        load_history()
        return len(history_data)
    except:
        return 0

# Menu compatibility
def main(exit_button=None, display=None, enc=None):
    run(exit_button, display, enc)

if __name__ == "__main__":
    run()