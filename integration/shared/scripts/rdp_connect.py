#!/usr/bin/env python3
"""Connect to Windows VM via RDP and install the SketchUp Link plugin."""
import sys
import time
import os

HOST = "127.0.0.1"
PORT = 3389
USERNAME = "Docker"
PASSWORD = "admin"

SCREENSHOT_DIR = "/home/jasonkraus/Repos/sketchup-link/integration/shared"

def main():
    # Use pyfreerdp to connect
    from freerdp import connect, disconnect, screenshot
    
    print(f"Connecting to RDP {HOST}:{PORT} as {USERNAME}...")
    
    try:
        session = connect(
            host=HOST,
            port=PORT,
            username=USERNAME,
            password=PASSWORD,
            width=1280,
            height=720,
            # Map the shared folder as a drive
            drive={"Shared": SCREENSHOT_DIR}
        )
        print("Connected!")
        
        time.sleep(5)
        
        # Take screenshot
        img = screenshot(session)
        if img:
            img.save(os.path.join(SCREENSHOT_DIR, "rdp_initial.png"))
            print(f"Screenshot saved ({img.size})")
        
        # Disconnect
        disconnect(session)
        
    except Exception as e:
        print(f"RDP error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
